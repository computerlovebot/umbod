"""Adapt desktop-owned transports to the shared downstream HTTP connector API."""

import asyncio
import sys
from uuid import uuid4

from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from fastmcp.server import create_proxy
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from .models import DesktopServer
from .security import CredentialVault, LoopbackAuthentication
from .storage import DesktopState


class ProxyLifetime:
    """Enter and exit ASGI lifespan in one task (required by AnyIO/ContextVars)."""

    def __init__(self, app):
        self.app = app
        self.ready = asyncio.get_running_loop().create_future()
        self.stopped = asyncio.Event()
        self.task = asyncio.create_task(self.run())

    async def run(self):
        try:
            async with self.app.lifespan(self.app):
                self.ready.set_result(None)
                await self.stopped.wait()
        except BaseException as error:
            if not self.ready.done():
                self.ready.set_exception(error)
            raise

    async def start(self):
        try:
            await self.ready
        except BaseException:
            await asyncio.gather(self.task, return_exceptions=True)
            raise

    async def aclose(self):
        self.stopped.set()
        await self.task


class DesktopUpstreams:
    def __init__(
        self, state: DesktopState, vault: CredentialVault, token: str, origin: str
    ) -> None:
        self.state, self.vault, self.token, self.origin = state, vault, token, origin
        self.apps: dict[str, object] = {}
        self.lifetimes: dict[str, ProxyLifetime] = {}

    async def start(self, key: str, server: dict) -> None:
        headers = {
            name: self._credential(ref)
            for name, ref in server.get("headers", {}).items()
        }
        if server["transport"] == "stdio":
            env = {
                name: self._credential(ref)
                for name, ref in server.get("env", {}).items()
            }
            transport = StdioTransport(
                command=server["command"],
                args=server.get("args", []),
                env=env,
                log_file=sys.stderr,
            )
        elif server["transport"] == "http":
            auth = None
            if server.get("oauth"):
                from .oauth import ConnectorOAuth, KeychainOAuthStorage

                auth = ConnectorOAuth(
                    KeychainOAuthStorage(self.vault, key, server["url"])
                )
            transport = StreamableHttpTransport(
                server["url"], headers=headers, auth=auth
            )
        else:
            raise ValueError("Unsupported connector transport")
        proxy = create_proxy(
            transport,
            mode="auto",
            provider_error_strategy="raise",
            name=f"desktop-upstream-{key}",
        )
        app = proxy.http_app(path="/mcp")
        lifetime = ProxyLifetime(app)
        await lifetime.start()
        old = self.lifetimes.pop(key, None)
        self.apps[key] = LoopbackAuthentication(app, self.token)
        self.lifetimes[key] = lifetime
        if old:
            await old.aclose()

    def _credential(self, reference: str) -> str:
        if not reference.startswith("upstream:"):
            raise ValueError("Only upstream credential references are allowed")
        value = self.vault.get(reference)
        if value is None:
            raise ValueError("A connector credential is missing from Keychain")
        return value

    async def prepare(self, server: dict) -> dict:
        server = DesktopServer.model_validate(server).model_dump()
        key = server.get("host_id") or uuid4().hex
        if key not in self.state.data["servers"] and server.get("host_id"):
            raise ValueError("Unknown desktop connector")
        try:
            await self.start(key, server)
            self.state.data.setdefault("transport_errors", {}).pop(key, None)
        except (ValueError, OSError):
            # Keep editable offline drafts, but stop the previously configured transport.
            old = self.lifetimes.pop(key, None)
            self.apps.pop(key, None)
            if old:
                await old.aclose()
            self.state.data.setdefault("transport_errors", {})[key] = (
                "Restore the executable or Keychain credential, then reconnect."
            )
        self.state.data["servers"][key] = {**server, "host_id": key}
        self.state.save()
        return {
            "host_id": key,
            "configuration": {
                "auth_mode": "static_bearer",
                "endpoint_url": f"{self.origin}/desktop/upstreams/{key}/mcp",
                "header_type": "bearer",
                "bearer_token": self.token,
            },
        }

    async def restore(self) -> None:
        errors = self.state.data.setdefault("transport_errors", {})
        for key, server in self.state.data["servers"].items():
            try:
                await self.start(key, server)
                errors.pop(key, None)
            except (ValueError, OSError):
                errors[key] = (
                    "Reconnect this connector after restoring its executable or Keychain credentials."
                )
        self.state.save()

    async def close(self) -> None:
        for lifetime in self.lifetimes.values():
            await lifetime.aclose()
        self.lifetimes.clear()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        parts = scope["path"].split("/")
        key = parts[3] if len(parts) > 3 else ""
        app = self.apps.get(key)
        if app is None:
            await JSONResponse({"detail": "Not found"}, status_code=404)(
                scope, receive, send
            )
            return
        path = "/" + "/".join(parts[4:])
        await app(
            {**scope, "path": path, "raw_path": path.encode(), "root_path": ""},
            receive,
            send,
        )
