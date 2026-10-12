"""Loopback browser callbacks around the shared MCP OAuth/PKCE adapter."""

import asyncio
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.client.auth import AuthorizationCodeResult
from mcp.shared.auth import OAuthClientInformationFull
from starlette.responses import PlainTextResponse
from umbod.core.connectors.downstream_mcp.adapters.fastmcp.oauth import (
    AuthorizationDocument,
    ConnectorOAuth,
    ConnectorOAuthStorage,
    SignInRequired,
)

from .security import CredentialVault


class KeychainOAuthStorage(ConnectorOAuthStorage):
    def __init__(self, vault: CredentialVault, key: str, url: str) -> None:
        super().__init__(AuthorizationDocument(endpoint_url=url), connector_id=key)
        self.vault, self.reference = vault, f"python:oauth:{key}"
        self.expected_value = None

    async def load(self) -> None:
        value = self.vault.get(self.reference)
        self.expected_value = value
        self.document = AuthorizationDocument(endpoint_url=self.document.endpoint_url)
        if value:
            document = AuthorizationDocument.model_validate_json(value)
            if document.endpoint_url != self.document.endpoint_url:
                raise ValueError("OAuth endpoint changed; sign in again")
            self.document = document

    async def save(self) -> None:
        if self.vault.get(self.reference) != self.expected_value:
            raise SignInRequired()
        value = self.document.model_dump_json()
        self.vault.set(self.reference, value)
        self.expected_value = value


class DesktopOAuth:
    def __init__(self, upstreams) -> None:
        self.upstreams = upstreams
        self.callbacks: dict[str, asyncio.Future] = {}
        self.expected_states: dict[str, str] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.results: dict[str, str] = {}

    async def begin(self, key: str, client_id: str = "") -> dict:
        server = self.upstreams.state.data["servers"][key]
        if server["transport"] != "http" or urlsplit(server["url"]).scheme != "https":
            raise ValueError("Browser sign-in requires an HTTPS connector")
        if key in self.tasks and not self.tasks[key].done():
            raise ValueError("Browser sign-in is already in progress")
        nonce = secrets.token_urlsafe(32)
        callback = asyncio.get_running_loop().create_future()
        redirect = asyncio.get_running_loop().create_future()
        self.callbacks[nonce] = callback
        storage = KeychainOAuthStorage(self.upstreams.vault, key, server["url"])
        await storage.load()
        if client_id:
            storage.document.client_info = OAuthClientInformationFull(
                client_id=client_id
            )
            storage.document.tokens = None
            storage.document.expires_at = None
            await storage.save()

        async def redirect_handler(url):
            self.expected_states[nonce] = parse_qs(urlsplit(url).query)["state"][0]
            if not redirect.done():
                redirect.set_result(url)

        async def callback_handler():
            async with asyncio.timeout(300):
                return await callback

        auth = ConnectorOAuth(
            storage,
            redirect_uri=f"{self.upstreams.origin}/desktop/oauth/callback/{nonce}",
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

        async def authorize():
            try:
                async with Client(
                    StreamableHttpTransport(server["url"], auth=auth)
                ) as client:
                    await client.list_tools()
                server["oauth"] = True
                self.upstreams.state.save()
                await self.upstreams.start(key, server)
                self.results[key] = "signed_in"
                if not redirect.done():
                    redirect.set_result("")
            except Exception:  # noqa: BLE001 - boundary redacts upstream and vault secrets
                self.results[key] = "failed"
                if not redirect.done():
                    redirect.set_exception(ValueError("Browser sign-in failed"))
            finally:
                self.callbacks.pop(nonce, None)
                self.expected_states.pop(nonce, None)

        self.results[key] = "pending"
        self.tasks[key] = asyncio.create_task(authorize())
        async with asyncio.timeout(30):
            url = await asyncio.shield(redirect)
        return {"url": url, "status": self.results.get(key, "pending")}

    async def callback(self, request):
        future = self.callbacks.get(request.path_params["nonce"])
        if future is None or future.done():
            return PlainTextResponse(
                "Sign-in has expired. Return to Umbod and retry.", status_code=400
            )
        code, state = (
            request.query_params.get("code"),
            request.query_params.get("state"),
        )
        if not state or not secrets.compare_digest(
            state, self.expected_states.get(request.path_params["nonce"], "")
        ):
            return PlainTextResponse("Missing authorization response.", status_code=400)
        if request.query_params.get("error"):
            future.set_exception(ValueError("Browser authorization was declined"))
            return PlainTextResponse(
                "Sign-in was not approved. Return to Umbod to try again."
            )
        if not code:
            return PlainTextResponse("Missing authorization response.", status_code=400)
        future.set_result(
            AuthorizationCodeResult(
                code=code, state=state, iss=request.query_params.get("iss")
            )
        )
        return PlainTextResponse(
            "Authorization received. Return to Umbod to check the result."
        )

    async def refresh(self, key):
        server = self.upstreams.state.data["servers"][key]
        storage = KeychainOAuthStorage(self.upstreams.vault, key, server["url"])
        await storage.load()
        if storage.document.tokens is None or not storage.document.tokens.refresh_token:
            raise ValueError("Sign in again to renew this credential")
        storage.document.expires_at = time.time() - 1
        await storage.save()
        async with Client(
            StreamableHttpTransport(server["url"], auth=ConnectorOAuth(storage))
        ) as client:
            await client.list_tools()
        await self.upstreams.start(key, server)
        return {"status": "refreshed"}

    async def forget(self, key):
        task = self.tasks.get(key)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.upstreams.vault.delete(f"python:oauth:{key}")
        self.results.pop(key, None)

    async def logout(self, key):
        await self.forget(key)
        server = self.upstreams.state.data["servers"][key]
        server["oauth"] = False
        self.upstreams.state.save()
        await self.upstreams.start(key, server)

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
