import pytest
from fastapi.testclient import TestClient
from investigator.api import create_app


def native(payload):
    return {
        "version": "4",
        "receiver": "investigator",
        "status": "firing",
        "truncatedAlerts": 0,
        "externalURL": "http://never-fetch.invalid/",
        "alerts": [
            {
                "status": "firing",
                "startsAt": payload["ends_at"],
                "endsAt": "0001-01-01T00:00:00Z",
                "fingerprint": "0123456789abcdef",
                "generatorURL": "http://never-fetch.invalid/",
                "labels": {
                    "application": "shopping-demo",
                    "service": payload["service"],
                    "environment": "local",
                    "release": "demo-v1",
                    "investigator_source": "local-monitor",
                },
                "annotations": {
                    "summary": payload["title"],
                    "description": payload["description"],
                    "investigator_window_start": payload["starts_at"],
                    "investigator_window_end": payload["ends_at"],
                },
            }
        ],
    }


@pytest.fixture
def alert_client(settings, engine, monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_TOKEN", "test-only-" + "x" * 32)
    with TestClient(create_app(settings, engine)) as client:
        client.headers["Authorization"] = "Bearer test-only-" + "x" * 32
        yield client


def test_alert_disabled_by_default_and_requires_token(client, alert_client, payload):
    delivery = {"source": "local-monitor", "occurrence_id": "one", "incident": payload}
    assert client.post("/api/webhooks/alerts", json=delivery).status_code == 503
    alert_client.headers["Authorization"] = "Bearer wrong"
    assert alert_client.post("/api/webhooks/alerts", json=delivery).status_code == 401
    assert client.get("/api/incidents").json()["items"] == []


def test_alert_duplicate_changed_delivery_recurrence_and_resolved(alert_client, payload):
    delivery = {"source": "local-monitor", "occurrence_id": "one", "incident": payload}
    first = alert_client.post("/api/webhooks/alerts", json=delivery)
    second = alert_client.post("/api/webhooks/alerts", json=delivery)
    assert first.status_code == second.status_code == 202
    assert first.json()["investigation_id"] == second.json()["investigation_id"]
    assert second.json()["replayed"]
    changed = {**delivery, "incident": {**payload, "title": "Changed alert"}}
    assert alert_client.post("/api/webhooks/alerts", json=changed).status_code == 409
    recurrence = alert_client.post(
        "/api/webhooks/alerts", json={**delivery, "occurrence_id": "two"}
    )
    assert recurrence.json()["investigation_id"] != first.json()["investigation_id"]
    resolved = alert_client.post("/api/webhooks/alerts", json={**delivery, "status": "resolved"})
    assert resolved.json()["status"] == "ignored"
    assert len(alert_client.get("/api/incidents").json()["items"]) == 2


def test_alert_bounds_and_invalid_scope(alert_client, payload):
    assert (
        alert_client.post(
            "/api/webhooks/alerts",
            content=b"x" * 16001,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    assert (
        alert_client.post(
            "/api/webhooks/alerts", content=b"abc", headers={"Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    delivery = {
        "source": "local-monitor",
        "occurrence_id": "one",
        "incident": {**payload, "service": "unknown"},
    }
    assert alert_client.post("/api/webhooks/alerts", json=delivery).status_code == 422
    delivery["incident"] = payload
    delivery["unexpected"] = "example-secret"
    response = alert_client.post("/api/webhooks/alerts", json=delivery)
    assert response.status_code == 422 and "example-secret" not in response.text


def test_native_batch_duplicate_recurrence_and_resolved(alert_client, payload):
    delivery = native(payload)
    first = alert_client.post("/api/webhooks/alertmanager", json=delivery)
    assert first.status_code == 202
    first_id = first.json()["items"][0]["investigation_id"]
    # Changing native delivery metadata does not change an occurrence's fixed window.
    delivery["alerts"][0]["endsAt"] = "2099-01-01T00:00:00Z"
    second = alert_client.post("/api/webhooks/alertmanager", json=delivery)
    assert second.json()["items"][0]["investigation_id"] == first_id
    assert second.json()["items"][0]["replayed"]
    delivery["alerts"][0]["startsAt"] = payload["starts_at"]
    recurrence = alert_client.post("/api/webhooks/alertmanager", json=delivery)
    assert recurrence.json()["items"][0]["investigation_id"] != first_id
    delivery["alerts"][0] = {
        **delivery["alerts"][0],
        "status": "resolved",
        "labels": {},
        "annotations": {},
    }
    assert (
        alert_client.post("/api/webhooks/alertmanager", json=delivery).json()["items"][0]["status"]
        == "ignored"
    )
    assert len(alert_client.get("/api/incidents").json()["items"]) == 2


def test_native_validates_entire_shape_before_admission_and_hides_contents(alert_client, payload):
    delivery = native(payload)
    delivery["alerts"].append(
        {**delivery["alerts"][0], "annotations": {"summary": "SECRET_UPLOAD"}}
    )
    response = alert_client.post("/api/webhooks/alertmanager", json=delivery)
    assert response.status_code == 422 and "SECRET_UPLOAD" not in response.text
    assert alert_client.get("/api/incidents").json()["items"] == []
    delivery = native(payload)
    delivery["truncatedAlerts"] = 1
    assert alert_client.post("/api/webhooks/alertmanager", json=delivery).status_code == 422
    delivery = native(payload)
    delivery["alerts"] *= 21
    assert alert_client.post("/api/webhooks/alertmanager", json=delivery).status_code == 422
    assert (
        alert_client.post(
            "/api/webhooks/alertmanager",
            content=b"x" * 64001,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )


def test_native_partial_admission_is_explicit_and_retries_reuse_jobs(alert_client, payload):
    delivery = native(payload)
    good = delivery["alerts"][0]
    delivery["alerts"].append({**good, "labels": {**good["labels"], "service": "unregistered"}})
    first = alert_client.post("/api/webhooks/alertmanager", json=delivery)
    assert first.status_code == 422 and first.json()["atomicity"] == "per_alert"
    assert [i["status"] for i in first.json()["items"]] == ["accepted", "rejected"]
    repeat = alert_client.post("/api/webhooks/alertmanager", json=delivery)
    assert repeat.json()["items"][0]["replayed"]
    assert len(alert_client.get("/api/incidents").json()["items"]) == 1
    changed = native(payload)
    changed["alerts"][0]["annotations"]["summary"] = "Changed description"
    assert alert_client.post("/api/webhooks/alertmanager", json=changed).status_code == 409


def test_native_requires_same_authentication_as_normalized_endpoint(client, alert_client, payload):
    assert client.post("/api/webhooks/alertmanager", json=native(payload)).status_code == 503
    alert_client.headers["Authorization"] = "Bearer wrong"
    assert alert_client.post("/api/webhooks/alertmanager", json=native(payload)).status_code == 401
