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


async def test_declined_browser_consent_finishes_pending_callback():
    oauth = DesktopOAuth(SimpleNamespace())
    future = asyncio.get_running_loop().create_future()
    oauth.callbacks["nonce"] = future
    oauth.expected_states["nonce"] = "expected"
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/desktop/oauth/callback/nonce",
            "path_params": {"nonce": "nonce"},
            "query_string": b"error=access_denied&state=expected",
            "headers": [],
        }
    )
    assert (await oauth.callback(request)).status_code == 200
    with pytest.raises(ValueError, match="declined"):
        await future


async def test_runtime_reauthentication_is_reported_and_persisted(tmp_path):
    from umbod_desktop.oauth import RuntimeOAuth
    from umbod_desktop.storage import DesktopState
    from umbod_desktop.upstreams import DesktopUpstreams

    vault = MemoryVault()
    upstreams = DesktopUpstreams(
        DesktopState(tmp_path), vault, "fixture", "http://127.0.0.1:8000"
    )
    storage = KeychainOAuthStorage(vault, "fixture", "https://tools.example/mcp")
    storage.document.client_info = OAuthClientInformationFull(client_id="fixture")
    storage.document.metadata = OAuthMetadata(
        issuer="https://tools.example",
        authorization_endpoint="https://tools.example/authorize",
        token_endpoint="https://tools.example/token",
        response_types_supported=["code"],
    )
    storage.document.authorization_server = "https://tools.example"
    await storage.save()

    async def handle(request):
        return httpx2.Response(404 if ".well-known" in str(request.url) else 401)

    auth = RuntimeOAuth(storage, upstreams, "fixture")
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(handle), auth=auth
    ) as client:
        with pytest.raises(SignInRequired):
            await client.post("https://tools.example/mcp")
    assert DesktopOAuth(upstreams).results["fixture"] == "sign_in_required"
    restored = DesktopUpstreams(
        DesktopState(tmp_path), vault, "fixture", "http://127.0.0.1:8000"
    )
    assert restored.authentication_status["fixture"] == "sign_in_required"


async def test_http_challenge_and_success_update_connection_status(tmp_path):
    import socket

    import uvicorn
    from fastmcp import Client, FastMCP
    from fastmcp.client.transports import StreamableHttpTransport
    from fastmcp.server.auth import AccessToken, TokenVerifier

    from umbod_desktop.storage import DesktopState
    from umbod_desktop.upstreams import DesktopUpstreams

    class FixtureVerifier(TokenVerifier):
        async def verify_token(self, token):
            if token == "fixture-token":
                return AccessToken(token=token, client_id="fixture", scopes=[])
            return None

    fixture = FastMCP("protected", auth=FixtureVerifier())

    @fixture.tool
    def echo() -> str:
        return "fixture"

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        url = f"http://127.0.0.1:{listener.getsockname()[1]}/mcp"
        server = uvicorn.Server(
            uvicorn.Config(fixture.http_app(path="/mcp"), log_level="error")
        )
        task = asyncio.create_task(server.serve(sockets=[listener]))
        upstreams = DesktopUpstreams(
            DesktopState(tmp_path), MemoryVault(), "fixture", "http://127.0.0.1:8000"
        )
        try:
            async with asyncio.timeout(15):
                while not server.started:
                    await asyncio.sleep(0.01)
                prepared = await upstreams.prepare(
                    {"name": "Protected", "transport": "http", "url": url}
                )
                key = prepared["host_id"]
                proxy = upstreams.apps[key]

                def transport():
                    return StreamableHttpTransport(
                        "http://127.0.0.1/mcp",
                        headers={"Authorization": "Bearer fixture"},
                        httpx_client_factory=lambda **kw: httpx2.AsyncClient(
                            transport=httpx2.ASGITransport(app=proxy), **kw
                        ),
                    )

                with pytest.raises(Exception):
                    async with Client(transport()) as client:
                        await client.list_tools()
                assert upstreams.authentication_status[key] == "sign_in_required"
                upstreams.vault.set("upstream:fixture", "Bearer fixture-token")
                await upstreams.prepare(
                    {
                        "host_id": key,
                        "name": "Protected",
                        "transport": "http",
                        "url": url,
                        "headers": {"Authorization": "upstream:fixture"},
                    }
                )
                proxy = upstreams.apps[key]
                async with Client(transport()) as client:
                    assert [tool.name for tool in await client.list_tools()] == ["echo"]
                assert upstreams.authentication_status[key] == "signed_out"
        finally:
            await upstreams.close()
            server.should_exit = True
            await task
