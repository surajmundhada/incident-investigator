"""Key-authenticated model metadata only; no generative requests or key output."""

import json

import httpx
from qualify_gemini import local_values

key = local_values().get("GEMINI_API_KEY", "")
if not key:
    print(json.dumps({"key_present": False}))
    raise SystemExit(2)
try:
    with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
        response = client.get(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash",
            headers={"x-goog-api-key": key},
        )
    print(
        json.dumps(
            {
                "key_present": True,
                "http_status": response.status_code,
                "model_metadata_available": response.is_success,
            }
        )
    )
except httpx.RequestError as exc:
    print(json.dumps({"key_present": True, "transport_error_type": type(exc).__name__}))
    raise SystemExit(1) from None
