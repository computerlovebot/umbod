import gzip

import httpx2
import pytest

from umbod_desktop.oauth_discovery import discover, public_https


async def test_discovery_follows_standard_metadata_without_credentials():
    seen = []

    def handle(request):
        assert "authorization" not in request.headers
        seen.append(str(request.url))
        if str(request.url) == "https://tools.example/mcp":
            return httpx2.Response(401, headers={"WWW-Authenticate": 'Bearer resource_metadata="https://tools.example/metadata"', "Content-Encoding": "gzip"}, content=gzip.compress(b"unauthorized"))
        if str(request.url) == "https://tools.example/metadata":
            return httpx2.Response(200, json={
                "resource": "https://canonical.example/mcp",
                "authorization_servers": ["https://auth.example"],
                "scopes_supported": ["read", "write"],
            })
        return httpx2.Response(200, json={
            "issuer": "https://auth.example", "authorization_endpoint": "https://auth.example/authorize",
            "token_endpoint": "https://auth.example/token", "response_types_supported": ["code"],
            "client_id_metadata_document_supported": True,
        })

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handle)) as client:
        result = await discover("https://tools.example/mcp", client)
    assert result["endpoint_differs"]
    assert result["available_scopes"] == ["read", "write"]
    assert result["registration"] == "hosted_metadata"
    assert all("canonical.example" not in url for url in seen)


@pytest.mark.parametrize("url", ["http://example.com/mcp", "https://user:secret@example.com/mcp", "https://example.com/mcp?token=secret"])
def test_discovery_rejects_credential_bearing_or_insecure_urls(url):
    with pytest.raises(ValueError):
        public_https(url)


async def test_discovery_rejects_wrong_issuer():
    def handle(request):
        if "oauth-authorization-server" in str(request.url):
            return httpx2.Response(200, json={
                "issuer": "https://wrong.example", "authorization_endpoint": "https://wrong.example/authorize",
                "token_endpoint": "https://wrong.example/token", "response_types_supported": ["code"],
            })
        return httpx2.Response(404)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handle)) as client:
        with pytest.raises(Exception, match="issuer"):
            await discover("https://tools.example/mcp", client)


async def test_resource_origin_can_cover_endpoint_path():
    def handle(request):
        if "oauth-protected-resource" in str(request.url):
            return httpx2.Response(200, json={"resource": "https://tools.example", "authorization_servers": ["https://tools.example"]})
        return httpx2.Response(404)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handle)) as client:
        result = await discover("https://tools.example/mcp", client)
    assert not result["endpoint_differs"]
