import json
from datetime import datetime, timezone

import pytest
from investigator.agent.contracts import LogArguments
from investigator.agent.tools import Toolset
from investigator.catalog import ApplicationConfiguration
from investigator.models import EvidenceSnapshot
from investigator.registry import Registry
from investigator.schemas import IncidentCreate
from investigator.snapshots import EvidenceTools, SnapshotCreate, SnapshotStore
from investigator.worker import run_once
from test_applications import booking_configuration


def capture(repo, payload, *, covered=None):
    config = booking_configuration()
    Registry(repo.sessions).register(config)
    request = SnapshotCreate(
        application="booking",
        configuration_revision=config.revision,
        release="v1",
        source_name="Synthetic booking example",
        starts_at=payload["starts_at"],
        ends_at=payload["ends_at"],
        covered_services=covered or ["booking-api", "availability-api"],
        synthetic_example=True,
        records=[
            {
                "timestamp": payload["ends_at"],
                "service": service,
                "level": "ERROR",
                "message": "Downstream failure password=example-secret",
                "request_id": "a" * 32,
                "status_code": 502 if service == "booking-api" else 503,
            }
            for service in (covered or ["booking-api", "availability-api"])
        ],
    )
    return config, request, SnapshotStore(repo.sessions).create(request)


def incident_request(payload, snapshot):
    return IncidentCreate(
        **{
            **payload,
            "application": "booking",
            "service": "booking-api",
            "release": "v1",
            "snapshot_id": snapshot["id"],
        }
    )


class NoLive:
    def collect(self, incident):
        pytest.fail("Captured investigations must never fall through to live evidence")


def test_snapshot_is_immutable_deduplicated_and_redacted_before_storage(repo, payload):
    _, request, snapshot = capture(repo, payload)
    duplicate = SnapshotStore(repo.sessions).create(request)
    assert duplicate["id"] == snapshot["id"] and duplicate["reused"]
    with repo.sessions() as db:
        row = db.get(EvidenceSnapshot, snapshot["id"])
        assert "example-secret" not in json.dumps(row.records)
        assert "[REDACTED]" in row.records[0]["message"]
    assert snapshot["record_count"] == 2 and snapshot["synthetic_example"]


def test_captured_investigation_pins_old_configuration_and_queries_dependencies(repo, payload):
    config, _, snapshot = capture(repo, payload)
    Registry(repo.sessions).register(booking_configuration(services={"booking-api": {}}))
    result = repo.admit(incident_request(payload, snapshot), "captured")
    incident = repo.investigation(result["investigation_id"])["incident"]
    assert incident["configuration_revision"] == config.revision
    tools = Toolset(EvidenceTools(repo.sessions, NoLive()))
    logs = tools.execute(
        "search_logs", LogArguments(service="availability-api", request_id="a" * 32), incident
    )
    assert logs["records"][0]["status_code"] == 503
    assert logs["source"] == "snapshot_log_adapter" and logs["data_origin"] == "captured"
    with pytest.raises(ValueError):
        tools.execute("search_logs", LogArguments(service="payment"), incident)


def test_missing_snapshot_service_is_unavailable_not_healthy(repo, payload):
    _, _, snapshot = capture(repo, payload, covered=["booking-api"])
    result = repo.admit(incident_request(payload, snapshot), "missing-service")
    incident = repo.investigation(result["investigation_id"])["incident"]
    logs = EvidenceTools(repo.sessions, NoLive()).collect(
        {**incident, "service": "availability-api"}
    )
    assert logs["availability"] == "unavailable" and logs["error"] == "service_not_in_snapshot"


def test_worker_finishes_captured_collection_without_provider(repo, payload):
    _, _, snapshot = capture(repo, payload)
    result = repo.admit(incident_request(payload, snapshot), "snapshot-worker")
    assert run_once(repo, EvidenceTools(repo.sessions, NoLive()))
    report = repo.investigation(result["investigation_id"])["report"]
    assert report["usage"]["model_calls"] == 0
    assert report["conclusion"] == "inconclusive"
    assert report["missing_evidence"]
    assert report["snapshot_id"] == snapshot["id"]
    assert report["observations"][0]["references"][0]["record_index"] == 0
    assert any("synthetic" in item for item in report["limitations"])


