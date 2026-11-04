"""LangGraph orchestration with application-owned, lease-fenced state persistence."""

import json
import time
from typing import TypedDict

from pydantic import ValidationError

from .contracts import WORKFLOW_VERSION, AgentState, Limits, validate_references
from .prompt import PROMPT_HASH
from .provider import ModelFailure
from .security import SECURITY_VERSION, redact
from .tools import call_key, permitted_services


class GraphState(TypedDict):
    snapshot: dict


class Investigator:
    def __init__(self, repo, provider, tools, limits=None, clock=time.time):
        self.repo, self.provider, self.tools = repo, provider, tools
        self.limits, self.clock = limits or Limits(), clock

    def run(self, claim, incident, initial_evidence):
        from langgraph.graph import END, START, StateGraph
        from langsmith import tracing_context

        def save(state, event=None):
            self.repo.save_checkpoint(claim, state.model_dump(mode="json"), event)
            return {"snapshot": state.model_dump(mode="json")}

        def stop(state, reason):
            state.phase, state.termination_reason = "done", reason
            state.decision = None
            return save(state, "Agent stopped: " + reason)

        def evidence(state):
            # Resolve only evidence belonging to this job; IDs are checked again at finalization.
            rows = self.repo.investigation(claim.investigation_id)["evidence"]
            return [row for row in rows if row["id"] in state.evidence_ids]

        def context(state):
            compact = []
            for row in evidence(state):
                item = {key: value for key, value in row.items() if key not in {"records", "hits"}}
                if "records" in row:
                    # Prefer errors but retain original indices for verifiable references.
                    indexed = list(enumerate(row["records"]))
                    indexed.sort(key=lambda pair: (pair[1]["level"] != "ERROR", pair[0]))
                    item["records"] = [
                        {"record_index": index, **record} for index, record in indexed[:20]
                    ]
                    item["context_omitted_records"] = max(0, len(indexed) - 20)
                if "hits" in row:
                    item["hits"] = [
                        {
                            key: hit[key]
                            for key in (
                                "id",
                                "document_id",
                                "heading",
                                "body",
                                "source",
                                "line_start",
                                "line_end",
                            )
                            if key in hit
                        }
                        for hit in row["hits"][:6]
                    ]
                compact.append(item)
            return redact(
                {
                    "incident": incident,
                    "evidence": compact,
                    "permitted_services": sorted(permitted_services(incident)),
                    "completed_call_keys": state.seen,
                    "remaining_model_calls": state.limits.model_calls - state.model_calls_started,
                    "remaining_tool_calls": state.limits.tool_calls - state.tool_calls_started,
                }
            )

        def add_usage(state, usage):
            if usage is None:
                state.unknown_model_outcomes += 1
                return
            state.reported_input_tokens += usage["input"]
            state.reported_output_tokens += usage["output"]
            state.reported_thought_tokens += usage["thought"]
            state.reported_total_tokens += usage["total"]

        def guard(state):
            self.repo.heartbeat(claim)
            if self.clock() - state.started_at >= state.limits.active_seconds:
                return "time_budget_exhausted"
            return None

        def plan(wrapped):
            state = AgentState.model_validate(wrapped["snapshot"])
            reason = guard(state)
            if reason:
                return stop(state, reason)
            if state.model_calls_started >= state.limits.model_calls:
                return stop(state, "model_call_budget_exhausted")
            if state.reported_total_tokens >= state.limits.reported_tokens:
                return stop(state, "reported_token_budget_exhausted")
            if (
                state.reserved_output_tokens + state.limits.output_tokens_per_call
                > state.limits.total_reserved_output_tokens
            ):
                return stop(state, "output_reservation_budget_exhausted")
            request = self.provider.request(context(state), state.limits.output_tokens_per_call)
            size = len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode())
            if (
                size > state.limits.request_bytes
                or size + state.request_bytes_used > state.limits.total_request_bytes
            ):
                return stop(state, "request_byte_budget_exhausted")
            state.model_calls_started += 1
            state.request_bytes_used += size
            state.reserved_output_tokens += state.limits.output_tokens_per_call
            state.pending_model = True
            save(state, f"Model request {state.model_calls_started} reserved")
            try:
                reply = self.provider.invoke(
                    request,
                    max(0.1, state.limits.active_seconds - (self.clock() - state.started_at)),
                )
            except ModelFailure as exc:
                add_usage(state, exc.usage)
                state.pending_model = False
                return stop(state, exc.code)
            add_usage(state, reply.usage)
            if reply.model_version and reply.model_version not in state.served_model_versions:
                state.served_model_versions.append(reply.model_version)
            state.pending_model = False
            if self.clock() - state.started_at >= state.limits.active_seconds:
                return stop(state, "time_budget_exhausted")
            if state.reported_total_tokens > state.limits.reported_tokens:
                return stop(state, "reported_token_budget_exhausted")
            try:
                arguments = reply.decision.validated()
                if reply.decision.name == "finish_investigation":
                    validate_references(arguments, evidence(state), permitted_services(incident))
                    state.draft = arguments
                    return stop(state, "report_completed")
                if arguments.service not in permitted_services(incident):
                    raise ValueError("Service outside scope")
            except (ValueError, ValidationError):
                return stop(state, "invalid_model_action")
            state.decision, state.phase = reply.decision, "act"
            return save(state, "Validated tool action: " + reply.decision.name)

        def act(wrapped):
            state = AgentState.model_validate(wrapped["snapshot"])
            reason = guard(state)
            if reason:
                return stop(state, reason)
            decision = state.decision
            if decision is None:
                return stop(state, "invalid_saved_action")
            arguments = decision.validated()
            key = call_key(decision.name, arguments.model_dump())
            saved = self.repo.evidence_for(claim.investigation_id, key)
            if key in state.seen:
                return stop(state, "repeated_tool_call")
            if saved is None:
                if state.tool_calls_started >= state.limits.tool_calls:
                    return stop(state, "tool_call_budget_exhausted")
                state.tool_calls_started += 1
                save(state, "Read-only tool request reserved: " + decision.name)
                payload = self.tools.execute(
                    decision.name,
                    arguments,
                    {
                        **incident,
                        "knowledge_revision": state.knowledge_revision,
                        "retrieval_profile": state.retrieval_profile,
                    },
                )
                saved = self.repo.record_evidence(claim, key, payload)
            if saved.get("revision") and state.knowledge_revision is None:
                state.knowledge_revision = saved["revision"]
                state.retrieval_profile = saved.get("ranking_profile")
            if saved["id"] not in state.evidence_ids:
                state.evidence_ids.append(saved["id"])
            state.seen.append(key)
            state.phase, state.decision = "plan", None
            return save(state, "Read-only tool result persisted")

        old = self.repo.checkpoint(claim.investigation_id)
        if old:
            state = AgentState.model_validate(old)
            if state.pending_model:
                state.unknown_model_outcomes += 1
                state.pending_model = False
                stop(state, "interrupted_model_outcome_unknown")
            elif (
                state.provider_id != self.provider.identity
                or state.prompt_hash != PROMPT_HASH
                or state.version != WORKFLOW_VERSION
                or state.limits != self.limits
            ):
                stop(state, "workflow_configuration_changed")
        else:
            state = AgentState(
                application=incident.get("application", "shopping-demo"),
                configuration_revision=incident.get("configuration_revision"),
                provider_id=self.provider.identity,
                provider_origin=self.provider.origin,
                prompt_hash=PROMPT_HASH,
                limits=self.limits,
                started_at=float(self.clock()),
                evidence_ids=[row["id"] for row in initial_evidence],
                tool_calls_started=len(initial_evidence),
                knowledge_revision=next(
                    (row["revision"] for row in initial_evidence if row.get("revision")), None
                ),
                retrieval_profile=next(
                    (
                        row["ranking_profile"]
                        for row in initial_evidence
                        if row.get("ranking_profile")
                    ),
                    None,
                ),
            )
            state.seen.append(
                call_key("search_logs", {"service": incident["service"], "request_id": None})
            )
            save(state, "Bounded agent started")
        if state.phase != "done":
            graph = StateGraph(GraphState)
            graph.add_node("plan", plan)
            graph.add_node("act", act)
            graph.add_conditional_edges(
                START, lambda wrapped: wrapped["snapshot"]["phase"], {"plan": "plan", "act": "act"}
            )
            graph.add_conditional_edges(
                "plan", lambda wrapped: wrapped["snapshot"]["phase"], {"act": "act", "done": END}
            )
            graph.add_conditional_edges(
                "act", lambda wrapped: wrapped["snapshot"]["phase"], {"plan": "plan", "done": END}
            )
            with tracing_context(enabled=False):
                final = graph.compile().invoke(
                    {"snapshot": state.model_dump(mode="json")},
                    config={"recursion_limit": 32, "callbacks": []},
                )
            state = AgentState.model_validate(final["snapshot"])
        return self.report(state, evidence(state))

    @staticmethod
    def report(state, evidence):
        draft = (
            state.draft.model_dump(mode="json")
            if state.draft
            else {
                "summary": "Investigation stopped: " + (state.termination_reason or "unknown"),
                "observations": [],
                "hypotheses": [],
                "runbook_references": [],
                "missing_evidence": ["A validated generated report was not completed."],
                "suggested_checks": [],
                "conclusion": "inconclusive",
            }
        )
        return {
            **draft,
            "mode": "agent_investigation" if state.draft else "agent_partial",
            "provider_origin": state.provider_origin,
            "model": state.provider_id,
            "served_model_versions": state.served_model_versions,
            "workflow_version": state.version,
            "application": state.application,
            "configuration_revision": state.configuration_revision,
            "knowledge_revision": state.knowledge_revision,
            "retrieval_profile": state.retrieval_profile,
            "prompt_hash": state.prompt_hash,
            "security_version": SECURITY_VERSION,
            "termination_reason": state.termination_reason,
            "evidence_ids": state.evidence_ids,
            "limits": state.limits.model_dump(),
            "usage": {
                "model_calls": state.model_calls_started,
                "tool_calls_started": state.tool_calls_started,
                "model_tokens": state.reported_total_tokens,
                "reported_input_tokens": state.reported_input_tokens,
                "reported_output_tokens": state.reported_output_tokens,
                "reported_thought_tokens": state.reported_thought_tokens,
                "unknown_model_outcomes": state.unknown_model_outcomes,
                "request_bytes": state.request_bytes_used,
                "reserved_output_tokens": state.reserved_output_tokens,
            },
            "limitations": [
                "References are validated structurally; this does not establish semantic support or causal accuracy.",
                "Hypotheses require review; no remediation was executed.",
            ]
            + (
                ["Some observations are fictional fixtures."]
                if any(row.get("data_origin") == "fixture" for row in evidence)
                else []
            )
            + (
                ["Some evidence sources were unavailable."]
                if any(row.get("availability") != "available" for row in evidence)
                else []
            )
            + (
                ["Some evidence was truncated or omitted from model context."]
                if any(row.get("truncated") or len(row.get("records", [])) > 20 for row in evidence)
                else []
            ),
        }
