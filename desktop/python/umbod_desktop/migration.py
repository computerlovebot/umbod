"""Resumable legacy import. Original JSON and Keychain entries remain untouched."""

import asyncio
import hashlib
import json
import time

import httpx
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from umbod.core.connectors.downstream_mcp.adapters.fastmcp.oauth import (
    AuthorizationDocument,
)

from .security import DESKTOP_GROUP
from .storage import atomic_json


class DesktopMigration:
    def __init__(self, directory, state, upstreams, api, token):
        self.directory, self.state, self.upstreams = directory, state, upstreams
        self.lock = asyncio.Lock()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        )

    async def request(self, method, path, body=None):
        response = await self.client.request(method, "/api/admin" + path, json=body)
        response.raise_for_status()
        return response.json() if response.content else {}

    async def run(self):
        async with self.lock:
            await self._run()

    async def _run(self):
        source = self.directory / "config.json"
        if (
            not source.exists()
            or self.state.data.get("migration", {}).get("status") == "complete"
        ):
            return
        payload = source.read_bytes()
        legacy = json.loads(payload)
        digest = hashlib.sha256(payload).hexdigest()
        journal = self.state.data.setdefault(
            "migration",
            {"status": "pending", "source_sha256": digest, "connectors": {}},
        )
        if journal["source_sha256"] != digest:
            raise ValueError(
                "Legacy settings changed during migration; restore the saved source before retrying"
            )
        backup = self.directory / "config.before-python.json"
        if not backup.exists():
            atomic_json(backup, legacy)
        journal["status"] = "importing"
        self.state.save()
        try:
            await self.request("POST", f"/mcp-permissions/groups/{DESKTOP_GROUP}")
            for server in legacy.get("servers", []):
                old_id = server["id"]
                entry = journal["connectors"].setdefault(old_id, {})
                if entry.get("complete"):
                    continue
                if "host_id" not in entry:
                    prepared = await self.upstreams.prepare(server)
                    entry["host_id"] = prepared["host_id"]
                    self.state.save()
                host_id = entry["host_id"]
                if (
                    server.get("oauth")
                    and self.upstreams.vault.get(f"python:oauth:{host_id}") is None
                ):
                    raw = self.upstreams.vault.get(f"upstream:oauth:{old_id}")
                    if raw is None:
                        raise ValueError("Legacy OAuth credential is missing")
                    saved = json.loads(raw)
                    if saved["resource"].rstrip("/") != server["url"].rstrip("/"):
                        raise ValueError("OAuth resource does not match")
                    document = AuthorizationDocument(
                        endpoint_url=server["url"],
                        client_info=OAuthClientInformationFull(
                            client_id=saved["client_id"]
                        ),
                        tokens=OAuthToken(
                            access_token=saved["access"],
                            token_type="Bearer",
                            refresh_token=saved.get("refresh"),
                            expires_in=max(0, int(saved["expires"] - time.time())),
                        ),
                        expires_at=saved["expires"],
                    )
                    self.upstreams.vault.set(
                        f"python:oauth:{host_id}", document.model_dump_json()
                    )
                config = {
                    "auth_mode": "static_bearer",
                    "endpoint_url": f"{self.upstreams.origin}/desktop/upstreams/{host_id}/mcp",
                    "header_type": "bearer",
                    "bearer_token": self.upstreams.token,
                }
                if "id" not in entry:
                    # Stable public path allows recovery if creation committed before journaling.
                    slug = "import-" + hashlib.sha256(old_id.encode()).hexdigest()[:24]
                    inventory = await self.request("GET", "/connectors/mcp")
                    existing = None
                    for item in inventory["connectors"]:
                        detail = await self.request(
                            "GET", f"/connectors/mcp/{item['connector_id']}"
                        )
                        if detail["public_path"] == f"/mcp/proxies/{slug}":
                            existing = detail
                            break
                    created = existing or await self.request(
                        "POST",
                        "/connectors/mcp",
                        {
                            "metadata": {
                                "display_name": server["name"],
                                "tool_name_prefix": slug.replace("-", "_"),
                                "capability_description": f"Tools from {server['name']}",
                                "public_path": f"/mcp/proxies/{slug}",
                            },
                            "configuration": config,
                        },
                    )
                    entry["id"] = created["connector_id"]
                    self.upstreams.state.data["servers"][host_id]["id"] = entry["id"]
                    self.state.save()
                base = f"/connectors/mcp/{entry['id']}"
                await self.request("POST", base + "/discoveries")
                tools = (await self.request("GET", base + "/tools"))["tools"]
                allowed = legacy.get("allowed_tools")
                if allowed is None:
                    client_ids = [client["id"] for client in legacy.get("clients", [])]
                    sets = [
                        set(legacy.get("grants", {}).get(client, []))
                        for client in client_ids
                    ]
                    allowed = set.intersection(*sets) if sets else set()
                selected = [
                    tool["name"]
                    for tool in tools
                    if f"{old_id}.{tool['name']}" in allowed
                ]
                if selected:
                    await self.request(
                        "PUT",
                        base + "/tools/activation",
                        {
                            "tools": [
                                {"tool_id": name, "activation_status": "enabled"}
                                for name in selected
                            ]
                        },
                    )
                    await self.request(
                        "PUT",
                        f"/mcp-permissions/groups/{DESKTOP_GROUP}/permissions",
                        {
                            "capabilities": [
                                {
                                    "connector_id": entry["id"],
                                    "capability_kind": "tool",
                                    "capability_key": name,
                                    "permission_status": "enabled",
                                }
                                for name in selected
                            ]
                        },
                    )
                await self.request("PUT", base + "/publication")
                entry["complete"] = True
                self.state.save()
            for field in (
                "daily_calls",
                "daily_tracking_started",
                "diagnostics",
                "client_setup",
            ):
                if field in legacy:
                    self.state.data.setdefault(field, legacy[field])
            if legacy.get("activation") and "activation" not in self.state.data:
                journey = dict(legacy["activation"])
                entry = journal["connectors"].get(journey.get("server"), {})
                journey["server"] = entry.get("id", journey.get("server"))
                self.state.data["activation"] = journey
            usage = self.state.data.setdefault("tool_usage", {})
            for name, counts in legacy.get("tool_usage", {}).items():
                old_id, _, tool = name.partition(".")
                new_id = journal["connectors"].get(old_id, {}).get("id", old_id)
                usage.setdefault(f"{new_id}.{tool}", counts)
            journal["status"] = "complete"
            journal.pop("error", None)
        except Exception:  # noqa: BLE001 - boundary redacts upstream and vault secrets
            journal["status"] = "needs_attention"
            journal["error"] = (
                "Some connectors could not be imported. Original settings and credentials are preserved; reconnect the upstream and retry."
            )
        finally:
            self.state.save()

    async def close(self):
        await self.client.aclose()
