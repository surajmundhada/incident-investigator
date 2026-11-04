"""Connected synthetic onboarding -> runbooks -> evidence-only report -> archive check.

Run inside a worker explicitly started with AGENT_MODE=disabled. No cloud calls.
"""

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import httpx


def main():
    if os.environ.get("AGENT_MODE", "disabled") != "disabled":
        raise RuntimeError("Start the actual worker in evidence-only mode before this check")
    root = Path("examples/booking-capture")
    configuration = json.loads((root / "application.json").read_text())
    configuration["application"] = "verification-" + uuid.uuid4().hex[:10]
    records = [
        json.loads(line) for line in (root / "logs.jsonl").read_text().splitlines() if line.strip()
    ]
    coverage = json.loads((root / "coverage.json").read_text())
    with httpx.Client(base_url="http://api:8000", timeout=15, trust_env=False) as client:

        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        request("GET", "/readyz")
        registered = request("POST", "/api/applications", json=configuration)
        published = request(
            "POST",
            "/api/knowledge/documents",
            json={
                "application": configuration["application"],
                "configuration_revision": registered["revision"],
                "expected_revision": None,
                "replace_application_corpus": True,
                "documents": [
                    {
                        "id": "booking-guide",
                        "title": "Booking dependency investigation",
                        "service": "global",
                        "markdown": "# Booking dependency investigation\n\nFor booking errors, correlate request IDs with availability-api logs. A downstream 503 can explain the caller's 502, but not the underlying cause. Check missing evidence and declared capture coverage.",
                    }
                ],
            },
        )
        snapshot = request(
            "POST",
            "/api/snapshots",
            json={
                **coverage,
                "application": configuration["application"],
                "environment": configuration["environment"],
                "release": configuration["release"],
                "configuration_revision": registered["revision"],
                "source_name": "synthetic-verification.jsonl",
                "records": records,
            },
        )
        incident = {
            "application": configuration["application"],
            "environment": configuration["environment"],
            "release": configuration["release"],
            "configuration_revision": registered["revision"],
            "snapshot_id": snapshot["id"],
            "service": "booking-api",
            "title": "Synthetic booking errors",
            "description": "Inspect booking errors and dependency evidence from this synthetic capture.",
            "starts_at": coverage["starts_at"],
            "ends_at": coverage["ends_at"],
        }
        admitted = request(
            "POST",
            "/api/incidents",
            json=incident,
            headers={"Idempotency-Key": "workspace-verification:" + snapshot["id"]},
        )
        iid = admitted["investigation_id"]
        path = "/api/investigations/" + iid
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            saved = request("GET", path)
            if saved["status"] in {"complete", "failed", "cancelled"}:
                break
            time.sleep(0.25)
        assert saved["status"] == "complete"
        assert saved["report"]["usage"]["model_calls"] == 0
        runbooks = next(e for e in saved["evidence"] if e["source"] == "versioned_runbooks")
        assert runbooks["availability"] == "available" and runbooks["hits"]
        assert runbooks["revision"] == published["revision"]
        stream = client.get(path + "/events/stream")
        stream.raise_for_status()
        assert "event: progress" in stream.text and "event: complete" in stream.text
        rows = request("GET", path + "/events")["items"]
        assert rows and len(rows) == stream.text.count("event: progress")
        artifact = request("POST", path + "/artifacts")
        assert artifact["backend"] == "local"
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            items = request("GET", path + "/artifacts")["items"]
            available = next(
                (
                    item
                    for item in items
                    if item["id"] == artifact["id"] and item["status"] == "available"
                ),
                None,
            )
            if available:
                break
            time.sleep(0.25)
        assert available is not None
        download = client.get(f"/api/artifacts/{artifact['id']}/download")
        download.raise_for_status()
        assert hashlib.sha256(download.content).hexdigest() == artifact["checksum"]
        assert download.json()["id"] == iid
        print(
            json.dumps(
                {
                    "kind": "synthetic-workspace-smoke-v1",
                    "application": configuration["application"],
                    "investigation_id": iid,
                    "knowledge_revision": published["revision"],
                    "artifact_id": artifact["id"],
                    "artifact_backend": "local",
                    "artifact_checksum_verified": True,
                    "model_calls": 0,
                    "data_origin": "synthetic_example",
                    "streamed_events": len(rows),
                    "diagnosis_accuracy_evaluated": False,
                }
            )
        )


if __name__ == "__main__":
    main()
