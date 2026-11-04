from datetime import datetime, timezone

import httpx
import pytest
from investigator.tools import LogTool


def scope():
    return {"service": "payment", "starts_at": 0, "ends_at": 200}


def row(service="payment", timestamp=100):
    return {
        "service": service,
        "timestamp": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
        "level": "ERROR",
        "message": "Read-only source observation",
    }


def test_filters_wrong_services_and_out_of_window_records():
    def handler(request):
        assert request.url.path == "/evidence/logs"
        assert request.method == "GET"
        return httpx.Response(
            200, json={"records": [row(), row("checkout"), row(timestamp=300)], "truncated": True}
        )

    result = LogTool("http://fixed-source", transport=httpx.MockTransport(handler)).collect(scope())
    assert result["availability"] == "available"
    assert len(result["records"]) == 1
    assert result["truncated"] is True


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(200, text="invalid JSON"),
        httpx.Response(200, json={"records": [{"unexpected": "schema"}]}),
        httpx.Response(200, content=b"x" * 256_001),
        httpx.Response(302, headers={"Location": "http://another-host"}),
    ],
)
def test_bad_sources_are_explicitly_unavailable(response):
    result = LogTool(
        "http://fixed-source", transport=httpx.MockTransport(lambda _: response)
    ).collect(scope())
    assert result["availability"] == "unavailable"
    assert result["records"] == []
    assert "error" in result


def test_timeout_is_explicit():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    result = LogTool("http://fixed-source", transport=httpx.MockTransport(timeout)).collect(scope())
    assert result["error"] == "source_timeout"


def test_available_empty_source_is_different_from_failure():
    result = LogTool(
        "http://fixed-source",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"records": []})),
    ).collect(scope())
    assert result["availability"] == "available"
    assert result["records"] == []
