import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "score_workflow", Path(__file__).with_name("score_workflow.py")
)
scoring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scoring)

LABELS = [
    {
        "case_id": "fault",
        "split": "heldout",
        "family": "unavailable",
        "responsible_service": "payment",
    },
    {"case_id": "normal", "split": "heldout", "family": "healthy", "responsible_service": None},
]


def study(rows):
    return {
        "stop": "provider_error",
        "rows": rows,
        "calls_started": len(rows),
        "reported_tokens": 1,
    }


def row(case, hypotheses, *, mode="agent_investigation", conclusion="supported_hypothesis"):
    return {
        "case_id": case,
        "method": "agent",
        "saved": {
            "report": {
                "mode": mode,
                "termination_reason": "report_completed",
                "hypotheses": hypotheses,
                "conclusion": conclusion,
            }
        },
    }


def test_partial_provider_run_never_becomes_a_final_accuracy_claim():
    result = scoring.summarize(study([row("fault", [{"service": "payment"}])]), LABELS)
    agent = next(method for method in result["methods"] if method["method"] == "agent")
    assert agent["fault_top1_correct_count"] == 1
    assert agent["fault_top1_fraction"] is None and not result["complete"]


def test_duplicate_episode_cannot_replace_an_earlier_outcome():
    value = row("fault", [{"service": "payment"}])
    with pytest.raises(ValueError, match="Duplicate"):
        scoring.summarize(study([value, value]), LABELS)


def test_partial_report_and_healthy_causal_hypothesis_do_not_count_correct():
    result = scoring.summarize(
        study(
            [
                row("fault", [{"service": "payment"}], mode="agent_partial"),
                row("normal", [{"service": "checkout"}]),
            ]
        ),
        LABELS,
    )
    agent = next(method for method in result["methods"] if method["method"] == "agent")
    assert agent["fault_top1_correct_count"] == agent["healthy_correct_count"] == 0
    result = scoring.summarize(study([row("normal", [], conclusion="inconclusive")]), LABELS)
    assert (
        next(method for method in result["methods"] if method["method"] == "agent")[
            "healthy_correct_count"
        ]
        == 1
    )
