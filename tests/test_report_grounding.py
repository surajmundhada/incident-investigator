import pytest
from investigator.agent.contracts import ReportDraft, validate_references


def draft(text, references, hypotheses=None):
    return ReportDraft.model_validate(
        {
            "summary": "Recorded request failures.",
            "observations": [{"text": text, "references": references}],
            "hypotheses": hypotheses or [],
            "missing_evidence": ["Underlying trigger remains unknown."],
            "suggested_checks": [],
            "conclusion": "inconclusive",
        }
    )


def test_explicit_status_claim_requires_its_direct_caller_completion():
    source = [
        {
            "id": "a" * 32,
            "source": "snapshot_log_adapter",
            "availability": "available",
            "records": [
                {"service": "checkout", "dependency": "payment", "status_code": 503},
                {"service": "checkout", "status_code": 502},
            ],
        }
    ]
    references = [{"evidence_id": "a" * 32, "record_index": 0}]
    report = draft("Payment returned HTTP 503 and checkout returned HTTP 502.", references)
    with pytest.raises(ValueError, match="direct references"):
        validate_references(report, source, {"checkout", "payment"})
    references.append({"evidence_id": "a" * 32, "record_index": 1})
    validate_references(
        draft(report.observations[0].text, references), source, {"checkout", "payment"}
    )


def test_status_guard_does_not_confuse_latency_with_http_status():
    source = [
        {
            "id": "a" * 32,
            "source": "snapshot_log_adapter",
            "availability": "available",
            "records": [{"service": "payment", "duration_ms": 500, "status_code": 200}],
        }
    ]
    validate_references(
        draft(
            "Request took 500 ms and returned HTTP 200.",
            [{"evidence_id": "a" * 32, "record_index": 0}],
        ),
        source,
        {"payment"},
    )


def test_hypothesis_source_can_be_supported_by_a_callers_dependency_record():
    reference = {"evidence_id": "a" * 32, "record_index": 0}
    source = [
        {
            "id": "a" * 32,
            "source": "snapshot_log_adapter",
            "availability": "available",
            "records": [{"service": "checkout", "dependency": "payment", "status_code": 503}],
        }
    ]
    hypothesis = {
        "explanation": "Payment returned HTTP 503; its underlying trigger is unknown.",
        "service": "payment",
        "supporting": [reference],
    }
    report = draft("Payment returned HTTP 503.", [reference], [hypothesis])
    validate_references(report, source, {"checkout", "payment", "inventory"})
    report.hypotheses[0].service = "inventory"
    with pytest.raises(ValueError, match="not anchored"):
        validate_references(report, source, {"checkout", "payment", "inventory"})
