"""Capped production-code replay; labels never enter model context. See WORKFLOW_PROTOCOL.md."""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "scripts"), str(Path(__file__).parent)]

import httpx  # noqa: E402
from investigator.agent.contracts import Limits  # noqa: E402
from investigator.agent.provider import GeminiProvider, ModelFailure  # noqa: E402
from investigator.catalog import DEMO_CONFIGURATION  # noqa: E402
from investigator.config import Settings  # noqa: E402
from investigator.db import Base, make_engine, sessions_for  # noqa: E402
from investigator.knowledge.store import KnowledgeUnavailable  # noqa: E402
from investigator.knowledge.tool import RunbookTool  # noqa: E402
from investigator.registry import Registry  # noqa: E402
from investigator.repository import Repository  # noqa: E402
from investigator.schemas import IncidentCreate  # noqa: E402
from investigator.snapshots import EvidenceTools, SnapshotCreate, SnapshotStore  # noqa: E402
from investigator.worker import run_once  # noqa: E402
from pilot import prepare  # noqa: E402
from qualify_gemini import local_values  # noqa: E402

HERE = Path(__file__).parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RemoteKnowledge:
    profile = "baseline"

    def __init__(self, revision, unavailable=False):
        self.revision, self.unavailable = revision, unavailable

    def search(self, request):
        if self.unavailable:
            raise KnowledgeUnavailable("Guidance unavailable in this recorded ablation")
        if request.revision not in {None, self.revision}:
            raise KnowledgeUnavailable("Replay knowledge revision mismatch")
        payload = request.model_dump()
        payload.update(revision=self.revision, profile="baseline")
        with httpx.Client(base_url="http://127.0.0.1:8001", timeout=20, trust_env=False) as client:
            response = client.post("/api/knowledge/search", json=payload)
            if response.status_code != 200:
                raise KnowledgeUnavailable("Replay retrieval unavailable")
            result = response.json()
        if result.get("revision") != self.revision:
            raise KnowledgeUnavailable("Replay returned another revision")
        return result


class NoLiveFallback:
    def collect(self, incident):
        raise RuntimeError("A recorded replay cannot fall through to live evidence")


