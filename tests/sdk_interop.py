"""Optional interoperability check using the official MCP SDK 2.3.0.

Runtime dependencies stay stdlib-only. This script is an integration test,
separate from unittest discovery, and touches no real editor or remote service.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import threading

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
import httpx2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ue_mcp import VERSION
from ue_mcp.packages import Manager
from ue_mcp.server import HTTPServer


async def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as folder:
        params = StdioServerParameters(command=sys.executable,
            args=[str(root / "scripts/mcp_server.py"), "--state-dir", folder])
        async with Client(params, read_timeout_seconds=15) as client:
            tools = await client.list_tools()
            assert any(tool.name == "ue_finish_task" for tool in tools.tools)
            result = await client.call_tool("ue_status", {})
            assert json.loads(result.content[0].text)["version"] == VERSION
            guidance = await client.call_tool("ue_knowledge_read", {"path": "SKILL.md"})
            assert "Unreal MCP" in json.loads(guidance.content[0].text)["text"]
        token = "interop-test-token-" + "x" * 40
        server = HTTPServer(("127.0.0.1", 0), token, folder)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}) as http:
                async with streamable_http_client("http://127.0.0.1:" + str(server.server_port) + "/mcp", http_client=http) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        assert any(tool.name == "ue_call" for tool in tools.tools)
                        result = await session.call_tool("ue_experience_status", {})
                        assert json.loads(result.content[0].text)["config"]["mode"] == "local"
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
    print("Official MCP SDK 2.3.0 interop passed: stdio auto negotiation, HTTP, discovery and knowledge.")


if __name__ == "__main__":
    asyncio.run(main())
