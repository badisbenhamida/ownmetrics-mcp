"""End-to-end over the real MCP stdio protocol, as an AI app would run the server.

No key is configured (HOME points at an empty folder), so nothing reaches Garmin: the
server must still start cleanly, list all tools, and explain the missing key.
"""

import json
import os
import shutil
import sys

import anyio
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

req = pytest.mark.req


async def _session_check(home: str) -> tuple[list, str]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ownmetrics_mcp"],
        env={
            "HOME": home,
            "USERPROFILE": home,
            "PATH": "",
            "PYTHONPATH": os.pathsep.join(sys.path),
        },
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = (await session.list_tools()).tools
        result = await session.call_tool("get_account_status", {})
        text = "".join(getattr(c, "text", "") for c in result.content)
        return tools, text


@req("T9", "AC6", "R6")
@pytest.mark.skipif(shutil.which("true") is None, reason="needs a POSIX-like environment")
def test_server_starts_over_stdio_and_explains_missing_key(tmp_path):
    tools, text = anyio.run(_session_check, str(tmp_path))
    assert len(tools) == 14
    status = json.loads(text)
    assert status["connected"] is False
    assert "ownmetrics-mcp auth" in status["problem"]
