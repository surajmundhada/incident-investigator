"""Real SDK subprocess/stdio handshake against a deliberately tiny local HTTP fixture."""

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


def test_mcp_stdio_handshake_and_read_only_tool_roundtrip():
    pytest.importorskip("mcp")
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(("GET", self.path))
            body = json.dumps({"items": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = Path(__file__).resolve().parents[1]
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-u", "-m", "investigator.mcp_server"],
        env={
            "PYTHONPATH": str(root / "backend"),
            "MCP_API_BASE_URL": f"http://127.0.0.1:{server.server_port}",
        },
    )

    async def check():
        async with Client(parameters, read_timeout_seconds=15) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 3
            assert all(tool.annotations.read_only_hint for tool in tools.tools)
            result = await client.call_tool("list_application_configurations", {})
            assert not result.is_error
            assert result.structured_content["data"] == {"items": []}
            rejected = await client.call_tool(
                "search_runbooks",
                {
                    "request": {
                        "query": "payment errors",
                        "service": "payment",
                        "url": "https://evil.invalid",
                    }
                },
            )
            assert rejected.is_error

    try:
        asyncio.run(check())
        assert requests == [("GET", "/api/applications")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
