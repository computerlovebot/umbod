import asyncio
import time
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx2
import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata, OAuthToken
from starlette.requests import Request
from test_runtime import MemoryVault
from umbod.core.connectors.downstream_mcp.adapters.fastmcp.oauth import (
    ConnectorOAuth,
    SignInRequired,
)

from umbod_desktop.oauth import DesktopOAuth, KeychainOAuthStorage


async def test_keychain_refresh_is_serialized_persistent_and_cannot_resurrect_logout():
    vault = MemoryVault()
    storage = KeychainOAuthStorage(vault, "fixture", "https://tools.example/mcp")
    storage.document.client_info = OAuthClientInformationFull(client_id="fixture")
    storage.document.tokens = OAuthToken(
        access_token="expired", refresh_token="refresh", token_type="Bearer"
    )
    storage.document.expires_at = time.time() - 1
    storage.document.metadata = OAuthMetadata(
        issuer="https://auth.example",
        authorization_endpoint="https://auth.example/authorize",
        token_endpoint="https://auth.example/token",
        response_types_supported=["code"],
    )
    storage.document.authorization_server = "https://auth.example"
    await storage.save()
    refreshes = []

    async def handle(request):
        if str(request.url) == "https://auth.example/token":
            assert parse_qs(request.content.decode())["grant_type"] == ["refresh_token"]
            refreshes.append(request)
            await asyncio.sleep(0.01)
            return httpx2.Response(
                200,
                json={
                    "access_token": "fresh",
                    "refresh_token": "rotated",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        assert request.headers["authorization"] == "Bearer fresh"
        return httpx2.Response(200, json={})

    async def use():
        auth = ConnectorOAuth(
            KeychainOAuthStorage(vault, "fixture", "https://tools.example/mcp")
        )
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(handle), auth=auth
        ) as client:
            assert (await client.post("https://tools.example/mcp")).status_code == 200

    await asyncio.gather(use(), use())
    await use()
    assert len(refreshes) == 1
    await storage.load()
    assert storage.document.tokens.refresh_token == "rotated"
    vault.delete(storage.reference)
    with pytest.raises(SignInRequired):
        await storage.save()
    assert vault.get(storage.reference) is None


async def test_wrong_callback_state_does_not_consume_pending_sign_in():
    oauth = DesktopOAuth(SimpleNamespace())
    future = asyncio.get_running_loop().create_future()
    oauth.callbacks["nonce"] = future
    oauth.expected_states["nonce"] = "expected"

    def request(state):
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/desktop/oauth/callback/nonce",
                "path_params": {"nonce": "nonce"},
                "query_string": f"code=fixture&state={state}".encode(),
                "headers": [],
            }
        )

    assert (await oauth.callback(request("wrong"))).status_code == 400
    assert not future.done()
    assert (await oauth.callback(request("expected"))).status_code == 200
    assert future.result().code == "fixture"
    assert (await oauth.callback(request("expected"))).status_code == 400
