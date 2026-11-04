"""Operator-only complete log captures for a fresh diagnosis study, zero model calls.

Records labels separately from anonymous snapshots. Does not submit investigations.
The demo is a controlled synthetic workload, not independent production evidence.
"""

import argparse
import hashlib
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from start_s3 import executable


def capture(output, repeats):
    output.mkdir(parents=True, exist_ok=False)  # Never overwrite a recorded study.
    docker = executable("docker.exe", "Programs/DockerDesktop/resources/bin/docker.exe")
    labels, files = [], {}
    modes = ("healthy", "unavailable", "slow", "application_error")
    with httpx.Client(timeout=10, trust_env=False) as client:

        def set_mode(mode):
            response = client.post(
                "http://127.0.0.1:8003/faults/payment", json={"mode": mode, "ttl_seconds": 60}
            )
            response.raise_for_status()

        try:
            for repetition in range(repeats):
                for mode in modes:
                    case_id = uuid.uuid4().hex
                    set_mode("healthy")
                    assert client.post("http://127.0.0.1:8002/checkout", json={}).status_code == 200
                    set_mode(mode)
                    start = datetime.now(timezone.utc)
                    statuses, request_ids = [], []
                    for _ in range(2 + repetition % 2):
                        response = client.post("http://127.0.0.1:8002/checkout", json={})
                        statuses.append(response.status_code)
                        request_ids.append(response.json()["request_id"])
                    if mode == "slow":
                        time.sleep(0.7)  # Include the last payment completion after caller timeout.
                    end = datetime.now(timezone.utc)
                    expected = {
                        "healthy": 200,
                        "unavailable": 502,
                        "slow": 504,
                        "application_error": 502,
                    }[mode]
                    assert statuses and all(status == expected for status in statuses)
                    records = []
                    for service in ("checkout", "payment", "inventory"):
                        # The read-only source's API is queried from inside its container.
                        # No fault labels/control endpoints enter the capture or agent network.
                        url = (
                            f"http://127.0.0.1:8000/evidence/logs?service={service}"
                            f"&start={start.timestamp()}&end={end.timestamp()}&limit=100"
                        )
                        code = "import urllib.request,sys;sys.stdout.write(urllib.request.urlopen(sys.argv[1],timeout=5).read().decode())"
                        result = subprocess.run(
                            [
                                docker,
                                "exec",
                                "incident-investigator-demo-evidence-1",
                                "python",
                                "-c",
                                code,
                                url,
                            ],
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            timeout=15,
                        )
                        if result.returncode:
                            raise RuntimeError("Read-only capture source failed")
                        batch = json.loads(result.stdout)
                        if batch["truncated"]:
                            raise RuntimeError(
                                "Capture retention/limit is truncated; cannot claim complete coverage"
                            )
                        records.extend(batch["records"])
                    assert all(
                        any(
                            r.get("request_id") == rid and r["service"] == "payment"
                            for r in records
                        )
                        for rid in request_ids
                    )
                    payload = {
                        "application": "shopping-demo",
                        "environment": "local",
                        "release": "demo-v1",
                        "source_name": case_id + ".jsonl",
                        "starts_at": start.isoformat(),
                        "ends_at": end.isoformat(),
                        "covered_services": ["checkout", "payment", "inventory"],
                        "synthetic_example": True,
                        "records": records,
                    }
                    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                    name = case_id + ".json"
                    (output / name).write_bytes(data)
                    files[name] = hashlib.sha256(data).hexdigest()
                    labels.append(
                        {
                            "case_id": case_id,
                            "family": mode,
                            "responsible_service": None if mode == "healthy" else "payment",
                            "split": "development" if repetition < 2 else "heldout",
                            "request_ids": request_ids,
                        }
                    )
                    print(f"Captured {len(labels)} anonymous windows.", flush=True)
        finally:
            set_mode("healthy")
    (output / "labels.operator.json").write_text(json.dumps(labels, indent=2))
    (output / "capture-lock.json").write_text(
        json.dumps(
            {
                "version": "live-captures-v1",
                "files": files,
                "labels_sha256": hashlib.sha256(
                    (output / "labels.operator.json").read_bytes()
                ).hexdigest(),
                "cases": len(labels),
                "model_calls": 0,
                "captured_before_agent_queries": True,
                "origin": "controlled_demo_http",
                "independent_production_dataset": False,
                "split_unit": "repeated_instance; fault families shared across splits",
                "application_configuration_revision_required_at_replay": True,
            },
            indent=2,
        )
    )
    print(
        "Capture complete; labels remain operator-only. No model calls or investigation submissions."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, choices=range(3, 7), default=6)
    args = parser.parse_args()
    capture(args.output.resolve(), args.repeats)
