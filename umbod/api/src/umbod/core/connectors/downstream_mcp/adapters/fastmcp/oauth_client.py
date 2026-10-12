"""FastMCP session adapter used by shared OAuth orchestration."""
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


def oauth_client(endpoint_url, auth):
    return Client(StreamableHttpTransport(endpoint_url, auth=auth))
