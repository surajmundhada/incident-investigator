"""One explicit native-function qualification request; never print a key or error body."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from investigator.agent.provider import GeminiProvider, ModelFailure  # noqa: E402


def local_values():
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name, value = stripped.split("=", 1)
            values[name.strip()] = value.strip().strip("\"'")
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-free-tier", action="store_true")
    parser.add_argument("--model", default="gemini-3.5-flash-lite")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.confirm_free_tier:
        parser.error(
            "Confirm this API key belongs to a Free-tier project before making the request"
        )
    key = local_values().get("GEMINI_API_KEY", "")
    if not key:
        print("GEMINI_API_KEY is not configured in the local .env")
        return 2
    provider = GeminiProvider(args.model, key, free_tier_confirmed=True)
    request = provider.request(
        {
            "incident": {
                "service": "checkout",
                "title": "Provider qualification",
                "description": "No incident observations are supplied.",
            },
            "permitted_services": ["checkout", "inventory", "payment"],
            "evidence": [],
            "qualification_task": "Select get_service_dependencies for checkout. Do not fabricate observations.",
        },
        2048,
    )
    try:
        reply = provider.invoke(request, 30)
        reply.decision.validated()
    except (ModelFailure, ValueError) as exc:
        result = {
            "status": "not_qualified",
            "model": args.model,
            "requests": 1,
            "reason": exc.code if isinstance(exc, ModelFailure) else "invalid_tool_arguments",
            "http_status": exc.status_code if isinstance(exc, ModelFailure) else None,
        }
        print(json.dumps(result))
        return 1
    result = {
        "status": "native_function_call_validated",
        "model": args.model,
        "served_model_version": reply.model_version,
        "requests": 1,
        "function": reply.decision.name,
        "usage": reply.usage,
        "limitations": "One protocol check, not a diagnosis-quality evaluation.",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
