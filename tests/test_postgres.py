"""Run only against an explicitly configured, disposable integration-test database."""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from investigator.repository import LostLease
from investigator.schemas import IncidentCreate
from sqlalchemy import inspect

pytestmark = pytest.mark.postgres


def test_postgres_migration_round_trip(postgres_repo):
    _, engine, config = postgres_repo
    assert "investigation_jobs" in inspect(engine).get_table_names()
    command.downgrade(config, "base")
    assert "incidents" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert "incidents" in inspect(engine).get_table_names()


def test_postgres_workers_claim_distinct_jobs(postgres_repo, payload):
    repo, _, _ = postgres_repo
    for i in range(2):
        repo.admit(IncidentCreate(**payload), f"pg-{i}")
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: repo.claim(), range(2)))
    assert all(claims)
    assert claims[0].job_id != claims[1].job_id


def test_postgres_only_one_worker_claims_single_job(postgres_repo, payload):
    repo, _, _ = postgres_repo
    repo.admit(IncidentCreate(**payload), "one-job")
    with ThreadPoolExecutor(max_workers=4) as executor:
        claims = list(executor.map(lambda _: repo.claim(), range(4)))
    assert sum(claim is not None for claim in claims) == 1


def test_postgres_concurrent_admission_is_idempotent(postgres_repo, payload):
    repo, _, _ = postgres_repo
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(lambda _: repo.admit(IncidentCreate(**payload), "same-incident"), range(4))
        )
    assert len({r["investigation_id"] for r in results}) == 1
    assert len(repo.list_incidents()) == 1


def test_postgres_expired_owner_cannot_write(postgres_repo, payload):
    repo, _, _ = postgres_repo
    repo.admit(IncidentCreate(**payload), "stale-worker")
    old = repo.claim(now=100)
    new = repo.claim(now=200)
    assert old.token != new.token
    with pytest.raises(LostLease):
        repo.finish(old, {"evidence_ids": []}, now=201)
    with pytest.raises(LostLease):
        repo.record_evidence(old, "logs.v1", {"availability": "available"}, now=201)
    repo.finish(new, {"mode": "lease_test", "evidence_ids": []}, now=202)
    assert repo.investigation(new.investigation_id)["status"] == "complete"


def test_postgres_preserves_committed_evidence_on_reclaim(postgres_repo, payload):
    repo, _, _ = postgres_repo
    repo.admit(IncidentCreate(**payload), "interrupted")
    now = time.time()
    first = repo.claim(now=now - 120)
    saved = repo.record_evidence(
        first,
        "logs.v1",
        {
            "availability": "available",
            "records": [],
            "truncated": False,
        },
        now=now - 119,
    )
    next_claim = repo.claim(now=now)
    assert next_claim.attempt == 2
    assert repo.evidence_for(next_claim.investigation_id, "logs.v1")["id"] == saved["id"]


def test_postgres_checkpoint_writes_are_fenced_and_cancelled(postgres_repo, payload):
    repo, _, _ = postgres_repo
    iid = repo.admit(IncidentCreate(**payload), "checkpoint-fencing")["investigation_id"]
    first = repo.claim(now=100)
    repo.save_checkpoint(first, {"phase": "pending_model"}, now=101)
    second = repo.claim(now=200)
    with pytest.raises(LostLease):
        repo.save_checkpoint(first, {"phase": "stale-overwrite"}, now=201)
    assert repo.checkpoint(iid) == {"phase": "pending_model"}
    repo.save_checkpoint(second, {"phase": "current-owner"}, now=201)
    repo.cancel(iid)
    with pytest.raises(LostLease):
        repo.save_checkpoint(second, {"phase": "after-cancel"}, now=202)
    assert repo.checkpoint(iid) == {"phase": "current-owner"}


def test_postgres_finish_and_cancel_have_one_terminal_winner(postgres_repo, payload):
    from investigator.repository import Conflict

    repo, _, _ = postgres_repo
    iid = repo.admit(IncidentCreate(**payload), "cancel-finish-race")["investigation_id"]
    claim = repo.claim()

    def finish():
        try:
            repo.finish(claim, {"mode": "race-test", "evidence_ids": []})
            return "complete"
        except LostLease:
            return "lost"

    def cancel():
        try:
            repo.cancel(iid)
            return "cancelled"
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda fn: fn(), (finish, cancel)))
    status = repo.investigation(iid)["status"]
    assert outcomes in (["complete", "conflict"], ["lost", "cancelled"])
    assert status in {"complete", "cancelled"}
