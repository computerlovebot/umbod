"""Retire a running legacy host through its authenticated lifecycle endpoint."""

import asyncio
import json

import httpx

from .models import loopback_origin


async def retire_legacy_host(directory, profile):
    path = directory / "runtime.json"
    if not path.exists():
        return
    record = json.loads(path.read_text())
    if record.get("profile") != profile:
        raise ValueError("Legacy runtime profile does not match")
    origin = loopback_origin(record["management"])
    async with httpx.AsyncClient(
        base_url=origin,
        timeout=3,
        trust_env=False,
        headers={"Authorization": f"Bearer {record['admin_token']}"},
    ) as client:
        try:
            response = await client.post("/manage", json={"action": "health"})
        except httpx.ConnectError:
            return
        response.raise_for_status()
        health = response.json()
        if health.get("profile") != profile or health.get("pid") != record["pid"]:
            raise ValueError("Legacy runtime identity does not match")
        response = await client.post("/manage", json={"action": "shutdown"})
        response.raise_for_status()
        async with asyncio.timeout(15):
            while path.exists():
                await asyncio.sleep(0.05)


def saved_agent_hashes(directory):
    """Retain existing global-permission client identities without extracting secrets."""
    path = directory / "config.json"
    if not path.exists():
        return []
    document = json.loads(path.read_text())
    clients = list(document.get("clients", []))
    if document.get("connection"):
        clients.append(document["connection"])
    return sorted(
        {
            client["token_hash"]
            for client in clients
            if isinstance(client.get("token_hash"), str)
            and len(client["token_hash"]) == 64
            and all(c in "0123456789abcdef" for c in client["token_hash"])
        }
    )


def saved_port(directory):
    for filename, field in (
        ("python-endpoint.json", "port"),
        ("config.json", "gateway_port"),
    ):
        path = directory / filename
        if path.exists():
            port = json.loads(path.read_text()).get(field)
            if port is not None:
                if type(port) is not int or not 1 <= port <= 65535:
                    raise ValueError("Invalid saved local port")
                return port
    return 0
