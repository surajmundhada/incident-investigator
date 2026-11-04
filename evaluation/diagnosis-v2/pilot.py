"""Explicit capped fresh development pilot; no held-out calls or automatic retries."""

import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "scripts")]

import httpx  # noqa: E402
from investigator.agent.contracts import validate_references  # noqa: E402
from investigator.agent.provider import GeminiProvider, ModelFailure  # noqa: E402
from investigator.catalog import DEMO_CONFIGURATION  # noqa: E402
from qualify_gemini import local_values  # noqa: E402

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    lock = json.loads((HERE / "captures/capture-lock.json").read_text())
    for name, expected in lock["files"].items():
        if digest(HERE / "captures" / name) != expected:
            raise ValueError("Frozen capture changed")
    label_path = HERE / "captures/labels.operator.json"
    if digest(label_path) != lock["labels_sha256"]:
        raise ValueError("Frozen split/labels changed")
    labels = json.loads(label_path.read_text())
    cases = [row["case_id"] for row in labels if row["split"] == "development"][:4]
    if len(cases) != 4:
        raise ValueError("Expected four development pilot cases")
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-free-tier", action="store_true")
    args = parser.parse_args()
    cases = prepare()
    if not args.execute:
        print(
            json.dumps(
                {
                    "captures_verified": 24,
                    "development_pilot_cases": len(cases),
                    "max_provider_starts": 12,
                    "actual_provider_starts": 0,
                }
            )
        )
        return
    if not args.confirm_free_tier:
        parser.error("Explicit Free-tier confirmation required")
    output = HERE / "results/development-pilot.json"
    if output.exists():
        raise ValueError("Refusing to overwrite or repeat this recorded pilot")
    values = local_values()
    if values.get("GEMINI_FREE_TIER_CONFIRMED") != "1":
        raise ValueError("Local Free-tier confirmation is not enabled")
    provider = GeminiProvider(
        values["GEMINI_MODEL"], values["GEMINI_API_KEY"], free_tier_confirmed=True
    )
    knowledge_path = HERE / "knowledge.json"
    knowledge = json.loads(knowledge_path.read_text())
    sources = [
        HERE / "PROTOCOL.md",
        HERE / "pilot.py",
        HERE / "captures/capture-lock.json",
        knowledge_path,
        *sorted((ROOT / "backend/investigator/agent").glob("*.py")),
    ]
    study = {
        "kind": "fresh_fixed_evidence_development_pilot_v1",
        "model": provider.identity,
        "knowledge_revision": knowledge["revision"],
        "sources": {str(p.relative_to(ROOT)): digest(p) for p in sources},
        "calls_started": 0,
        "input_bytes": 0,
        "reported_tokens": 0,
        "rows": [],
        "heldout_calls": 0,
        "independent_production_benchmark": False,
    }

    def persist():
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(study, indent=2), encoding="utf-8")
        temporary.replace(output)

    persist()
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=20, trust_env=False) as client:
        for case in cases:
            captured = json.loads((HERE / "captures" / (case + ".json")).read_text())
            logs = [
                {
                    "id": uuid.uuid5(uuid.NAMESPACE_URL, case + service).hex,
                    "source": "snapshot_log_adapter",
                    "service": service,
                    "availability": "available",
                    "records": [row for row in captured["records"] if row["service"] == service],
                    "data_origin": "captured",
                    "synthetic_example": True,
                }
                for service in ("checkout", "payment", "inventory")
            ]
            incident = {
                "service": "checkout",
                "application": "shopping-demo",
                "environment": "local",
                "release": "demo-v1",
                "configuration_revision": DEMO_CONFIGURATION.revision,
                "application_config": DEMO_CONFIGURATION.canonical(),
                "starts_at": captured["starts_at"],
                "ends_at": captured["ends_at"],
                "title": "Checkout behavior investigation",
                "description": "Explain observed behavior in this fixed window, distinguish failure propagation from underlying cause, and state missing evidence.",
            }
            query = "checkout " + " ".join(row["message"] for row in logs[0]["records"][:3])
            for method in ("logs_only", "all_context", "baseline_rag"):
                row = {"case_id": case, "method": method, "status": "not_started"}
                study["rows"].append(row)
                try:
                    if method == "logs_only":
                        hits = []
                    elif method == "all_context":
                        hits = [
                            p
                            for p in knowledge["passages"]
                            if p["service"] in {"checkout", "global"}
                        ]
                    else:
                        response = client.post(
                            "/api/knowledge/search",
                            json={
                                "query": query[:500],
                                "service": "checkout",
                                "application": "shopping-demo",
                                "environment": "local",
                                "release": "demo-v1",
                                "revision": knowledge["revision"],
                                "profile": "baseline",
                                "limit": 6,
                            },
                        )
                        response.raise_for_status()
                        hits = response.json()["hits"]
                    evidence = logs + (
                        [
                            {
                                "id": uuid.uuid5(uuid.NAMESPACE_URL, case + "guidance").hex,
                                "source": "versioned_runbooks",
                                "availability": "available",
                                "revision": knowledge["revision"],
                                "hits": [
                                    {
                                        k: p[k]
                                        for k in ("id", "document_id", "title", "heading", "body")
                                    }
                                    for p in hits
                                ],
                            }
                        ]
                        if hits
                        else []
                    )
                    request = provider.request(
                        {
                            "incident": incident,
                            "evidence": evidence,
                            "permitted_services": ["checkout", "payment", "inventory"],
                            "instruction": "Fixed-evidence comparison. Use only finish_investigation; no additional source is available.",
                        },
                        2048,
                    )
                    request["tools"][0]["functionDeclarations"] = [
                        d
                        for d in request["tools"][0]["functionDeclarations"]
                        if d["name"] == "finish_investigation"
                    ]
                    request["toolConfig"]["functionCallingConfig"]["allowedFunctionNames"] = [
                        "finish_investigation"
                    ]
                    size = len(
                        json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
                    )
                    if (
                        study["calls_started"] >= 12
                        or size > 32000
                        or study["input_bytes"] + size > 384000
                        or study["reported_tokens"] >= 100000
                    ):
                        row["status"], study["stop"] = "budget_not_started", "batch_budget"
                        persist()
                        return
                    study["calls_started"] += 1
                    study["input_bytes"] += size
                    row.update(
                        status="started_outcome_unknown",
                        request_sha256=hashlib.sha256(
                            json.dumps(request, sort_keys=True).encode()
                        ).hexdigest(),
                        context_evidence=evidence,
                    )
                    persist()  # Never repeat a call whose outcome is unknown.
                    started = time.monotonic()
                    reply = provider.invoke(request, 30)
                    study["reported_tokens"] += reply.usage["total"]
                    row.update(
                        raw_action=reply.decision.model_dump(mode="json"),
                        usage=reply.usage,
                        served_model_version=reply.model_version,
                        elapsed_seconds=time.monotonic() - started,
                    )
                    if reply.decision.name != "finish_investigation":
                        raise ValueError("Unexpected action")
                    draft = reply.decision.validated()
                    validate_references(draft, evidence, {"checkout", "payment", "inventory"})
                    row.update(status="structurally_valid", report=draft.model_dump(mode="json"))
                except ModelFailure as exc:
                    row.update(status=exc.code, usage=exc.usage)
                    if exc.usage:
                        study["reported_tokens"] += exc.usage["total"]
                    study["stop"] = "provider_error"
                    persist()
                    print(json.dumps({"status": exc.code, "calls_started": study["calls_started"]}))
                    return
                except ValueError:
                    row["status"] = "invalid_schema_or_references"
                except httpx.HTTPError:
                    row["status"], study["stop"] = "local_retrieval_unavailable", "retrieval_error"
                    persist()
                    return
                persist()
                print(
                    json.dumps(
                        {
                            "method": method,
                            "status": row["status"],
                            "calls_started": study["calls_started"],
                        }
                    ),
                    flush=True,
                )
                time.sleep(4)
    study["stop"] = "completed"
    persist()


if __name__ == "__main__":
    main()
