"""Call the UI-enabled echo tool through the packaged agent bridge."""

import asyncio
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def main():
    async with Client(
        StdioTransport(
            command=sys.argv[1],
            args=[
                "bridge",
                "--profile",
                sys.argv[3],
                "--data-dir",
                sys.argv[2],
                "--test-credentials",
            ],
            env={"TMPDIR": str(Path(sys.argv[2]).parent)},
        ),
        mode="legacy",
    ) as client:
        async with asyncio.timeout(30):
            while not (tools := await client.list_tools()):
                await asyncio.sleep(0.1)
            assert len(tools) == 1, "Only the UI-enabled tool should be published"
            result = await client.call_tool(
                tools[0].name, {"text": "ui-journey-fixture"}
            )
            assert "ui-journey-fixture" in str(result)


asyncio.run(asyncio.wait_for(main(), timeout=45))
