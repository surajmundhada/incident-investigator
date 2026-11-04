"""Verify the documented launcher as a real process without cloud/model access."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def test_preview_process_accepts_incident_and_finishes(tmp_path, payload):
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "PYTHONPATH": str(root / "backend")}
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "investigator.preview",
            "--port",
            str(port),
            "--data-dir",
            str(tmp_path / "preview"),
        ],
        cwd=root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=flags,
    )
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=1
        ) as client:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError(process.stderr.read().decode(errors="replace"))
                try:
                    if client.get("/readyz").status_code == 200:
                        break
                except httpx.RequestError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Preview did not become ready")
            from datetime import datetime, timezone

            payload["ends_at"] = datetime.now(timezone.utc).isoformat()
            response = client.post(
                "/api/incidents", json=payload, headers={"Idempotency-Key": "preview-smoke"}
            )
            assert response.status_code == 202
            iid = response.json()["investigation_id"]
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                investigation = client.get(f"/api/investigations/{iid}").json()
                if investigation["status"] == "complete":
                    break
                time.sleep(0.1)
            assert investigation["status"] == "complete"
            assert investigation["report"]["usage"]["model_calls"] == 0
            assert investigation["evidence"][0]["data_origin"] == "fixture"
            assert len(investigation["evidence"][0]["records"]) == 2
            assert client.get("/healthz").json()["storage"] == "sqlite_preview"
    finally:
        process.terminate()
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
