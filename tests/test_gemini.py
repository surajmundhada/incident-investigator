import json

import httpx
import pytest
from investigator.agent.provider import GeminiProvider, ModelFailure, build_request


def response_body():
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {
                            "functionCall": {
                                "name": "get_service_dependencies",
                                "args": {"service": "checkout"},
                            },
                            "thoughtSignature": "opaque-not-persisted",
                        }
                    ]
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 15,
            "thoughtsTokenCount": 5,
            "totalTokenCount": 120,
        },
    }


def test_native_wire_format_key_is_header_only_and_no_automatic_tools():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=response_body())

    provider = GeminiProvider(
        "gemini-3.8-flash",
        "test-key",
        free_tier_confirmed=True,
        transport=httpx.MockTransport(handle),
    )
    request = provider.request({"incident": "untrusted text"}, 512)
    reply = provider.invoke(request, 10)
    assert reply.decision.name == "get_service_dependencies"
    assert reply.usage["total"] == 120
    assert "test-key" not in json.dumps(request)
    assert seen[0].headers["x-goog-api-key"] == "test-key"
    assert seen[0].url.host == "generativelanguage.googleapis.com"
    assert "key=" not in str(seen[0].url)
    assert "thoughtSignature" not in reply.decision.model_dump()
    declarations = request["tools"][0]["functionDeclarations"]
    assert len(declarations) == 4
    assert "$ref" not in json.dumps(declarations)


@pytest.mark.parametrize(
    "status,expected",
    [
        (429, "provider_rate_limited"),
        (403, "provider_request_failed"),
        (503, "provider_request_failed"),
    ],
)
def test_provider_errors_are_sanitized_and_not_retried(status, expected):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, text="sensitive response with test-key")

    provider = GeminiProvider(
        "gemini-3.8-flash",
        "test-key",
        free_tier_confirmed=True,
        transport=httpx.MockTransport(handle),
    )
    with pytest.raises(ModelFailure) as error:
        provider.invoke(build_request({}, 512), 10)
    assert str(error.value) == expected
    assert len(calls) == 1
    assert "test-key" not in str(error.value)


@pytest.mark.parametrize(
    "kind", ["unknown_tool", "multiple_calls", "incomplete", "missing_usage", "oversized"]
)
def test_malformed_model_results_do_not_execute(kind):
    body = response_body()
    if kind == "unknown_tool":
        body["candidates"][0]["content"]["parts"][0]["functionCall"]["name"] = "execute_shell"
    elif kind == "multiple_calls":
        body["candidates"][0]["content"]["parts"] *= 2
    elif kind == "incomplete":
        body["candidates"][0]["finishReason"] = "MAX_TOKENS"
    elif kind == "missing_usage":
        body.pop("usageMetadata")
    elif kind == "oversized":
        body["extra"] = "x" * 260_000
    provider = GeminiProvider(
        "gemini-3.8-flash",
        "test-key",
        free_tier_confirmed=True,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
    )
    with pytest.raises(ModelFailure):
        provider.invoke(build_request({}, 512), 10)


def test_explicit_free_tier_confirmation_and_model_are_required():
    with pytest.raises(ValueError):
        GeminiProvider("gemini-3.8-flash", "test-key")
    with pytest.raises(ValueError):
        GeminiProvider("https://example.com", "test-key", free_tier_confirmed=True)
