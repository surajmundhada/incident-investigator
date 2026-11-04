"""Exercise real HTTP services, temporary failure, persistence, and recovery.

Operator-side only. Prints no fault settings into agent-visible evidence.
"""

import argparse
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx


def verify(api, checkout, control, require_knowledge=False):
    with httpx.Client(timeout=10, trust_env=False) as client:

        def set_mode(mode):
            response = client.post(
                control + "/faults/payment", json={"mode": mode, "ttl_seconds": 60}
            )
            response.raise_for_status()

        def submit(service, start, end):
            response = client.post(
                api + "/api/incidents",
                headers={"Idempotency-Key": uuid.uuid4().hex},
                json={
                    "title": "Requests failing during checkout",
                    "description": "Inspect errors in the supplied request window.",
                    "service": service,
                    "starts_at": start.isoformat(),
                    "ends_at": end.isoformat(),
                },
            )
            response.raise_for_status()
            iid = response.json()["investigation_id"]
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                response = client.get(api + f"/api/investigations/{iid}")
                response.raise_for_status()
                result = response.json()
                if result["status"] == "complete":
                    return iid, result
                if result["status"] == "failed":
                    raise AssertionError("Investigation failed")
                time.sleep(0.2)
            raise AssertionError("Investigation did not complete within 20 seconds")

        def check(condition, message):
            if not condition:
                raise AssertionError(message)

        try:
            set_mode("healthy")
            response = client.post(checkout + "/checkout", json={"item": "book", "quantity": 1})
            check(response.status_code == 200, "Healthy checkout failed")
            start = datetime.now(timezone.utc) - timedelta(milliseconds=10)
            set_mode("unavailable")
            response = client.post(checkout + "/checkout", json={"item": "book", "quantity": 1})
            check(response.status_code == 502, "Failure did not propagate to checkout")
            request_id = response.json()["request_id"]
            end = datetime.now(timezone.utc)
            ids = []
            for service, expected_status in (("checkout", 502), ("payment", 503)):
                iid, result = submit(service, start, end)
                ids.append(iid)
                evidence = next(
                    row for row in result["evidence"] if row["tool_call_id"] == "logs.v1"
                )
                check(evidence["availability"] == "available", "Live source unavailable")
                check(evidence["data_origin"] == "live", "Unexpected fixture evidence")
                check(
                    any(
                        row.get("request_id") == request_id
                        and row.get("status_code") == expected_status
                        for row in evidence["records"]
                    ),
                    f"Missing correlated {service} failure",
                )
                check(result["report"]["usage"]["model_calls"] == 0, "Unexpected model usage")
                check(not result["report"]["hypotheses"], "Unexpected diagnosis")
                if require_knowledge:
                    report = result["report"]
                    check(
                        report.get("knowledge_availability") == "available", "Knowledge unavailable"
                    )
                    check(bool(report.get("retrieved_guidance")), "No guidance retrieved")
                    check(bool(report.get("knowledge_revision")), "Missing knowledge revision")
                    owned = {row["id"] for row in result["evidence"]}
                    check(
                        all(hit["evidence_id"] in owned for hit in report["retrieved_guidance"]),
                        "Unowned guidance reference",
                    )
            print(
                "PASS: healthy checkout, real downstream failure, correlated live evidence, persisted reports."
            )
            for iid in ids:
                print(api + f"/api/investigations/{iid}")
        finally:
            set_mode("healthy")
        response = client.post(checkout + "/checkout", json={"item": "book", "quantity": 1})
        check(response.status_code == 200, "Checkout did not recover")
        print("PASS: payment reset and healthy checkout recovery. No model or cloud calls.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8001")
    parser.add_argument("--checkout", default="http://127.0.0.1:8002")
    parser.add_argument("--control", default="http://127.0.0.1:8003")
    parser.add_argument("--require-knowledge", action="store_true")
    args = parser.parse_args()
    verify(
        args.api.rstrip("/"),
        args.checkout.rstrip("/"),
        args.control.rstrip("/"),
        args.require_knowledge,
    )