class BudgetProvider:
    def __init__(self, base, study, row, persist, one_shot, cap):
        self.base, self.study, self.row, self.persist = base, study, row, persist
        self.identity, self.origin = base.identity, base.origin
        self.one_shot, self.cap = one_shot, cap

    def request(self, context, output_tokens):
        request = self.base.request(context, output_tokens)
        if self.one_shot:
            request["tools"][0]["functionDeclarations"] = [
                value
                for value in request["tools"][0]["functionDeclarations"]
                if value["name"] == "finish_investigation"
            ]
            request["toolConfig"]["functionCallingConfig"]["allowedFunctionNames"] = [
                "finish_investigation"
            ]
        return request

    def invoke(self, request, remaining_seconds):
        size = len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode())
        if (
            self.study["calls_started"] >= self.cap
            or self.study["input_bytes"] + size > self.cap * 32000
            or self.study["reported_tokens"] >= (150000 if self.cap == 20 else 700000)
        ):
            self.study["stop"] = "batch_budget"
            self.persist()
            raise ModelFailure("batch_budget")
        delay = max(0, 4 - (time.time() - self.study.get("last_call_started", 0)))
        if delay:
            time.sleep(delay)
        trace = {
            "outcome": "reserved_unknown",
            "request_sha256": hashlib.sha256(
                json.dumps(request, sort_keys=True).encode()
            ).hexdigest(),
            "context": json.loads(request["contents"][0]["parts"][0]["text"]),
        }
        self.row["traces"].append(trace)
        self.study["calls_started"] += 1
        self.study["input_bytes"] += size
        self.study["last_call_started"] = time.time()
        self.persist()
        try:
            reply = self.base.invoke(request, max(0.1, remaining_seconds - delay))
        except ModelFailure as exc:
            trace.update(outcome=exc.code, usage=exc.usage)
            if exc.usage:
                self.study["reported_tokens"] += exc.usage["total"]
            self.study["stop"] = "provider_error"
            self.persist()
            raise
        self.study["reported_tokens"] += reply.usage["total"]
        trace.update(
            outcome="returned",
            decision=reply.decision.model_dump(mode="json"),
            usage=reply.usage,
            model_version=reply.model_version,
        )
        self.persist()
        return reply


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["development", "heldout"])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-free-tier", action="store_true")
    args = parser.parse_args()
    prepare()  # Verify original capture/split hashes, without modifying pilot results.
    labels = json.loads((HERE / "captures/labels.operator.json").read_text())
    selected = [row for row in labels if row["split"] == args.phase]
    if args.phase == "development":
        selected = selected[4:]
    episodes = [(row, method) for row in selected for method in ("logs_only", "rag", "agent")]
    if args.phase == "heldout":
        for family, method in (
            ("unavailable", "agent_missing_payment"),
            ("slow", "agent_missing_payment"),
            ("unavailable", "agent_no_guidance"),
            ("application_error", "agent_no_guidance"),
        ):
            episodes.append((next(row for row in selected if row["family"] == family), method))
    if not args.execute:
        print(json.dumps({"phase": args.phase, "episodes": len(episodes), "actual_model_calls": 0}))
        return
    if not args.confirm_free_tier:
        parser.error("Explicit Free-tier confirmation required")
    output_dir = HERE / "results" / ("workflow-" + args.phase)
    output_dir.mkdir(exist_ok=False)
    values = local_values()
    if values.get("GEMINI_FREE_TIER_CONFIRMED") != "1":
        raise ValueError("Configured project is not confirmed Free tier")
    base = GeminiProvider(
        values["GEMINI_MODEL"], values["GEMINI_API_KEY"], free_tier_confirmed=True
    )
    revision = json.loads((HERE / "knowledge.json").read_text())["revision"]
    source_paths = [
        HERE / "WORKFLOW_PROTOCOL.md",
        HERE / "workflow.py",
        HERE / "captures/capture-lock.json",
        HERE / "knowledge.json",
    ]
    source_paths += sorted((ROOT / "backend/investigator").glob("*.py"))
    source_paths += sorted((ROOT / "backend/investigator/agent").glob("*.py"))
    source_paths += sorted((ROOT / "backend/investigator/knowledge").glob("*.py"))
    study = {
        "phase": args.phase,
        "kind": "production_workflow_replay_v1",
        "model": base.identity,
        "knowledge_revision": revision,
        "sources": {str(p.relative_to(ROOT)): sha(p) for p in source_paths},
        "calls_started": 0,
        "input_bytes": 0,
        "reported_tokens": 0,
        "rows": [],
    }

    def persist():
        target = output_dir / "results.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(study, indent=2), encoding="utf-8")
        temp.replace(target)

    persist()  # Source/protocol lock precedes any provider start.
    settings = Settings(
        "sqlite:///" + str(output_dir / "replay.sqlite3"), allow_sqlite_preview=True
    )
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    sessions = sessions_for(engine)
    Registry(sessions).ensure_demo()
    repo, snapshots = Repository(sessions, settings), SnapshotStore(sessions)
    logs = EvidenceTools(sessions, NoLiveFallback())
    try:
        for label, method in episodes:
            captured = json.loads((HERE / "captures" / (label["case_id"] + ".json")).read_text())
            if method == "agent_missing_payment":
                captured["covered_services"].remove("payment")
                captured["records"] = [
                    record for record in captured["records"] if record["service"] != "payment"
                ]
            snapshot = snapshots.create(
                SnapshotCreate(**captured, configuration_revision=DEMO_CONFIGURATION.revision)
            )
            admitted = repo.admit(
                IncidentCreate(
                    application="shopping-demo",
                    service="checkout",
                    configuration_revision=DEMO_CONFIGURATION.revision,
                    snapshot_id=snapshot["id"],
                    title="Recorded checkout behavior",
                    description="Investigate the captured checkout behavior. Distinguish observations from underlying causes and state missing evidence.",
                    starts_at=captured["starts_at"],
                    ends_at=captured["ends_at"],
                ),
                label["case_id"] + ":" + method,
            )
            row = {
                "case_id": label["case_id"],
                "method": method,
                "investigation_id": admitted["investigation_id"],
                "traces": [],
            }
            study["rows"].append(row)
            persist()
            knowledge = RemoteKnowledge(revision, unavailable=method == "agent_no_guidance")
            runbooks = None if method == "logs_only" else RunbookTool(knowledge)
            active = method.startswith("agent")
            provider = BudgetProvider(
                base, study, row, persist, not active, 20 if args.phase == "development" else 92
            )
            started = time.perf_counter()
            run_once(
                repo,
                logs,
                runbooks,
                provider,
                Limits(model_calls=3 if active else 1, tool_calls=6, total_request_bytes=96000),
            )
            row.update(
                saved=repo.investigation(admitted["investigation_id"]),
                elapsed_seconds=time.perf_counter() - started,
            )
            persist()
            print(
                json.dumps(
                    {
                        "phase": args.phase,
                        "episodes": len(study["rows"]),
                        "method": method,
                        "termination": row["saved"].get("report", {}).get("termination_reason"),
                        "calls": study["calls_started"],
                    }
                ),
                flush=True,
            )
            if study.get("stop"):
                return
        study["stop"] = "completed"
        persist()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
