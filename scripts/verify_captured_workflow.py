"""Exercise a second application's captured evidence through the real API, quota-free.

Run inside the worker container started WITHOUT the agent override. This verifies
onboarding/persistence, not diagnosis accuracy or actual-model behavior.
"""

import argparse
import json
import os
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://api:8000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if os.environ.get("AGENT_MODE", "disabled") != "disabled":
        raise SystemExit(
            "Run this smoke inside an evidence-only worker (no -Agent startup override)"
        )
    root = Path(__file__).resolve().parents[1] / "examples" / "booking-capture"
    configuration = json.loads((root / "application.json").read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in (root / "logs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    coverage = json.loads((root / "coverage.json").read_text(encoding="utf-8"))
    with httpx.Client(base_url=args.base_url, timeout=15, trust_env=False) as client:

        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        request("GET", "/readyz")
        registered = request("POST", "/api/applications", json=configuration)
        upload = {
            "application": configuration["application"],
            "environment": configuration["environment"],
            "release": configuration["release"],
            "configuration_revision": registered["revision"],
            "source_name": "logs.jsonl",
            "records": records,
            **coverage,
        }
        snapshot = request("POST", "/api/snapshots", json=upload)
        duplicate = request("POST", "/api/snapshots", json=upload)
        assert duplicate["id"] == snapshot["id"] and duplicate["reused"]
        # This comparison intentionally uses a different application's listing.
        assert snapshot["id"] not in {
            item["id"]
            for item in request("GET", "/api/snapshots?application=shopping-demo")["items"]
        }
        incident = {
            "application": configuration["application"],
            "environment": configuration["environment"],
            "release": configuration["release"],
            "configuration_revision": registered["revision"],
            "snapshot_id": snapshot["id"],
            "service": "booking-api",
            "title": "Synthetic captured booking failure",
            "description": "Collect supplied booking evidence and report its limits. These are synthetic example logs.",
            "starts_at": coverage["starts_at"],
            "ends_at": coverage["ends_at"],
        }
        headers = {"Idempotency-Key": "captured-smoke-v1:" + snapshot["id"]}
        admitted = request("POST", "/api/incidents", json=incident, headers=headers)
        replay = request("POST", "/api/incidents", json=incident, headers=headers)
        assert replay["replayed"] and replay["investigation_id"] == admitted["investigation_id"]
        path = "/api/investigations/" + admitted["investigation_id"]
        deadline = time.monotonic() + 40
        while True:
            saved = request("GET", path)
            if saved["status"] in {"complete", "failed", "cancelled"}:
                break
            if time.monotonic() > deadline:
                raise AssertionError("Captured job did not complete within 40 seconds")
            time.sleep(0.25)
        assert saved["status"] == "complete"
        report = saved["report"]
        assert report["usage"]["model_calls"] == 0
        assert report["application"] == configuration["application"]
        assert report["configuration_revision"] == registered["revision"]
        logs = next(row for row in saved["evidence"] if row["source"] == "snapshot_log_adapter")
        assert logs["availability"] == "available" and len(logs["records"]) == 3
        assert logs["synthetic_example"] and logs["snapshot_id"] == snapshot["id"]
        assert "example-token-not-real" not in json.dumps(saved)
        assert "[REDACTED]" in json.dumps(logs)
        assert any("synthetic" in value for value in report["limitations"])
        assert report["knowledge_availability"] == "unavailable"
        result = {
            "application": configuration["application"],
            "configuration_revision": registered["revision"],
            "snapshot_id": snapshot["id"],
            "investigation_id": saved["id"],
            "status": saved["status"],
            "snapshot_replay": duplicate["reused"],
            "incident_replay": replay["replayed"],
            "collected_log_records": len(logs["records"]),
            "model_calls": 0,
            "data_origin": "captured",
            "synthetic_example": True,
            "known_credential_redacted": True,
            "knowledge_available": False,
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))


if __name__ == "__main__":
    main()
