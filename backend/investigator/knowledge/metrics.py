"""Section-level retrieval metrics. No labels or external judge calls live here."""

import math
import statistics


def measure(hits, relevant, k=5):
    expected = {(row["document"], row["heading"]) for row in relevant}
    if not expected:
        return {"answerable": False, "abstained": not hits}
    seen, gains, first = set(), [], None
    for rank, hit in enumerate(hits[:k], 1):
        unit = (hit["document_id"], hit["heading"])
        correct = unit in expected and unit not in seen
        gains.append(int(correct) / math.log2(rank + 1))
        if correct and first is None:
            first = rank
        seen.add(unit)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, len(expected)) + 1))
    return {
        "answerable": True,
        "recall_at_5": len(seen & expected) / len(expected),
        "mrr_at_5": 1 / first if first else 0.0,
        "ndcg_at_5": sum(gains) / ideal,
    }


def summarize(rows):
    answerable = [row for row in rows if row["metrics"]["answerable"]]
    absent = [row for row in rows if not row["metrics"]["answerable"]]
    timings = sorted(ms for row in rows for ms in row["latencies_ms"])
    scores = {
        key: statistics.mean(row["metrics"][key] for row in answerable)
        for key in ("recall_at_5", "mrr_at_5", "ndcg_at_5")
    }
    return {
        **scores,
        "no_answer_abstention": statistics.mean(row["metrics"]["abstained"] for row in absent)
        if absent
        else None,
        "p50_ms": statistics.median(timings),
        "p95_ms": timings[max(0, math.ceil(0.95 * len(timings)) - 1)],
        "answerable_cases": len(answerable),
        "no_answer_cases": len(absent),
    }
