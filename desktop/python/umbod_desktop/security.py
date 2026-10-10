"""Single-user authentication and OS-vault credentials; no development fallback."""

import hashlib
import secrets
from typing import Protocol

from fastmcp.server.auth import AccessToken, TokenVerifier
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from umbod.rest.authentication.authorization import JwtClaims, JwtVerificationError

DESKTOP_GROUP = "desktop-owner"


class CredentialVault(Protocol):
    def get(self, reference: str) -> str | None: ...
    def set(self, reference: str, value: str) -> None: ...
    def delete(self, reference: str) -> None: ...


class KeychainVault:
    def __init__(self, profile: str, namespace: str = "") -> None:
        from keyring.backends.macOS import Keyring

        self.backend = Keyring()
        self.service = (
            "app.umbod.desktop" + (".dev" if profile == "dev" else "") + namespace
        )

    def get(self, reference: str) -> str | None:
        return self.backend.get_password(self.service, reference)

    def set(self, reference: str, value: str) -> None:
        self.backend.set_password(self.service, reference, value)

    def delete(self, reference: str) -> None:
        if self.get(reference) is not None:
            self.backend.delete_password(self.service, reference)


def persistent_secret(vault: CredentialVault, reference: str) -> str:
    value = vault.get(reference)
    if value is None:
        value = secrets.token_urlsafe(48)
        vault.set(reference, value)
    if len(value) < 32:
        raise ValueError("Stored desktop credential is invalid")
    return value


class DesktopAdminVerifier:
    def __init__(self, token: str) -> None:
        self.token = token

    def verify(self, token: str) -> JwtClaims:
        if not secrets.compare_digest(token.encode(), self.token.encode()):
            raise JwtVerificationError("Invalid desktop credential")
        return JwtClaims(
            claims={"sub": "desktop-owner", "name": "You", "groups": [DESKTOP_GROUP]}
        )


class DesktopAgentVerifier(TokenVerifier):
    def __init__(self, token: str, legacy_hashes: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.token = token
        self.legacy_hashes = legacy_hashes

    async def verify_token(self, token: str) -> AccessToken | None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        if not secrets.compare_digest(token.encode(), self.token.encode()) and not any(
            secrets.compare_digest(digest, saved) for saved in self.legacy_hashes
        ):
            return None
        return AccessToken(
            token=token,
            client_id="desktop-agent",
            scopes=[],
            subject="desktop-owner",
            claims={"sub": "desktop-owner", "groups": [DESKTOP_GROUP]},
        )


class LoopbackAuthentication:
    """Protect every host route, including health and internal system routes."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app, self.token = app, token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"authorization", b"")
        # Browser origins/cookies have no place in this native-only host contract.
        if (
            b"origin" in headers
            or b"cookie" in headers
            or not secrets.compare_digest(supplied, f"Bearer {self.token}".encode())
        ):
            await JSONResponse({"detail": "Unauthorized"}, status_code=401)(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)
