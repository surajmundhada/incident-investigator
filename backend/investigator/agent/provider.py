"""Small Gemini REST adapter. No automatic tools, retries, tracing, or fallback."""

import json
import os
import re
import time
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from .contracts import ARGUMENTS, Decision
from .prompt import SYSTEM_PROMPT
from .security import application_context, redact


class ModelFailure(Exception):
    def __init__(self, code, usage=None, status_code=None):
        super().__init__(code)
        self.code, self.usage = code, usage
        self.status_code = status_code


@dataclass(frozen=True)
class Reply:
    decision: Decision
    usage: dict
    model_version: str | None = None


def expanded_schema(model):
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, dict):
            if "$ref" in value:
                return expand(definitions[value["$ref"].split("/")[-1]])
            return {
                key: expand(item) for key, item in value.items() if key not in {"title", "default"}
            }
        return value

    return expand(schema)


def build_request(context, output_tokens):
    trusted = application_context(context.get("incident"))
    context = redact(context)
    return {
        "systemInstruction": {
            "parts": [
                {"text": SYSTEM_PROMPT},
                {"text": "Application-owned reviewed context:\n" + json.dumps(trusted)},
            ]
        },
        "contents": [
            {"role": "user", "parts": [{"text": json.dumps(context, ensure_ascii=False)}]}
        ],
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": name,
                        "description": {
                            "search_logs": "Read bounded logs in the fixed incident window, optionally matching a request ID.",
                            "search_runbooks": "Retrieve applicable versioned operational guidance, not incident observations.",
                            "get_service_dependencies": "Read the reviewed dependency map for an allowed service.",
                            "finish_investigation": "Finish with a structured report, supported references, and limitations.",
                        }[name],
                        "parametersJsonSchema": expanded_schema(model),
                    }
                    for name, model in ARGUMENTS.items()
                ]
            }
        ],
        "toolConfig": {
            "functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": list(ARGUMENTS)}
        },
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": output_tokens,
            "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False},
        },
    }


def parse_usage(body):
    value = body.get("usageMetadata", {})
    mapping = {
        "input": "promptTokenCount",
        "output": "candidatesTokenCount",
        "thought": "thoughtsTokenCount",
        "total": "totalTokenCount",
    }
    result = {name: value.get(key, 0) for name, key in mapping.items()}
    if "totalTokenCount" not in value or any(
        type(count) is not int or count < 0 or count > 10_000_000 for count in result.values()
    ):
        raise ModelFailure("missing_or_invalid_usage")
    return result


class GeminiProvider:
    origin = "gemini"

    def __init__(self, model, api_key, *, free_tier_confirmed=False, transport=None):
        if not re.fullmatch(r"gemini-[a-zA-Z0-9.-]{1,80}", model):
            raise ValueError("A specific Gemini model ID is required")
        if not api_key or not free_tier_confirmed:
            raise ValueError("Configure a key and explicitly confirm the project's free tier")
        self.identity = "gemini:" + model
        self.model, self._api_key, self.transport = model, api_key, transport

    def request(self, context, output_tokens):
        return build_request(redact(context, secrets=(self._api_key,)), output_tokens)

    def invoke(self, request, remaining_seconds):
        deadline = time.monotonic() + remaining_seconds
        try:
            with httpx.Client(
                timeout=min(30.0, remaining_seconds),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                with client.stream(
                    "POST",
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                    headers={"x-goog-api-key": self._api_key},
                    json=request,
                ) as response:
                    if response.status_code == 429:
                        raise ModelFailure("provider_rate_limited", status_code=429)
                    if not response.is_success:
                        raise ModelFailure(
                            "provider_request_failed", status_code=response.status_code
                        )
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 256_000 or time.monotonic() >= deadline:
                            raise ModelFailure("provider_response_limit")
            body = json.loads(data)
        except httpx.TimeoutException:
            raise ModelFailure("provider_timeout") from None
        except httpx.RequestError:
            raise ModelFailure("provider_transport_error") from None
        except ValueError:
            raise ModelFailure("invalid_provider_response") from None
        if not isinstance(body, dict):
            raise ModelFailure("invalid_provider_response")
        usage = parse_usage(body)
        try:
            candidates = body.get("candidates", [])
            if len(candidates) != 1 or candidates[0].get("finishReason") != "STOP":
                raise ValueError("A complete single candidate is required")
            parts = candidates[0]["content"]["parts"]
            calls = [part["functionCall"] for part in parts if "functionCall" in part]
            if len(calls) != 1:
                raise ValueError("Exactly one function call is required")
            decision = Decision.model_validate(
                {"name": calls[0]["name"], "arguments": calls[0]["args"]}
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            raise ModelFailure("invalid_model_action", usage) from None
        served = body.get("modelVersion")
        if not isinstance(served, str) or not re.fullmatch(r"gemini-[a-zA-Z0-9._-]{1,100}", served):
            served = None
        return Reply(decision, usage, served)


def configured_provider():
    mode = os.environ.get("AGENT_MODE", "disabled")
    if mode == "disabled":
        return None
    if mode != "gemini":
        raise ValueError("AGENT_MODE must be disabled or gemini; no implicit fallback")
    return GeminiProvider(
        model=os.environ.get("GEMINI_MODEL", ""),
        api_key=os.environ.get("GEMINI_API_KEY", ""),
        free_tier_confirmed=os.environ.get("GEMINI_FREE_TIER_CONFIRMED") == "1",
    )