def test_agent_can_follow_captured_dependency_and_cite_snapshot_logs(repo, payload):
    from test_agent import ScriptedProvider

    _, _, snapshot = capture(repo, payload)
    result = repo.admit(incident_request(payload, snapshot), "snapshot-agent")

    def finish(context):
        logs = [item for item in context["evidence"] if item["source"] == "snapshot_log_adapter"]
        return {
            "name": "finish_investigation",
            "arguments": {
                "summary": "Captured logs show errors; underlying cause remains unknown.",
                "observations": [
                    {
                        "text": "Captured services returned errors.",
                        "references": [
                            {"evidence_id": item["id"], "record_index": 0} for item in logs
                        ],
                    }
                ],
                "hypotheses": [],
                "runbook_references": [],
                "missing_evidence": ["No underlying-cause evidence."],
                "suggested_checks": [],
                "conclusion": "inconclusive",
            },
        }

    provider = ScriptedProvider(
        [{"name": "search_logs", "arguments": {"service": "availability-api"}}, finish]
    )
    assert run_once(repo, EvidenceTools(repo.sessions, NoLive()), provider=provider)
    report = repo.investigation(result["investigation_id"])["report"]
    assert report["termination_reason"] == "report_completed"
    assert report["provider_origin"] == "scripted_test"
    assert len(report["observations"][0]["references"]) == 2


@pytest.mark.parametrize("change", ["application", "configuration", "window", "service"])
def test_admission_rejects_snapshot_scope_mismatch(repo, payload, change):
    _, _, snapshot = capture(repo, payload)
    request = incident_request(payload, snapshot)
    if change == "application":
        request.application = "shopping-demo"
    if change == "configuration":
        request.configuration_revision = "f" * 64
    if change == "window":
        request.starts_at = datetime.fromtimestamp(request.starts_at.timestamp() - 1, timezone.utc)
    if change == "service":
        request.service = "notification-api"
    with pytest.raises(ValueError):
        repo.admit(request, "invalid-capture")


def test_snapshot_upload_endpoint_bounds_and_error_sanitisation(client, repo, payload):
    _, request, _ = capture(repo, payload)
    response = client.post("/api/snapshots", json=request.model_dump(mode="json"))
    assert response.status_code == 201 and response.json()["reused"]
    assert client.get("/api/snapshots?application=shopping-demo").json()["items"] == []
    assert len(client.get("/api/snapshots?application=booking").json()["items"]) == 1
    bad = request.model_dump(mode="json")
    bad["records"][0]["message"] = "TOPSECRET" * 500
    invalid = client.post("/api/snapshots", json=bad)
    assert invalid.status_code == 422 and "TOPSECRET" not in invalid.text
    assert (
        client.post(
            "/api/snapshots", content=b"x" * 1_000_001, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/api/snapshots",
            content=request.model_dump_json(),
            headers={"Content-Type": "text/plain"},
        ).status_code
        == 415
    )
    assert client.post("/api/snapshots", content=request.model_dump_json()).status_code == 415


def test_snapshot_adapter_rejects_changed_environment_and_release(repo, payload):
    _, _, snapshot = capture(repo, payload)
    result = repo.admit(incident_request(payload, snapshot), "scope-mutation")
    incident = repo.investigation(result["investigation_id"])["incident"]
    tools = EvidenceTools(repo.sessions, NoLive())
    for field, value in (("environment", "production"), ("release", "another-release")):
        logs = tools.collect({**incident, field: value})
        assert logs["availability"] == "unavailable"
        assert logs["error"] == "snapshot_scope_mismatch"


def test_coverage_and_record_service_validation(repo, payload):
    config = ApplicationConfiguration(
        application="booking", release="v1", services={"booking-api": {}}
    )
    Registry(repo.sessions).register(config)
    request = SnapshotCreate(
        application="booking",
        configuration_revision=config.revision,
        release="v1",
        source_name="Empty declared coverage",
        covered_services=["booking-api"],
        records=[],
        starts_at=payload["starts_at"],
        ends_at=payload["ends_at"],
    )
    snapshot = SnapshotStore(repo.sessions).create(request)
    incident = repo.investigation(
        repo.admit(incident_request(payload, snapshot), "empty-coverage")["investigation_id"]
    )["incident"]
    logs = EvidenceTools(repo.sessions, NoLive()).collect(incident)
    assert logs["availability"] == "available" and logs["records"] == []
    assert "not independently verified" in logs["coverage_basis"]
