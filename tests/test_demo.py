import json
import time
from datetime import datetime, timezone

import httpx
import pytest
from demo_app.control import create_app as control_app
from demo_app.control import payment_unavailable
from demo_app.evidence import create_app as evidence_app
from demo_app.service import create_app as service_app
from demo_app.telemetry import Telemetry
from fastapi.testclient import TestClient
from investigator.schemas import IncidentCreate
from investigator.tools import LogTool
from investigator.worker import run_once


def test_payment_fault_and_expiry(tmp_path, monkeypatch):
    with TestClient(control_app(tmp_path / "control")) as control:
        with TestClient(service_app("payment", tmp_path / "logs", tmp_path / "control")) as payment:
            assert payment.post("/charge", json={}).status_code == 200
            response = control.post(
                "/faults/payment", json={"mode": "unavailable", "ttl_seconds": 5}
            )
            assert response.status_code == 200
            failed = payment.post("/charge", json={})
            assert failed.status_code == 503
            assert "mode" not in failed.json()
            assert "unavailable" not in payment.get("/healthz").text
            monkeypatch.setattr(
                "demo_app.control.time.time", lambda: response.json()["expires_at"] + 1
            )
            assert payment.post("/charge", json={}).status_code == 200
            metrics = payment.get("/metrics").text
            assert 'demo_errors_total{service="payment"} 1' in metrics


def test_control_validation_and_reset(tmp_path):
    with TestClient(control_app(tmp_path)) as control:
        for payload in (
            {"mode": "anything"},
            {"mode": "unavailable", "ttl_seconds": 301},
            {"mode": "unavailable", "ttl_seconds": 0},
            {"mode": "healthy", "arbitrary": "value"},
        ):
            assert control.post("/faults/payment", json=payload).status_code == 422
        control.post("/faults/payment", json={"mode": "unavailable"})
        assert payment_unavailable(tmp_path)
        control.post("/faults/payment", json={"mode": "healthy"})
        assert not payment_unavailable(tmp_path)


@pytest.mark.parametrize("failure", ["http", "timeout"])
def test_checkout_bounds_downstream_failures_and_propagates_id(tmp_path, failure):
    seen = []

    def downstream(request):
        seen.append(request)
        if request.url.host == "payment":
            if failure == "timeout":
                raise httpx.ReadTimeout("timeout", request=request)
            return httpx.Response(503)
        return httpx.Response(200)

    with TestClient(
        service_app("checkout", tmp_path, transport=httpx.MockTransport(downstream))
    ) as app:
        response = app.post("/checkout", json={}, headers={"X-Request-ID": "a" * 32})
        assert response.status_code == (504 if failure == "timeout" else 502)
        assert response.json()["dependency"] == "payment"
        assert [request.url.host for request in seen] == ["inventory", "payment"]
        assert all(request.headers["X-Request-ID"] == "a" * 32 for request in seen)
        assert app.post("/checkout", json={"quantity": 0}).status_code == 422
    rows = [json.loads(line) for line in (tmp_path / "checkout.jsonl").read_text().splitlines()]
    assert any(row.get("request_id") == "a" * 32 and row["level"] == "ERROR" for row in rows)
    assert not any("ttl_seconds" in row or "mode" in row for row in rows)


def test_new_payment_scenarios_have_bounded_delay_and_operational_evidence(tmp_path, monkeypatch):
    delays = []
    monkeypatch.setattr("demo_app.service.time.sleep", delays.append)
    with TestClient(control_app(tmp_path / "control")) as control:
        with TestClient(service_app("payment", tmp_path / "logs", tmp_path / "control")) as payment:
            control.post("/faults/payment", json={"mode": "slow", "ttl_seconds": 5})
            assert payment.post("/charge", json={}).status_code == 200
            assert delays == [1.5]
            control.post("/faults/payment", json={"mode": "application_error", "ttl_seconds": 5})
            assert payment.post("/charge", json={}).status_code == 500
            control.post("/faults/payment", json={"mode": "healthy"})
            assert payment.post("/charge", json={}).status_code == 200
    rows = [json.loads(line) for line in (tmp_path / "logs/payment.jsonl").read_text().splitlines()]
    assert any(row["message"] == "Charge handler failed" for row in rows)
    assert not any("application_error" in str(row) or "ttl_seconds" in row for row in rows)


def test_live_source_filters_bounds_and_passes_through_worker(tmp_path, repo, payload):
    telemetry = Telemetry("payment", tmp_path)
    telemetry.emit(
        "Payment processing unavailable", level="ERROR", request_id="b" * 32, status_code=503
    )
    telemetry.emit("Request completed", status_code=200)
    telemetry.close()
    now = time.time()
    with TestClient(evidence_app(tmp_path)) as source:
        response = source.get(
            "/evidence/logs",
            params={"service": "payment", "start": now - 5, "end": now, "limit": 1},
        )
        assert response.status_code == 200
        assert response.json()["origin"] == "live"
        assert response.json()["truncated"]
        assert len(response.json()["records"]) == 1
        assert (
            source.get(
                "/evidence/logs", params={"service": "payment", "start": now + 1, "end": now + 2}
            ).json()["records"]
            == []
        )
        assert (
            source.get(
                "/evidence/logs", params={"service": "inventory", "start": now - 5, "end": now}
            ).status_code
            == 503
        )
        assert (
            source.get(
                "/evidence/logs", params={"service": "../control", "start": now - 5, "end": now}
            ).status_code
            == 422
        )
        assert (
            source.get(
                "/evidence/logs", params={"service": "payment", "start": 0, "end": now}
            ).status_code
            == 422
        )

        def forward(request):
            result = source.get(request.url.path, params=dict(request.url.params))
            return httpx.Response(result.status_code, json=result.json())

        payload["ends_at"] = datetime.fromtimestamp(now, timezone.utc).isoformat()
        admitted = repo.admit(IncidentCreate(**payload), "live-demo")
        assert run_once(repo, LogTool("http://evidence", transport=httpx.MockTransport(forward)))
        result = repo.investigation(admitted["investigation_id"])
        assert result["evidence"][0]["data_origin"] == "live"
        assert result["evidence"][0]["records"][0]["request_id"] == "b" * 32
        assert result["report"]["usage"]["model_calls"] == 0
        assert not any("fictional" in text for text in result["report"]["limitations"])


def test_corrupted_logs_are_unavailable_and_rotation_is_visible(tmp_path):
    (tmp_path / "payment.jsonl").write_text("not json\n", encoding="utf-8")
    with TestClient(evidence_app(tmp_path)) as source:
        query = {"service": "payment", "start": time.time() - 5, "end": time.time()}
        assert source.get("/evidence/logs", params=query).status_code == 503
        (tmp_path / "payment.jsonl").write_text("", encoding="utf-8")
        (tmp_path / "payment.jsonl.1").write_text("", encoding="utf-8")
        assert source.get("/evidence/logs", params=query).json()["truncated"]
