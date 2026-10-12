"""Public MCP authentication discovery without credentials or registration."""

from urllib.parse import urlsplit

import httpx2
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    extract_resource_metadata_from_www_auth,
    handle_auth_metadata_response,
    handle_protected_resource_response,
    validate_metadata_issuer,
)
from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url
from pydantic import TypeAdapter
from umbod.core.connectors.downstream_mcp.models import EndpointUrl


def public_https(value):
    url = str(TypeAdapter(EndpointUrl).validate_python(value))
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.query or parsed.fragment:
        raise ValueError("Metadata URLs must use HTTPS without query or fragment")
    return url


async def discover(url, client=None):
    if client is None:
        async with httpx2.AsyncClient(timeout=8, follow_redirects=False) as owned:
            return await discover(url, owned)

    async def get(address):
        address = public_https(address)
        async with client.stream("GET", address) as response:
            chunks = bytearray()
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > 1024 * 1024:
                    raise ValueError("Metadata response too large")
            return httpx2.Response(response.status_code, headers={key: value for key, value in response.headers.items() if key.lower() not in {"content-encoding", "content-length"}}, content=bytes(chunks))

    public_https(url)
    response = await get(url)
    hint = extract_resource_metadata_from_www_auth(response)
    resource = None
    for address in build_protected_resource_metadata_discovery_urls(hint, url):
        resource = await handle_protected_resource_response(await get(address))
        if resource:
            break
    suggested = public_https(str(resource.resource)) if resource and resource.resource else url
    issuer = str(resource.authorization_servers[0]) if resource and resource.authorization_servers else None
    metadata = None
    for address in build_oauth_authorization_server_metadata_discovery_urls(issuer, url):
        ok, metadata = await handle_auth_metadata_response(await get(address))
        if metadata:
            parsed = urlsplit(url)
            validate_metadata_issuer(metadata, issuer or f"{parsed.scheme}://{parsed.netloc}")
            break
        if not ok:
            break
    return {
        "canonical_endpoint": suggested,
        "endpoint_differs": not check_resource_allowed(requested_resource=resource_url_from_server_url(url), configured_resource=suggested),
        "issuer": str(metadata.issuer) if metadata else "",
        "available_scopes": (resource.scopes_supported if resource else None) or (metadata.scopes_supported if metadata else None) or [],
        "registration": ("hosted_metadata" if metadata and metadata.client_id_metadata_document_supported else
                         "automatic" if metadata and metadata.registration_endpoint else "manual" if metadata else "unknown"),
    }
