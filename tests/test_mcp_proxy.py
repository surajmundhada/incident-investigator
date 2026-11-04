import json

import httpx
import pytest
from investigator.mcp_server import ReadOnlyProxy


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.invalid",
        "http://127.0.0.1:8001/path",
        "http://user:password@localhost",
        "http://localhost?other=x",
        "file:///tmp/source",
    ],
)
def test_mcp_proxy_rejects_remote_or_embedded_urls(url):
    with pytest.raises(ValueError):
        ReadOnlyProxy(url)


def test_mcp_calls_fixed_read_only_api_and_redacts_payload():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"message": "password=example-secret"})

    proxy = ReadOnlyProxy(transport=httpx.MockTransport(respond))
    try:
        result = proxy.investigation("a" * 32)
        assert "example-secret" not in json.dumps(result)
        assert result["trust"] == "untrusted_reference_data"
        proxy.applications()
        proxy.runbooks({"query": "payment errors", "service": "payment"})
        assert [(call.method, call.url.path) for call in calls] == [
            ("GET", "/api/investigations/" + "a" * 32),
            ("GET", "/api/applications"),
            ("POST", "/api/knowledge/search"),
        ]
        assert json.loads(calls[-1].content)["application"] == "shopping-demo"
        with pytest.raises(ValueError):
            proxy.investigation("../cancel")
        with pytest.raises(ValueError):
            proxy.runbooks({"query": "payment errors", "service": "payment", "url": "evil"})
        assert len(calls) == 3
    finally:
        proxy.close()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, text="secret database details"),
        httpx.Response(200, content=b"x" * 500001),
        httpx.Response(200, content=b"not json"),
    ],
)
def test_mcp_unavailable_oversized_invalid_responses_never_become_success(response):
    proxy = ReadOnlyProxy(transport=httpx.MockTransport(lambda _: response))
    try:
        result = proxy.applications()
        assert result["availability"] == "unavailable" and "secret" not in json.dumps(result)
    finally:
        proxy.close()


def test_sdk_discovery_and_tools_use_the_same_read_only_proxy():
    import asyncio

    pytest.importorskip("mcp")
    from investigator.mcp_server import make_server
    from mcp import Client

    proxy = ReadOnlyProxy(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"items": []}))
    )

    async def check():
        async with Client(make_server(proxy), raise_exceptions=True) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "get_saved_investigation",
                "list_application_configurations",
                "search_runbooks",
            }
            result = await client.call_tool("list_application_configurations", {})
            assert result.structured_content["availability"] == "available"
            rejected = await client.call_tool(
                "get_saved_investigation", {"investigation_id": "../bad"}
            )
            assert rejected.is_error

    try:
        asyncio.run(check())
    finally:
        proxy.close()
