"""Read-only reconciliation of release documentation and frozen result artifacts."""

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def verify():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    doc = (ROOT / "docs/evaluation.md").read_text(encoding="utf-8")
    checks = []

    def check(label, actual, expected):
        if actual != expected:
            raise ValueError(f"Documented metric mismatch: {label}")
        checks.append({"check": label, "value": actual})

    cache = load("docs/cache-benchmark.json")
    check("cache trials per main workload", cache["trials"], 40)
    check("cache corpus documents", cache["corpus"]["documents"], 13)
    check("cache corpus passages", cache["corpus"]["passages"], 32)
    for key, displayed in [
        ("disabled/warm_repeated", "9.245"),
        ("both/warm_repeated", "1.694"),
        ("disabled/unique", "9.781"),
        ("both/unique", "12.466"),
    ]:
        row = cache["measurements"][key]
        check(key + " requests", row["requests"], 40)
        check(key + " p50 rounded", f"{row['p50_ms']:.3f}", displayed)
        check(key + " README value", displayed in readme, True)
        check(key + " evaluation value", displayed in doc, True)
    check(
        "warm median improvement rounded",
        f"{cache['repeated_median_improvement_percent']:.1f}",
        "81.7",
    )
    values = cache["measurements"]
    overhead = 100 * (values["both/unique"]["p50_ms"] / values["disabled/unique"]["p50_ms"] - 1)
    check("unique median overhead rounded", f"{overhead:.1f}", "27.4")
    check("unique overhead documentation", "27.4%" in doc, True)

    heldout = load("evaluation/results/heldout.json")
    for variant, recall, mrr in [
        ("frozen_hybrid", "86.7", "0.844"),
        ("v2_baseline", "86.7", "0.844"),
        ("improved", "90.0", "0.789"),
    ]:
        summary = heldout["variants"][variant]["summary"]
        check(variant + " recall rounded", f"{100 * summary['recall_at_5']:.1f}", recall)
        check(variant + " MRR rounded", f"{summary['mrr_at_5']:.3f}", mrr)
        check(variant + " answerable", summary["answerable_cases"], 15)
        check(variant + " absent", summary["no_answer_cases"], 5)
        check(variant + " documented pair", f"{recall}% | {mrr}" in doc, True)
    check("experimental profile not promoted", "not promoted" in doc, True)

    pilot = load("evaluation/diagnosis-v2/results/development-pilot.json")
    check("pilot distinct cases", len({row["case_id"] for row in pilot["rows"]}), 4)
    check("pilot calls", pilot["calls_started"], 12)
    check("pilot reported tokens", pilot["reported_tokens"], 61104)
    check("pilot serialized input bytes", pilot["input_bytes"], 177851)
    for method, expected in [("logs_only", 4), ("all_context", 3), ("baseline_rag", 4)]:
        rows = [row for row in pilot["rows"] if row["method"] == method]
        check(method + " pilot rows", len(rows), 4)
        check(method + " valid", Counter(r["status"] for r in rows)["structurally_valid"], expected)
    for value in ["61,104", "177,851", "4/4", "3/4"]:
        check("pilot documentation " + value, value in doc, True)

    workflow = load("evaluation/diagnosis-v2/results/workflow-heldout/summary.json")
    for field, value in [
        ("planned_episodes", 52),
        ("attempted_episodes", 10),
        ("valid_reports", 9),
        ("calls_started", 14),
        ("reported_tokens", 60138),
        ("complete", False),
        ("stop", "provider_error"),
    ]:
        check("workflow " + field, workflow[field], value)
    check("workflow documentation tokens", "60,138" in doc, True)
    provenance = load("evaluation/external-online-boutique/provenance.json")
    check("external record count", provenance["records"], 120)
    check("external service count", len(provenance["services"]), 6)
    check(
        "retained dataset license",
        (ROOT / "examples/external-online-boutique/LICENSE-RCAEval.txt").exists(),
        True,
    )
    for lock_name, base in [
        ("evaluation/data-lock.json", ROOT / "evaluation"),
        ("evaluation/baseline-v1/snapshot.json", ROOT / "evaluation/baseline-v1"),
    ]:
        lock = load(lock_name)
        for name, expected in lock.get("files", lock).items():
            check(
                "frozen input " + name,
                hashlib.sha256((base / name).read_bytes()).hexdigest(),
                expected,
            )
    return {"checks": checks, "result": "passed", "result_files_modified": False}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
