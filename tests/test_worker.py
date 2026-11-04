import time

import pytest
from investigator.repository import LostLease
from investigator.schemas import IncidentCreate
from investigator.worker import collect_report, run_once


def observation():
    return {
        "source": "test_fixture",
        "service": "payment",
        "availability": "available",
        "window": {"start": 0, "end": time.time()},
        "collected_at": "2026-11-03T00:00:00Z",
        "records": [
            {
                "timestamp": "2026-11-03T00:00:00Z",
                "service": "payment",
                "level": "ERROR",
                "message": "Database connection failed",
            }
        ],
        "truncated": False,
    }


class StubTool:
    def __init__(self):
        self.calls = 0

    def collect(self, _):
        self.calls += 1
        return observation()


def test_worker_persists_evidence_and_honest_report(repo, payload):
    admission = repo.admit(IncidentCreate(**payload), "worker")
    tool = StubTool()
    assert run_once(repo, tool)
    result = repo.investigation(admission["investigation_id"])
    assert result["status"] == "complete"
    assert result["report"]["mode"] == "evidence_collection_only"
    assert result["report"]["hypotheses"] == []
    assert result["report"]["usage"]["model_calls"] == 0
    assert len(result["evidence"]) == 1
    assert result["report"]["evidence_ids"] == [result["evidence"][0]["id"]]
    assert not run_once(repo, tool)
    assert tool.calls == 1


def test_unavailable_source_is_not_treated_as_no_errors(repo, payload):
    admission = repo.admit(IncidentCreate(**payload), "missing")

    class Unavailable:
        def collect(self, _):
            return {
                **observation(),
                "availability": "unavailable",
                "records": [],
                "error": "source_unreachable",
            }

    run_once(repo, Unavailable())
    report = repo.investigation(admission["investigation_id"])["report"]
    assert report["termination_reason"] == "insufficient_evidence"
    assert "unavailable" in report["summary"].lower()


def test_evidence_only_report_exposes_unavailable_guidance_as_missing():
    logs = {**observation(), "id": "a" * 32}
    report = collect_report(logs, {"id": "b" * 32, "availability": "unavailable", "hits": []})
    assert report["conclusion"] == "inconclusive"
    assert any("runbook" in value.lower() for value in report["missing_evidence"])
    assert report["usage"]["model_calls"] == 0


def test_expired_worker_cannot_finalize_or_record(repo, payload):
    repo.admit(IncidentCreate(**payload), "lease")
    first = repo.claim(now=100)
    assert repo.claim(now=101) is None
    second = repo.claim(now=200)
    assert second.token != first.token
    assert second.attempt == 2
    with pytest.raises(LostLease):
        repo.record_evidence(first, "logs.v1", observation(), now=201)
    with pytest.raises(LostLease):
        repo.finish(first, {"evidence_ids": []}, now=201)
    evidence = repo.record_evidence(second, "logs.v1", observation(), now=201)
    repo.finish(second, collect_report(evidence), now=202)


def test_persisted_observation_survives_crash_before_finalization(repo, payload):
    admission = repo.admit(IncidentCreate(**payload), "resume")
    now = time.time()
    claim = repo.claim(now=now - 120)
    saved = repo.record_evidence(claim, "logs.v1", observation(), now=now - 119)
    # Worker disappears here. Next worker reclaims after its lease and reuses the observation.
    tool = StubTool()
    run_once(repo, tool)
    result = repo.investigation(admission["investigation_id"])
    assert result["status"] == "complete"
    assert result["attempts"] == 2
    assert tool.calls == 0
    assert result["evidence"][0]["id"] == saved["id"]


def test_attempt_limit_terminates_abandoned_job(repo, payload):
    admission = repo.admit(IncidentCreate(**payload), "exhaust")
    assert repo.claim(now=100).attempt == 1
    assert repo.claim(now=200).attempt == 2
    assert repo.claim(now=300).attempt == 3
    assert repo.claim(now=400) is None
    assert repo.investigation(admission["investigation_id"])["status"] == "failed"


def test_foreign_evidence_rejected_and_completion_rolled_back(repo, payload):
    admission = repo.admit(IncidentCreate(**payload), "foreign")
    claim = repo.claim()
    with pytest.raises(ValueError, match="outside"):
        repo.finish(claim, {"evidence_ids": ["not-owned"]})
    assert repo.investigation(admission["investigation_id"])["status"] == "running"


def test_duplicate_evidence_call_is_reused(repo, payload):
    repo.admit(IncidentCreate(**payload), "same-result")
    claim = repo.claim()
    first = repo.record_evidence(claim, "logs.v1", observation())
    second = repo.record_evidence(claim, "logs.v1", observation())
    assert first["id"] == second["id"]


def test_progress_cursor_does_not_repeat_events(repo, payload):
    iid = repo.admit(IncidentCreate(**payload), "events")["investigation_id"]
    first = repo.events(iid)
    run_once(repo, StubTool())
    later = repo.events(iid, after=first[-1]["id"])
    assert later
    assert all(row["id"] > first[-1]["id"] for row in later)
    assert later[-1]["kind"] == "complete"
