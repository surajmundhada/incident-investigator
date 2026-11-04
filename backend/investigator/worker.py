"""First slice: evidence collection, not a simulated AI diagnosis."""

import argparse
import logging
import time
from contextlib import nullcontext

from .agent.lease import keep_lease
from .agent.provider import configured_provider
from .config import Settings
from .db import make_engine, sessions_for
from .knowledge.tool import RunbookTool, configured_store
from .repository import LostLease, Repository
from .snapshots import EvidenceTools
from .tools import LogTool

logger = logging.getLogger(__name__)


def collect_report(evidence, knowledge=None):
    available = evidence["availability"] == "available"
    count = len(evidence["records"])
    report = {
        "mode": "evidence_collection_only",
        "summary": f"Collected {count} matching log records."
        if available
        else "Log source unavailable.",
        "observations": [
            {
                "text": r["message"],
                "references": [{"evidence_id": evidence["id"], "record_index": index}],
            }
            for index, r in enumerate(evidence["records"])
        ],
        "evidence_ids": [evidence["id"]],
        "hypotheses": [],
        "conclusion": "inconclusive",
        "missing_evidence": ["Follow-up investigation was not performed in evidence-only mode."],
        "suggested_checks": [],
        "runbook_references": [],
        "limitations": ["No LLM is connected. This report does not establish a root cause."]
        + (
            ["Evidence comes from a fictional test fixture, not a live application."]
            if evidence.get("data_origin") == "fixture"
            else []
        )
        + ([] if available else ["Unavailable logs must not be interpreted as no errors."])
        + (["Source response was truncated."] if evidence["truncated"] else []),
        "termination_reason": "evidence_collected" if available else "insufficient_evidence",
        "usage": {
            "model_calls": 0,
            "model_tokens": 0,
            "tool_calls_started": 1 + (knowledge is not None),
        },
    }
    if not available:
        report["missing_evidence"].append("The selected log source was unavailable.")
    elif not count:
        report["missing_evidence"].append(
            "No matching log records were returned for the selected window."
        )
    if evidence["truncated"]:
        report["missing_evidence"].append("Some log records were omitted by source limits.")
    if knowledge is not None:
        report["mode"] = "evidence_collection_with_retrieval"
        report["evidence_ids"].append(knowledge["id"])
        report["retrieved_guidance"] = [
            {**hit, "knowledge_revision": knowledge["revision"], "evidence_id": knowledge["id"]}
            for hit in knowledge.get("hits", [])
        ]
        report["knowledge_availability"] = knowledge["availability"]
        report["knowledge_revision"] = knowledge.get("revision")
        report["limitations"].append("Retrieved runbooks are guidance, not incident observations.")
        if knowledge["availability"] != "available":
            report["limitations"].append("Runbook retrieval was unavailable.")
            report["missing_evidence"].append("Runbook retrieval was unavailable.")
    return report


def run_once(repo, tool, runbooks=None, provider=None, limits=None):
    claim = repo.claim()
    if claim is None:
        return False
    try:
        with keep_lease(repo, claim) if provider is not None else nullcontext():
            _process(repo, tool, runbooks, provider, limits, claim)
    except LostLease:
        logger.warning("Job ownership changed; stale worker stopped")
    except Exception:
        logger.exception("Worker failed")
        try:
            repo.fail(claim)
        except LostLease:
            logger.warning("Failure could not be recorded because ownership changed")
    return True


def _process(repo, tool, runbooks, provider, limits, claim):
    incident = repo.investigation(claim.investigation_id)["incident"]
    # Persisted observations survive a crash between collection and final report creation.
    evidence = repo.evidence_for(claim.investigation_id, "logs.v1")
    if evidence is None:
        incident = repo.investigation(claim.investigation_id)["incident"]
        payload = tool.collect(incident)
        evidence = repo.record_evidence(claim, "logs.v1", payload)
    knowledge = repo.evidence_for(claim.investigation_id, "runbooks.v1")
    if knowledge is None and runbooks is not None:
        incident = repo.investigation(claim.investigation_id)["incident"]
        knowledge = repo.record_evidence(claim, "runbooks.v1", runbooks.collect(incident, evidence))
    if provider is None:
        report = collect_report(evidence, knowledge)
    else:
        from .agent.tools import Toolset
        from .agent.workflow import Investigator

        incident = repo.investigation(claim.investigation_id)["incident"]
        initial = [evidence] + ([knowledge] if knowledge is not None else [])
        report = Investigator(
            repo, provider, Toolset(tool, runbooks.store if runbooks else None), limits
        ).run(claim, incident, initial)
    report.update(
        application=incident["application"],
        configuration_revision=incident["configuration_revision"],
        snapshot_id=incident.get("snapshot_id"),
    )
    if evidence.get("synthetic_example"):
        report.setdefault("limitations", []).append(
            "The uploaded snapshot is labelled synthetic example data."
        )
    repo.finish(claim, report)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    engine = make_engine(settings)
    repo = Repository(sessions_for(engine), settings)
    tool = EvidenceTools(
        repo.sessions, LogTool(settings.evidence_base_url, settings.tool_timeout_seconds)
    )
    store = configured_store(engine)
    runbooks = RunbookTool(store) if store is not None else None
    provider = configured_provider()
    logging.basicConfig(level=logging.INFO)
    try:
        while True:
            worked = run_once(repo, tool, runbooks, provider)
            if args.once:
                break
            if not worked:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if store is not None:
            store.close()
        engine.dispose()


if __name__ == "__main__":
    main()
