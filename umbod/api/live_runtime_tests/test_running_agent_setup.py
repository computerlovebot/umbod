import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from conftest import RuntimeEndpoints


@pytest.mark.asyncio
async def test_running_mcp_serves_agent_setup_resource(runtime_endpoints: RuntimeEndpoints) -> None:
    uri = "umbod://setup/agent-instructions"
    transport = StreamableHttpTransport(
        runtime_endpoints.mcp_url,
        headers={"Authorization": f"Bearer {runtime_endpoints.bearer_token}"},
    )
    async with Client(transport, mode="legacy") as client:
        resources = await client.list_resources()
        assert uri in {str(resource.uri) for resource in resources}
        contents = await client.read_resource(uri)
        assert "<!-- umbod:begin -->" in contents[0].text
        assert "user-scoped AGENTS.md" in contents[0].text
        assert "search_tools" in contents[0].text
