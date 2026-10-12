"""Shared public-client OAuth policy layered on the SDK adapter."""

import time
from umbod.core.connectors.downstream_mcp.adapters.fastmcp.oauth import ConnectorOAuth

CLIENT_METADATA_URL = "https://umbod.ai/oauth/client-metadata.json"


class OAuthFailure(ValueError):
    """Only fixed, secret-free messages may be constructed at this boundary."""


class InteractiveConnectorOAuth(ConnectorOAuth):
    def __init__(self, *args, **kwargs):
        self.requested_scope = kwargs.pop("requested_scope", "")
        self.force_authorization = kwargs.pop("force_authorization", False)
        self.force_refresh = kwargs.pop("force_refresh", False)
        metadata_url = kwargs.pop("metadata_url", None)
        super().__init__(*args, **kwargs)
        self.token_received = False
        self.context.client_metadata_url = metadata_url
        self.context.client_metadata.token_endpoint_auth_method = "none"

    async def _initialize(self):
        await super()._initialize()
        if (
            self.context.client_info
            and self.context.client_info.client_id == CLIENT_METADATA_URL
        ):
            self.context.client_metadata_url = CLIENT_METADATA_URL
        if self.force_refresh:
            self.context.token_expiry_time = time.time() - 1
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
        await self._process_token_response(response, False)

    async def _process_token_response(self, response, refresh):
        if response.status_code not in {200, 201}:
            await response.aread()
            try:
                code = response.json().get("error")
            except ValueError, AttributeError:
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
                "invalid_grant": "The refresh token expired or was revoked."
                if refresh
                else "The authorization code expired or did not match this sign-in.",
                "invalid_scope": "The provider rejected the requested permissions.",
                "invalid_request": "The provider rejected the token request.",
                "unauthorized_client": "This client is not authorized for this provider.",
            }
            raise OAuthFailure(
                reasons.get(code, "The provider rejected the token exchange.")
                + f" (HTTP {response.status_code}). Try signing in again."
            )
        await super()._handle_token_response(response)
        self.token_received = True
        self.force_authorization = False
        self.storage.document.metadata = self.context.oauth_metadata
        self.storage.document.authorization_server = self.context.auth_server_url
        await self.storage.save()

    async def _handle_refresh_response(self, response):
        if response.status_code != 200:
            await self._process_token_response(response, True)
        refreshed = await super()._handle_refresh_response(response)
        if refreshed:
            self.force_refresh = False
        return refreshed


class RuntimeOAuth(InteractiveConnectorOAuth):
    """Background use reports reauthentication without launching a browser."""

    def __init__(self, storage, sign_in_required):
        super().__init__(storage)
        self.sign_in_required = sign_in_required

    async def _perform_authorization(self):
        from umbod.core.connectors.downstream_mcp.adapters.fastmcp.oauth import (
            SignInRequired,
        )

        self.sign_in_required()
        raise SignInRequired()


def response_authentication_status(status_code: int, authorized: bool) -> str | None:
    if status_code == 401:
        return "sign_in_required"
    if status_code == 200:
        return "signed_in" if authorized else "signed_out"
    return None
