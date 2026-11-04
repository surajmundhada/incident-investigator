"""Read-only MCP stdio smoke against the running API; no model or cloud calls."""

import asyncio
import json
import sys
from pathlib import Path


async def main():
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    root = Path(__file__).resolve().parents[1]
    workspace = json.loads((root / "work/workspace-verification.json").read_text())
    server = StdioServerParameters(
        command=sys.executable,
        args=["-u", "-m", "investigator.mcp_server"],
        env={"PYTHONPATH": str(root / "backend"), "MCP_API_BASE_URL": "http://127.0.0.1:8001"},
    )
    async with Client(server, read_timeout_seconds=15) as client:
        tools = await client.list_tools()
        names = sorted(tool.name for tool in tools.tools)
        assert len(names) == 3 and all(tool.annotations.read_only_hint for tool in tools.tools)
        applications = await client.call_tool("list_application_configurations", {})
        assert applications.structured_content["availability"] == "available"
        saved = await client.call_tool(
            "get_saved_investigation", {"investigation_id": workspace["investigation_id"]}
        )
        assert saved.structured_content["data"]["id"] == workspace["investigation_id"]
        runbooks = await client.call_tool(
            "search_runbooks",
            {
                "request": {
                    "application": "shopping-demo",
                    "query": "payment unavailable",
                    "service": "checkout",
                }
            },
        )
        result = runbooks.structured_content
        assert result["availability"] == "available" and result["data"]["hits"]
        print(
            json.dumps(
                {
                    "kind": "connected-mcp-stdio-v1",
                    "tools": names,
                    "saved_investigation_read": True,
                    "application_configurations_read": True,
                    "retrieval_hits": len(result["data"]["hits"]),
                    "model_calls": 0,
                    "external_host_configured": False,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
