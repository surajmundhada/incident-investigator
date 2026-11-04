import time
from types import SimpleNamespace

import pytest
from investigator.agent.contracts import AgentState, Decision, Limits
from investigator.agent.prompt import PROMPT_HASH
from investigator.agent.provider import ModelFailure, Reply
from investigator.agent.tools import Toolset, call_key
from investigator.agent.workflow import Investigator
from investigator.repository import LostLease
from investigator.schemas import IncidentCreate


def log_batch(service="checkout"):
    return {
        "source": "http_log_adapter",
        "availability": "available",
        "service": service,
        "records": [
            {
                "timestamp": "2026-11-04T00:00:00Z",
                "service": service,
                "level": "ERROR",
                "message": "Request failed",
                "request_id": "a" * 32,
                "status_code": 502 if service == "checkout" else 503,
            }
        ],
        "data_origin": "live",
        "truncated": False,
    }


class ScriptedProvider:
    identity = "test:scripted-actions-v1"
    origin = "scripted_test"

    def __init__(self, actions):
        self.actions, self.calls = iter(actions), 0

    def request(self, context, output_tokens):
        return context

    def invoke(self, request, remaining_seconds):
        self.calls += 1
        action = next(self.actions)
        if callable(action):
            action = action(request)
        if isinstance(action, BaseException):
            raise action
        return Reply(
            Decision.model_validate(action), {"input": 20, "output": 10, "thought": 0, "total": 30}
        )


def finish(context):
    logs = [row for row in context["evidence"] if row["source"] == "http_log_adapter"]
    references = [
        {"evidence_id": row["id"], "record_index": 0}
        for row in logs
        if row["records"] and row["availability"] == "available"
    ]
    return {
        "name": "finish_investigation",
        "arguments": {
            "summary": "Observed a failed request; underlying cause remains inconclusive.",
            "observations": [
                {"text": "Requests returned error statuses.", "references": references}
            ]
            if references
            else [],
            "hypotheses": [],
            "runbook_references": [],
            "missing_evidence": ["No independent underlying-cause observation."],
            "suggested_checks": ["Compare downstream observations."],
            "conclusion": "inconclusive",
        },
    }


def prepare(repo, payload):
    request = IncidentCreate(**{**payload, "service": "checkout"})
    iid = repo.admit(request, "agent-case")["investigation_id"]
    claim = repo.claim()
    saved = repo.record_evidence(claim, "logs.v1", log_batch())
    incident = repo.investigation(iid)["incident"]
    tools = Toolset(SimpleNamespace(collect=lambda scoped: log_batch(scoped["service"])))
    return claim, incident, [saved], tools


def test_graph_follows_dependency_and_finishes_with_owned_references(repo, payload):
    claim, incident, initial, tools = prepare(repo, payload)
    provider = ScriptedProvider(
        [
            {"name": "get_service_dependencies", "arguments": {"service": "checkout"}},
            {"name": "search_logs", "arguments": {"service": "payment", "request_id": "a" * 32}},
            finish,
        ]
    )
    report = Investigator(repo, provider, tools).run(claim, incident, initial)
    repo.finish(claim, report)
    assert report["provider_origin"] == "scripted_test"
    assert report["mode"] == "agent_investigation"
    assert report["termination_reason"] == "report_completed"
    assert report["usage"]["model_calls"] == 3
    assert report["usage"]["model_tokens"] == 90
    assert len(report["evidence_ids"]) == 3
    assert len(report["observations"][0]["references"]) == 2
    assert repo.checkpoint(claim.investigation_id)["phase"] == "done"


@pytest.mark.parametrize(
    "action",
    [
        {
            "name": "search_logs",
            "arguments": {"service": "payment", "url": "http://fault-controller"},
        },
        {"name": "search_logs", "arguments": {"service": "payment", "starts_at": 0}},
        {"name": "search_logs", "arguments": {"service": "unknown"}},
    ],
)
def test_untrusted_tool_arguments_cannot_expand_permissions(repo, payload, action):
    claim, incident, initial, tools = prepare(repo, payload)
    report = Investigator(repo, ScriptedProvider([action]), tools).run(claim, incident, initial)
    assert report["termination_reason"] == "invalid_model_action"
    assert len(report["evidence_ids"]) == 1


def test_payment_scope_cannot_query_unrelated_inventory(repo, payload):
    claim, incident, initial, tools = prepare(repo, payload)
    incident["service"] = "payment"
    provider = ScriptedProvider([{"name": "search_logs", "arguments": {"service": "inventory"}}])
    report = Investigator(repo, provider, tools).run(claim, incident, initial)
    assert report["termination_reason"] == "invalid_model_action"


def test_repeated_read_stops_without_another_source_call(repo, payload):
    claim, incident, initial, tools = prepare(repo, payload)

    def unexpected(*args):
        pytest.fail("Initial log collection must not be repeated")

    tools.logs.collect = unexpected
    provider = ScriptedProvider([{"name": "search_logs", "arguments": {"service": "checkout"}}])
    report = Investigator(repo, provider, tools).run(claim, incident, initial)
    assert report["termination_reason"] == "repeated_tool_call"


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"model_calls": 1}, "model_call_budget_exhausted"),
        ({"tool_calls": 1}, "tool_call_budget_exhausted"),
        ({"request_bytes": 1000}, "request_byte_budget_exhausted"),
        ({"total_reserved_output_tokens": 128}, "output_reservation_budget_exhausted"),
        ({"reported_tokens": 1}, "reported_token_budget_exhausted"),
    ],
)
def test_budgets_stop_further_actions(repo, payload, change, reason):
    claim, incident, initial, tools = prepare(repo, payload)
    provider = ScriptedProvider(
        [{"name": "get_service_dependencies", "arguments": {"service": "checkout"}}]
    )
    if reason == "request_byte_budget_exhausted":
        provider.request = lambda context, output: {"text": "x" * 2000}
    report = Investigator(repo, provider, tools, Limits(**change)).run(claim, incident, initial)
    assert report["termination_reason"] == reason
    assert report["hypotheses"] == []


