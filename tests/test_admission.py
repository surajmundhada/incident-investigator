from concurrent.futures import ThreadPoolExecutor

import pytest
from investigator.models import Incident, Investigation, InvestigationEvent, Job
from investigator.schemas import IncidentCreate
from sqlalchemy import event, func, select


def test_duplicate_request_returns_same_investigation(client, payload):
    one = client.post("/api/incidents", json=payload, headers={"Idempotency-Key": "duplicate"})
    two = client.post("/api/incidents", json=payload, headers={"Idempotency-Key": "duplicate"})
    assert one.status_code == two.status_code == 202
    assert one.json()["investigation_id"] == two.json()["investigation_id"]
    assert two.json()["replayed"] is True
    assert len(client.get("/api/incidents").json()["items"]) == 1


def test_key_reuse_with_changed_payload_conflicts(client, payload):
    headers = {"Idempotency-Key": "same-key"}
    assert client.post("/api/incidents", json=payload, headers=headers).status_code == 202
    changed = {**payload, "title": "A different incident"}
    assert client.post("/api/incidents", json=changed, headers=headers).status_code == 409


def test_timezone_equivalent_input_is_idempotent(repo, payload):
    from datetime import timedelta, timezone

    request = IncidentCreate(**payload)
    first = repo.admit(request, "timezone")
    shifted = request.model_copy(
        update={
            "starts_at": request.starts_at.astimezone(timezone(timedelta(hours=5, minutes=30))),
            "ends_at": request.ends_at.astimezone(timezone(timedelta(hours=5, minutes=30))),
        }
    )
    assert repo.admit(shifted, "timezone")["investigation_id"] == first["investigation_id"]


def test_incident_job_and_event_commit_atomically(repo, engine, payload):
    def reject_job(*_):
        raise RuntimeError("injected write failure")

    event.listen(Job, "before_insert", reject_job)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            repo.admit(IncidentCreate(**payload), "rollback")
    finally:
        event.remove(Job, "before_insert", reject_job)
    with repo.sessions() as db:
        for model in (Incident, Investigation, Job, InvestigationEvent):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_concurrent_duplicate_admission_creates_one_row(repo, payload):
    request = IncidentCreate(**payload)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: repo.admit(request, "concurrent"), range(2)))
    assert results[0]["investigation_id"] == results[1]["investigation_id"]
    assert len(repo.list_incidents()) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"service": "arbitrary-host"},
        {"title": "   "},
        {"description": "   "},
        {"starts_at": "2026-01-01T00:00:00"},
        {"unexpected": "extra field"},
    ],
)
def test_invalid_requests_are_rejected(client, payload, change):
    response = client.post(
        "/api/incidents", json={**payload, **change}, headers={"Idempotency-Key": "invalid"}
    )
    assert response.status_code == 422


def test_reversed_and_unbounded_windows_are_rejected(client, payload):
    from datetime import datetime, timedelta

    for start in (
        payload["ends_at"],
        (datetime.fromisoformat(payload["ends_at"]) - timedelta(hours=2)).isoformat(),
    ):
        response = client.post(
            "/api/incidents",
            json={**payload, "starts_at": start},
            headers={"Idempotency-Key": "window"},
        )
        assert response.status_code == 422


def test_missing_key_and_unknown_investigation(client, payload):
    assert client.post("/api/incidents", json=payload).status_code == 422
    assert client.get("/api/investigations/unknown").status_code == 404
    assert client.get("/api/investigations/unknown/events").status_code == 404
