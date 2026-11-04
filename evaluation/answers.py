"""Explicit, capped Free-tier answer comparison. No automatic report grading."""

import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import httpx  # noqa: E402
from investigator.agent.contracts import validate_references  # noqa: E402
from investigator.agent.provider import GeminiProvider, ModelFailure  # noqa: E402
from qualify_gemini import local_values  # noqa: E402

QUESTIONS = [
    (
        "failure-path",
        "Describe the observed checkout failure path and distinguish it from why the downstream service became unavailable.",
        False,
    ),
    (
        "unsupported-database",
        "Do these observations establish that database connection exhaustion caused the failure? Explain what can and cannot be concluded.",
        False,
    ),
    (
        "deployment-correlation",
        "The operator suspects a deployment around the same time. Can the collected observations establish a deployment regression?",
        False,
    ),
    (
        "missing-downstream",
        "Using the supplied caller-side observations, what can be established about payment and what is missing about its underlying failure?",
        True,
    ),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-free-tier", action="store_true")
    parser.add_argument("--api", default="http://127.0.0.1:8001")
    parser.add_argument("--context", type=Path, default=ROOT / "work/knowledge-context.json")
    args = parser.parse_args()
    if not args.confirm_free_tier:
        parser.error("Explicit Free-tier confirmation is required")
    output = ROOT / "evaluation/results/answers.json"
    if output.exists():
        raise ValueError("Refusing to overwrite the answer study")
    source_path = ROOT / "docs/example-agent-investigation.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    knowledge = json.loads(args.context.read_text(encoding="utf-8"))
    values = local_values()
    provider = GeminiProvider(
        values["GEMINI_MODEL"], values["GEMINI_API_KEY"], free_tier_confirmed=True
    )
    logs = [row for row in source["evidence"] if row.get("source") == "http_log_adapter"]
    study = {
        "kind": "exploratory_fixed_evidence_answer_study",
        "source_hash": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "knowledge_revision": knowledge["revision"],
        "model": provider.identity,
        "limitations": "Selected old observations; four authored questions; same-assistant review; no diagnosis accuracy claim.",
        "calls_started": 0,
        "input_bytes": 0,
        "reported_tokens": 0,
        "results": [],
    }

    def persist():
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(study, indent=2) + "\n", encoding="utf-8")

    with httpx.Client(timeout=20, trust_env=False) as client:
        for case_id, question, omit_payment in QUESTIONS:
            for method in ("logs_only", "all_context", "v2_baseline", "development_selected"):
                evidence = [row for row in logs if not omit_payment or row["service"] == "checkout"]
                scoped = [
                    row for row in knowledge["passages"] if row["service"] in {"checkout", "global"}
                ]
                if method == "logs_only":
                    hits = []
                elif method == "all_context":
                    hits = scoped
                else:
                    response = client.post(
                        args.api + "/api/knowledge/search",
                        json={
                            "query": question,
                            "service": "checkout",
                            "revision": knowledge["revision"],
                            "profile": "baseline" if method == "v2_baseline" else "improved",
                            "limit": 6,
                        },
                    )
                    response.raise_for_status()
                    hits = response.json()["hits"]
                if hits:
                    evidence = evidence + [
                        {
                            "id": uuid.uuid5(uuid.NAMESPACE_URL, case_id + method).hex,
                            "source": "versioned_runbooks",
                            "availability": "available",
                            "revision": knowledge["revision"],
                            "hits": [
                                {
                                    key: row[key]
                                    for key in ("id", "document_id", "title", "heading", "body")
                                }
                                for row in hits
                            ],
                        }
                    ]
                context = {
                    "incident": {**source["incident"], "question": question},
                    "evidence": evidence,
                    "permitted_services": ["checkout", "payment", "inventory"],
                    "instruction": "This is a fixed-evidence comparison. Call only finish_investigation; do not request more tools.",
                }
                request = provider.request(context, 2048)
                request["tools"][0]["functionDeclarations"] = [
                    row
                    for row in request["tools"][0]["functionDeclarations"]
                    if row["name"] == "finish_investigation"
                ]
                request["toolConfig"]["functionCallingConfig"]["allowedFunctionNames"] = [
                    "finish_investigation"
                ]
                size = len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode())
                if (
                    study["calls_started"] >= 16
                    or size > 32_000
                    or study["input_bytes"] + size > 512_000
                    or study["reported_tokens"] >= 100_000
                ):
                    study["stop"] = "batch_budget"
                    persist()
                    return
                study["calls_started"] += 1
                study["input_bytes"] += size
                persist()
                row = {
                    "case": case_id,
                    "method": method,
                    "question": question,
                    "context_passages": len(hits),
                    "context_evidence": evidence,
                    "request_hash": hashlib.sha256(
                        json.dumps(request, sort_keys=True).encode()
                    ).hexdigest(),
                }
                try:
                    reply = provider.invoke(request, 30)
                    study["reported_tokens"] += reply.usage["total"]
                    row["raw_action"] = reply.decision.model_dump(mode="json")
                    row.update(usage=reply.usage, served_model_version=reply.model_version)
                    draft = reply.decision.validated()
                    validate_references(draft, evidence, {"checkout", "payment", "inventory"})
                    row.update(
                        status="structurally_valid",
                        report=draft.model_dump(mode="json"),
                        usage=reply.usage,
                    )
                except ModelFailure as exc:
                    row.update(status=exc.code, usage=exc.usage)
                    if exc.usage:
                        study["reported_tokens"] += exc.usage["total"]
                    study["results"].append(row)
                    study["stop"] = "provider_error"
                    persist()
                    print(json.dumps({"case": case_id, "method": method, "status": exc.code}))
                    return
                except ValueError:
                    row.update(status="invalid_references_or_schema")
                study["results"].append(row)
                persist()
                print(
                    json.dumps({"case": case_id, "method": method, "status": row["status"]}),
                    flush=True,
                )
                time.sleep(4)
    study["stop"] = "completed"
    persist()


if __name__ == "__main__":
    main()
