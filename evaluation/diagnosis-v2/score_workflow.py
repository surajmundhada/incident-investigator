"""Mechanical typed-service matching only; incomplete phases receive no accuracy percentage."""

import json
from pathlib import Path

HERE = Path(__file__).parent


def valid(row):
    report = row.get("saved", {}).get("report") or {}
    return (
        report.get("mode") == "agent_investigation"
        and report.get("termination_reason") == "report_completed"
    )


def summarize(study, labels):
    heldout = {row["case_id"]: row for row in labels if row["split"] == "heldout"}
    rows = {(row["case_id"], row["method"]): row for row in study["rows"]}
    if len(rows) != len(study["rows"]):
        raise ValueError("Duplicate episodes cannot replace earlier outcomes")
    complete = study.get("stop") == "completed" and len(study["rows"]) == 52
    methods = []
    for method in ("logs_only", "rag", "agent"):
        fault, healthy = [], []
        for case, label in heldout.items():
            row = rows.get((case, method))
            report = row.get("saved", {}).get("report", {}) if row else {}
            hypotheses = report.get("hypotheses", []) if report else []
            entry = {
                "case_id": case,
                "attempted": row is not None,
                "valid_report": bool(row and valid(row)),
            }
            if label["family"] == "healthy":
                entry["correct"] = (
                    entry["valid_report"]
                    and not hypotheses
                    and report.get("conclusion") == "inconclusive"
                )
                healthy.append(entry)
            else:
                services = [hypothesis["service"] for hypothesis in hypotheses]
                entry["correct"] = (
                    entry["valid_report"]
                    and bool(services)
                    and services[0] == label["responsible_service"]
                )
                entry["top3_correct"] = (
                    entry["valid_report"] and label["responsible_service"] in services[:3]
                )
                fault.append(entry)
        correct = sum(row["correct"] for row in fault)
        methods.append(
            {
                "method": method,
                "planned_fault_cases": len(fault),
                "attempted_fault_cases": sum(row["attempted"] for row in fault),
                "fault_top1_correct_count": correct,
                "fault_top1_fraction": correct / len(fault) if complete else None,
                "planned_healthy_cases": len(healthy),
                "healthy_correct_count": sum(row["correct"] for row in healthy),
                "healthy_correct_fraction": sum(row["correct"] for row in healthy) / len(healthy)
                if complete
                else None,
                "fault_cases": fault,
                "healthy_cases": healthy,
            }
        )
    return {
        "kind": "typed_failure_localization_summary_v1",
        "complete": complete,
        "stop": study.get("stop"),
        "planned_episodes": 52,
        "attempted_episodes": len(study["rows"]),
        "valid_reports": sum(valid(row) for row in study["rows"]),
        "calls_started": study["calls_started"],
        "reported_tokens": study["reported_tokens"],
        "methods": methods,
        "limitations": "Counts from an incomplete run are not final accuracy. Typed originating-service match is not semantic faithfulness or proof of underlying cause. No failed or unknown episode was retried.",
    }


if __name__ == "__main__":
    path = HERE / "results/workflow-heldout/results.json"
    study = json.loads(path.read_text())
    labels = json.loads((HERE / "captures/labels.operator.json").read_text())
    summary = summarize(study, labels)
    (HERE / "results/workflow-heldout/summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({key: value for key, value in summary.items() if key != "methods"}, indent=2))
