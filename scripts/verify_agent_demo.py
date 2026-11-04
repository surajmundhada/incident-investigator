"""One actual-model investigation of a real demo failure. Operator-side only."""

import argparse
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx


def verify(api, checkout, control, output):
    with httpx.Client(timeout=10, trust_env=False) as client:

        def mode(value):
            response = client.post(
                control + "/faults/payment", json={"mode": value, "ttl_seconds": 60}
            )
            response.raise_for_status()

        try:
            mode("healthy")
            response = client.post(checkout + "/checkout", json={})
            if response.status_code != 200:
                raise AssertionError("Healthy checkout failed")
            start = datetime.now(timezone.utc) - timedelta(milliseconds=10)
            mode("unavailable")
            response = client.post(checkout + "/checkout", json={})
            if response.status_code != 502:
                raise AssertionError("Expected a downstream checkout error")
            end = datetime.now(timezone.utc)
        finally:
            mode("healthy")
        response = client.post(
            api + "/api/incidents",
            headers={"Idempotency-Key": uuid.uuid4().hex},
            json={
                "title": "Checkout returns HTTP 502",
                "description": "Investigate failing checkout requests in this window. Identify the affected dependency and what cannot be established.",
                "service": "checkout",
                "starts_at": start.isoformat(),
                "ends_at": end.isoformat(),
            },
        )
        response.raise_for_status()
        iid = response.json()["investigation_id"]
        deadline = time.monotonic() + 160
        while time.monotonic() < deadline:
            response = client.get(api + f"/api/investigations/{iid}")
            response.raise_for_status()
            result = response.json()
            if result["status"] in {"complete", "failed", "cancelled"}:
                break
            time.sleep(0.5)
        else:
            raise AssertionError("Investigation did not finish within the demo deadline")
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        report = result.get("report") or {}
        print(
            json.dumps(
                {
                    "investigation_url": api + f"/api/investigations/{iid}",
                    "status": result["status"],
                    "mode": report.get("mode"),
                    "model": report.get("model"),
                    "provider_origin": report.get("provider_origin"),
                    "termination_reason": report.get("termination_reason"),
                    "usage": report.get("usage"),
                    "evidence_services": sorted(
                        {row["service"] for row in result["evidence"] if "service" in row}
                    ),
                },
                indent=2,
            )
        )
        if (
            report.get("provider_origin") != "gemini"
            or report.get("termination_reason") != "report_completed"
        ):
            raise AssertionError(
                "A complete actual-model report was not produced; inspect the saved partial result"
            )
        if not any(
            row.get("service") == "payment" and row.get("source") == "http_log_adapter"
            for row in result["evidence"]
        ):
            raise AssertionError("The model did not gather payment-side observations")
        print(
            "PASS: actual model followed the failing dependency and completed a structurally validated report."
        )
        print("This is one smoke test, not a diagnosis-accuracy benchmark.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8001")
    parser.add_argument("--checkout", default="http://127.0.0.1:8002")
    parser.add_argument("--control", default="http://127.0.0.1:8003")
    parser.add_argument("--output", type=Path, default=Path("work/agent-live-demo.json"))
    args = parser.parse_args()
    verify(args.api.rstrip("/"), args.checkout.rstrip("/"), args.control.rstrip("/"), args.output)