def test_invalid_and_unavailable_evidence_references_are_rejected(repo, payload):
    claim, incident, initial, tools = prepare(repo, payload)

    def forged(context):
        action = finish(context)
        action["arguments"]["observations"][0]["references"][0]["evidence_id"] = "f" * 32
        return action

    report = Investigator(repo, ScriptedProvider([forged]), tools).run(claim, incident, initial)
    assert report["termination_reason"] == "invalid_model_action"
    assert report["observations"] == []


def test_provider_failure_is_partial_with_unknown_usage(repo, payload):
    claim, incident, initial, tools = prepare(repo, payload)
    report = Investigator(
        repo, ScriptedProvider([ModelFailure("provider_rate_limited")]), tools
    ).run(claim, incident, initial)
    assert report["mode"] == "agent_partial"
    assert report["termination_reason"] == "provider_rate_limited"
    assert report["usage"]["unknown_model_outcomes"] == 1
    assert report["usage"]["model_calls"] == 1


def test_cancelled_worker_cannot_save_or_call_model(repo, payload):
    claim, incident, initial, tools = prepare(repo, payload)
    assert repo.cancel(claim.investigation_id)["status"] == "cancelled"
    provider = ScriptedProvider([finish])
    with pytest.raises(LostLease):
        Investigator(repo, provider, tools).run(claim, incident, initial)
    assert provider.calls == 0
    with pytest.raises(LostLease):
        repo.save_checkpoint(claim, {})
    assert repo.cancel(claim.investigation_id)["status"] == "cancelled"


def test_interrupted_model_call_is_not_reissued(repo, payload):
    claim, incident, initial, tools = prepare(repo, payload)
    state = AgentState(
        provider_id=ScriptedProvider.identity,
        provider_origin="scripted_test",
        prompt_hash=PROMPT_HASH,
        limits=Limits(),
        started_at=time.time(),
        pending_model=True,
        model_calls_started=1,
        evidence_ids=[initial[0]["id"]],
    )
    repo.save_checkpoint(claim, state.model_dump(mode="json"))
    provider = ScriptedProvider([])
    report = Investigator(repo, provider, tools).run(claim, incident, initial)
    assert report["termination_reason"] == "interrupted_model_outcome_unknown"
    assert provider.calls == 0
    assert report["usage"]["unknown_model_outcomes"] == 1


def test_time_budget_checked_after_model_before_tool(repo, payload):
    claim, incident, initial, tools = prepare(repo, payload)
    now = [time.time()]

    def slow(context):
        now[0] += 121
        return {"name": "get_service_dependencies", "arguments": {"service": "checkout"}}

    report = Investigator(repo, ScriptedProvider([slow]), tools, clock=lambda: now[0]).run(
        claim, incident, initial
    )
    assert report["termination_reason"] == "time_budget_exhausted"
    assert len(report["evidence_ids"]) == 1


def test_cancel_api_invalidates_queued_job(client, payload):
    iid = client.post(
        "/api/incidents", json=payload, headers={"Idempotency-Key": "cancel-api"}
    ).json()["investigation_id"]
    assert client.post(f"/api/investigations/{iid}/cancel").json()["status"] == "cancelled"
    assert client.app.state.repository.claim() is None
    assert client.post("/api/investigations/unknown/cancel").status_code == 404


def test_saved_tool_result_is_reused_after_interrupted_action(repo, payload):
    claim, incident, initial, tools = prepare(repo, payload)
    decision = Decision(name="search_logs", arguments={"service": "payment"})
    state = AgentState(
        provider_id=ScriptedProvider.identity,
        provider_origin="scripted_test",
        prompt_hash=PROMPT_HASH,
        limits=Limits(),
        started_at=time.time(),
        phase="act",
        decision=decision,
        model_calls_started=1,
        tool_calls_started=2,
        evidence_ids=[initial[0]["id"]],
    )
    repo.save_checkpoint(claim, state.model_dump(mode="json"))
    key = call_key(decision.name, decision.validated().model_dump())
    saved = repo.record_evidence(claim, key, log_batch("payment"))

    def unexpected(*args):
        pytest.fail("Saved read-only result should not be collected again")

    tools.logs.collect = unexpected
    report = Investigator(repo, ScriptedProvider([finish]), tools).run(claim, incident, initial)
    assert saved["id"] in report["evidence_ids"]
    assert report["termination_reason"] == "report_completed"


def test_cancellation_during_model_prevents_tool_execution(repo, payload):
    claim, incident, initial, tools = prepare(repo, payload)

    def cancel_during_call(context):
        repo.cancel(claim.investigation_id)
        return {"name": "get_service_dependencies", "arguments": {"service": "checkout"}}

    provider = ScriptedProvider([cancel_during_call])
    with pytest.raises(LostLease):
        Investigator(repo, provider, tools).run(claim, incident, initial)
    assert provider.calls == 1
    assert len(repo.investigation(claim.investigation_id)["evidence"]) == 1
