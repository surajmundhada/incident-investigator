import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from investigator.catalog import Identifier

Service = Identifier
WORKFLOW_VERSION = "bounded-investigator-v5"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LogArguments(StrictModel):
    service: Service
    request_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class RunbookArguments(StrictModel):
    service: Service
    query: str = Field(min_length=2, max_length=500)


class DependencyArguments(StrictModel):
    service: Service


class ObservationReference(StrictModel):
    evidence_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    record_index: int = Field(ge=0, le=99)


class RunbookReference(StrictModel):
    evidence_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    passage_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class ObservedClaim(StrictModel):
    text: str = Field(
        min_length=3,
        max_length=500,
        description="One narrow factual claim, fully supported by its own direct references. Split compound claims when necessary.",
    )
    references: list[ObservationReference] = Field(
        min_length=1,
        max_length=5,
        description="Cite every record needed for this claim, including caller completion and downstream evidence when describing propagation.",
    )


class Hypothesis(StrictModel):
    explanation: str = Field(min_length=3, max_length=700)
    service: Service = Field(
        description="The service hypothesized to originate the observed failure mechanism, not merely the affected caller. Use payment for a payment failure propagating to checkout; do not invent an underlying cause."
    )
    supporting: list[ObservationReference] = Field(min_length=1, max_length=5)
    contradicting: list[ObservationReference] = Field(default_factory=list, max_length=5)


class ReportDraft(StrictModel):
    summary: str = Field(min_length=3, max_length=1000)
    observations: list[ObservedClaim] = Field(max_length=8)
    hypotheses: list[Hypothesis] = Field(max_length=3)
    runbook_references: list[RunbookReference] = Field(default_factory=list, max_length=6)
    missing_evidence: list[str] = Field(max_length=8)
    suggested_checks: list[str] = Field(max_length=6)
    conclusion: Literal["supported_hypothesis", "inconclusive"]

    @model_validator(mode="after")
    def bounded_strings(self):
        if any(
            not value.strip() or len(value) > 500
            for value in self.missing_evidence + self.suggested_checks
        ):
            raise ValueError("Report checks and limitations must be bounded meaningful strings")
        if self.conclusion == "supported_hypothesis" and not self.hypotheses:
            raise ValueError("A supported hypothesis requires supporting observations")
        return self


ARGUMENTS = {
    "search_logs": LogArguments,
    "search_runbooks": RunbookArguments,
    "get_service_dependencies": DependencyArguments,
    "finish_investigation": ReportDraft,
}


class Decision(StrictModel):
    name: Literal[
        "search_logs", "search_runbooks", "get_service_dependencies", "finish_investigation"
    ]
    arguments: dict

    def validated(self):
        return ARGUMENTS[self.name].model_validate(self.arguments)


class Limits(StrictModel):
    model_calls: int = Field(default=8, ge=1, le=8)
    tool_calls: int = Field(default=12, ge=1, le=12)
    active_seconds: int = Field(default=120, ge=1, le=120)
    request_bytes: int = Field(default=32_000, ge=1000, le=32_000)
    total_request_bytes: int = Field(default=128_000, ge=1000, le=128_000)
    output_tokens_per_call: int = Field(default=2048, ge=128, le=2048)
    total_reserved_output_tokens: int = Field(default=16_384, ge=128, le=16_384)
    reported_tokens: int = Field(default=32_768, ge=1, le=32_768)


class AgentState(StrictModel):
    application: str = "shopping-demo"
    configuration_revision: str | None = None
    version: str = WORKFLOW_VERSION
    provider_id: str
    provider_origin: str
    prompt_hash: str
    limits: Limits
    started_at: float
    phase: Literal["plan", "act", "done"] = "plan"
    pending_model: bool = False
    decision: Decision | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    seen: list[str] = Field(default_factory=list)
    model_calls_started: int = 0
    tool_calls_started: int = 0
    request_bytes_used: int = 0
    reserved_output_tokens: int = 0
    reported_input_tokens: int = 0
    reported_output_tokens: int = 0
    reported_thought_tokens: int = 0
    reported_total_tokens: int = 0
    unknown_model_outcomes: int = 0
    served_model_versions: list[str] = Field(default_factory=list)
    knowledge_revision: str | None = None
    retrieval_profile: str | None = None
    termination_reason: str | None = None
    draft: ReportDraft | None = None


def validate_references(draft, evidence, permitted_services):
    lookup = {row["id"]: row for row in evidence}

    def observation(reference):
        row = lookup.get(reference.evidence_id)
        if (
            row is None
            or row.get("source") not in {"http_log_adapter", "snapshot_log_adapter"}
            or row.get("availability") != "available"
        ):
            raise ValueError("Observational references require available investigation-owned logs")
        records = row.get("records", [])
        if reference.record_index >= len(records):
            raise ValueError("Referenced log record does not exist")
        return records[reference.record_index]

    def explicit_statuses(text, records):
        # Narrow deterministic contradiction check, not a semantic entailment judge.
        stated = {
            int(code)
            for code in re.findall(
                r"\b(?:HTTP(?:\s+status(?:\s+codes?)?)?|status(?:\s+codes?)?)\s*[:=]?\s*([1-5]\d{2})\b",
                text,
                flags=re.IGNORECASE,
            )
        }
        observed = {record.get("status_code") for record in records}
        if not stated.issubset(observed):
            raise ValueError(
                "An explicit HTTP status is absent from this claim's direct references"
            )

    for claim in draft.observations:
        records = [observation(reference) for reference in claim.references]
        explicit_statuses(claim.text, records)
    for hypothesis in draft.hypotheses:
        if hypothesis.service not in permitted_services:
            raise ValueError("Hypothesis service is outside the permitted dependency scope")
        supporting = [observation(reference) for reference in hypothesis.supporting]
        for reference in hypothesis.contradicting:
            observation(reference)
        if not any(
            record.get("service") == hypothesis.service
            or record.get("dependency") == hypothesis.service
            for record in supporting
        ):
            raise ValueError("Hypothesis service is not anchored in its supporting observations")
        explicit_statuses(hypothesis.explanation, supporting)
    for reference in draft.runbook_references:
        row = lookup.get(reference.evidence_id)
        if (
            row is None
            or row.get("availability") != "available"
            or not any(hit["id"] == reference.passage_id for hit in row.get("hits", []))
        ):
            raise ValueError("Runbook citation does not belong to retrieved investigation guidance")
