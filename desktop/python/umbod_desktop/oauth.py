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

from .oauth_discovery import discover
from .security import CredentialVault

CLIENT_METADATA_URL = "https://umbod.ai/oauth/client-metadata.json"


class DesktopOAuthFailure(ValueError):
    """Only fixed, secret-free messages may be constructed at this boundary."""


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


class DesktopConnectorOAuth(ConnectorOAuth):
    def __init__(self, *args, requested_scope="", metadata_url=None, force_authorization=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.requested_scope = requested_scope
        self.force_authorization = force_authorization
        self.token_received = False
        self.context.client_metadata_url = metadata_url
        self.context.client_metadata.token_endpoint_auth_method = "none"

    async def _initialize(self):
        await super()._initialize()
        if self.context.client_info and self.context.client_info.client_id == CLIENT_METADATA_URL:
            self.context.client_metadata_url = CLIENT_METADATA_URL
        if self.force_authorization:
            # Keep the saved authorization usable if the user cancels this attempt,
            # but do not silently reuse it instead of requesting the chosen scopes.
            self.context.current_tokens = None
            self.context.token_expiry_time = None

    async def _perform_authorization(self):
        # Discovery advertises available scopes, not the user's permission choice.
        # Apply the explicit limit after the SDK's discovery/step-up selection.
        if self.requested_scope:
            self.context.client_metadata.scope = self.requested_scope
        return await super()._perform_authorization()

    async def _handle_token_response(self, response):
        if response.status_code not in {200, 201}:
            await response.aread()
            try:
                code = response.json().get("error")
            except (ValueError, AttributeError):
                code = None
            if not isinstance(code, str):
                code = None
            if code == "invalid_client":
                # A rejected registration cannot be reused. The next attempt must
                # register again instead of trapping the user in the same failure.
                self.storage.document.client_info = None
                self.storage.document.tokens = None
                self.storage.document.expires_at = None
                await self.storage.save()
            reasons = {
                "invalid_client": "The provider rejected the registered client.",
                "invalid_grant": "The authorization code expired or did not match this sign-in.",
                "invalid_scope": "The provider rejected the requested permissions.",
                "invalid_request": "The provider rejected the token request.",
                "unauthorized_client": "This client is not authorized for this provider.",
            }
            raise DesktopOAuthFailure(
                reasons.get(code, "The provider rejected the token exchange.")
                + f" (HTTP {response.status_code}). Try signing in again."
            )
        await super()._handle_token_response(response)
        self.token_received = True
        self.force_authorization = False
        self.storage.document.metadata = self.context.oauth_metadata
        self.storage.document.authorization_server = self.context.auth_server_url
        await self.storage.save()


class RuntimeOAuth(DesktopConnectorOAuth):
    """Surface a required interactive login without prompting from a tool call."""

    def __init__(self, storage, upstreams, key):
        super().__init__(storage)
        self.upstreams, self.key = upstreams, key

    async def _perform_authorization(self):
        self.upstreams.authentication_status[self.key] = "sign_in_required"
        self.upstreams.state.save()
        raise SignInRequired()


class DesktopOAuth:
    def __init__(self, upstreams) -> None:
        self.upstreams = upstreams
        self.callbacks: dict[str, asyncio.Future] = {}
        self.expected_states: dict[str, str] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.results: dict[str, str] = getattr(upstreams, "authentication_status", {})
        self.errors: dict[str, str] = {}
        self.previews: dict[str, dict] = {}
        self.stages: dict[str, str] = {}
        self.events: dict[str, list[dict]] = {}

    async def begin(self, key: str, client_id: str = "", scopes: str | None = None) -> dict:
        server = self.upstreams.state.data["servers"][key]
        if server["transport"] != "http" or urlsplit(server["url"]).scheme != "https":
            raise ValueError("Browser sign-in requires an HTTPS connector")
        if key in self.tasks and not self.tasks[key].done():
            raise ValueError("Browser sign-in is already in progress")
        if scopes is not None:
            if not isinstance(scopes, str):
                raise ValueError("OAuth scopes must be a space-separated string")
            server["oauth_scopes"] = " ".join(scopes.split())
            self.upstreams.state.save()
        # Registration binds the client to this URI. State remains fresh per attempt;
        # the path must survive retries and application restarts.
        nonce = key
        redirect_uri = f"{self.upstreams.origin}/desktop/oauth/callback/{nonce}"
        callback = asyncio.get_running_loop().create_future()
        redirect = asyncio.get_running_loop().create_future()
        storage = KeychainOAuthStorage(self.upstreams.vault, key, server["url"])
        await storage.load()
        registered = storage.document.client_info
        preview = self.previews.get(key, {})
        use_metadata = (not client_id and registered is None and preview.get("registration") == "hosted_metadata") or (
            registered is not None and registered.client_id == CLIENT_METADATA_URL and not client_id
        )
        if use_metadata:
            redirect_uri = f"{self.upstreams.origin}/desktop/oauth/callback"
        if registered and registered.redirect_uris and (
            (not use_metadata and redirect_uri not in {str(uri) for uri in registered.redirect_uris})
            or registered.token_endpoint_auth_method not in {None, "none"}
        ):
            storage.document.client_info = None
            storage.document.tokens = None
            storage.document.expires_at = None
            await storage.save()
        if client_id:
            storage.document.client_info = OAuthClientInformationFull(
                client_id=client_id
            )
            storage.document.tokens = None
            storage.document.expires_at = None
            await storage.save()

        self.callbacks[nonce] = callback

        async def redirect_handler(url):
            self.record(key, "browser")
            self.expected_states[nonce] = parse_qs(urlsplit(url).query)["state"][0]
            if not redirect.done():
                redirect.set_result(url)

        async def callback_handler():
            async with asyncio.timeout(300):
                return await callback

        auth = DesktopConnectorOAuth(
            storage,
            requested_scope=server.get("oauth_scopes", ""),
            metadata_url=CLIENT_METADATA_URL if use_metadata else None,
            force_authorization=True,
            redirect_uri=redirect_uri,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

        async def authorize():
            try:
                async with Client(
                    StreamableHttpTransport(server["url"], auth=auth)
                ) as client:
                    self.record(key, "discovery")
                    await client.list_tools()
                server["oauth"] = True
                self.upstreams.state.save()
                await self.upstreams.start(key, server)
                self.results[key] = "signed_in"
                self.record(key, "connected")
                if not redirect.done():
                    redirect.set_result("")
            except Exception as exc:  # noqa: BLE001 - never expose upstream exception text
                authorized = auth.token_received
                if authorized:
                    server["oauth"] = True
                    self.upstreams.state.save()
                self.results[key] = "discovery_failed" if authorized else "failed"
                self.record(key, "discovery" if authorized else self.stages.get(key, "authorization"), failed=True)
                self.errors[key] = self.failure_message(exc)
                if not redirect.done():
                    redirect.set_exception(ValueError("Browser sign-in failed"))
            finally:
                if not redirect.done():
                    redirect.set_result("")
                self.callbacks.pop(nonce, None)
                self.expected_states.pop(nonce, None)

        self.record(key, "discovery")
        self.results[key] = "pending"
        self.errors.pop(key, None)
        self.tasks[key] = asyncio.create_task(authorize())
        async with asyncio.timeout(30):
            url = await asyncio.shield(redirect)
        return {"url": url, "status": self.results.get(key, "pending")}

    def record(self, key, stage, failed=False):
        self.stages[key] = stage
        events = self.events.setdefault(key, [])
        events.append({"time": int(time.time()), "stage": stage, "result": "failed" if failed else "started"})
        del events[:-20]

    async def discover(self, key):
        self.record(key, "metadata")
        self.previews[key] = await discover(self.upstreams.state.data["servers"][key]["url"])
        return {**await self.details(key), **self.previews[key]}

    async def details(self, key):
        server = self.upstreams.state.data["servers"][key]
        storage = KeychainOAuthStorage(self.upstreams.vault, key, server["url"])
        await storage.load()
        document = storage.document
        metadata = document.metadata
        return {
            "callback_url": f"{self.upstreams.origin}/desktop/oauth/callback" + ("" if document.client_info and document.client_info.client_id == CLIENT_METADATA_URL else f"/{key}"),
            "has_authorization": document.tokens is not None,
            "granted_scopes": document.tokens.scope if document.tokens else None,
            "requested_scopes": server.get("oauth_scopes", ""),
            "available_scopes": metadata.scopes_supported or [] if metadata else [],
            "registration": ("hosted_metadata" if metadata and metadata.client_id_metadata_document_supported else
                             "automatic" if metadata and metadata.registration_endpoint else "manual" if metadata else "unknown"),
            "stage": self.stages.get(key, "not_started"),
            "diagnostics": self.events.get(key, []),
            **self.previews.get(key, {}),
        }

    async def cancel(self, key):
        task = self.tasks.get(key)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.results[key] = "cancelled"
        self.errors.pop(key, None)
        self.record(key, "cancelled")
        return {"status": "cancelled"}

    @staticmethod
    def failure_message(exc: BaseException) -> str:
        # Provider errors can contain tokens and callback URLs. Expose only known
        # categories, including errors wrapped by transport task groups.
        if isinstance(exc, DesktopOAuthFailure):
            return str(exc)
        if isinstance(exc, BaseExceptionGroup):
            return DesktopOAuth.failure_message(exc.exceptions[0])
        if exc.__cause__ is not None:
            return DesktopOAuth.failure_message(exc.__cause__)
        if type(exc).__name__ == "MCPError":
            return "The MCP server rejected connection or tool discovery. Authorization may already be saved. Check the server’s access settings, then retry discovery."
        if type(exc).__name__ == "OAuthFlowError" and str(exc).startswith("Protected resource "):
            return "The provider advertises a different MCP endpoint. Use its canonical endpoint URL in Edit connection, then sign in again."
        messages = {
            "OAuthTokenError": "The provider rejected the token exchange. Try signing in again.",
            "OAuthRegistrationError": "This provider requires a registered OAuth client. Enter its client ID in Connection settings.",
            "OAuthFlowError": "The provider's OAuth response could not be validated. Try signing in again.",
            "TimeoutError": "Browser sign-in timed out. Return to Connection settings and try again.",
            "ConnectError": "Could not reach the provider. Check your connection and try again.",
            "ReadTimeout": "The provider took too long to respond. Try signing in again.",
            "ValidationError": "The provider returned an unsupported sign-in or tool response.",
        }
        return messages.get(type(exc).__name__, "Sign-in or tool discovery failed. Try again in Connection settings.")

    async def callback(self, request):
        nonce = request.path_params.get("nonce")
        state = request.query_params.get("state", "")
        if nonce is None:
            nonce = next((key for key, expected in self.expected_states.items() if secrets.compare_digest(state, expected)), "")
        future = self.callbacks.get(nonce)
        if future is None or future.done():
            return PlainTextResponse(
                "Sign-in has expired. Return to Umbod and retry.", status_code=400
            )
        code, state = (
            request.query_params.get("code"),
            request.query_params.get("state"),
        )
        if not state or not secrets.compare_digest(
            state, self.expected_states.get(nonce, "")
        ):
            return PlainTextResponse("Missing authorization response.", status_code=400)
        if request.query_params.get("error"):
            future.set_exception(ValueError("Browser authorization was declined"))
            return PlainTextResponse(
                "Sign-in was not approved. Return to Umbod to try again."
            )
        if not code:
            return PlainTextResponse("Missing authorization response.", status_code=400)
        self.record(nonce, "token_exchange")
        future.set_result(
            AuthorizationCodeResult(
                code=code, state=state, iss=request.query_params.get("iss")
            )
        )
        return PlainTextResponse(
            "Authorization received. Return to Umbod to check the result."
        )

    async def refresh(self, key):
        self.record(key, "refresh")
        try:
            result = await self._refresh(key)
        except Exception as exc:  # noqa: BLE001 - sanitize transport task groups too
            self.record(key, "refresh", failed=True)
            self.errors[key] = "Could not refresh authorization. Use Sign in with browser to reconnect. " + self.failure_message(exc)
            raise DesktopOAuthFailure(self.errors[key]) from None
        self.errors.pop(key, None)
        self.results[key] = "signed_in"
        self.record(key, "connected")
        return result

    async def _refresh(self, key):
        server = self.upstreams.state.data["servers"][key]
        storage = KeychainOAuthStorage(self.upstreams.vault, key, server["url"])
        await storage.load()
        if storage.document.tokens is None or not storage.document.tokens.refresh_token:
            raise ValueError("Sign in again to renew this credential")
        storage.document.expires_at = time.time() - 1
        await storage.save()
        async with Client(
            StreamableHttpTransport(server["url"], auth=DesktopConnectorOAuth(storage))
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
        self.errors.pop(key, None)

    async def logout(self, key):
        await self.forget(key)
        server = self.upstreams.state.data["servers"][key]
        server["oauth"] = False
        self.results[key] = "sign_in_required"
        self.upstreams.state.save()
        await self.upstreams.start(key, server)

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
