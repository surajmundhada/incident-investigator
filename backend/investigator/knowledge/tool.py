import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from investigator.catalog import DEFAULT_APPLICATION

from .cache import configured_cache
from .embeddings import LocalEmbedder
from .query import incident_query
from .reranking import LocalReranker
from .store import KnowledgeStore, KnowledgeUnavailable, SearchRequest


def configured_store(engine):
    if os.environ.get("KNOWLEDGE_ENABLED") != "1":
        return None
    directory = os.environ.get("KNOWLEDGE_MODEL_DIR")
    if not directory:
        raise ValueError("KNOWLEDGE_MODEL_DIR must point to verified local model files")
    config = json.loads(
        (Path(__file__).resolve().parents[3] / "knowledge/retrieval-config.json").read_text(
            encoding="utf-8"
        )
    )
    reranker_dir = os.environ.get("KNOWLEDGE_RERANKER_DIR")
    reranker = LocalReranker(reranker_dir) if reranker_dir else None
    return KnowledgeStore(
        engine,
        LocalEmbedder(directory),
        profile=config["profile"],
        reranker=reranker,
        cache=configured_cache(engine),
    )


class RunbookTool:
    def __init__(self, store):
        self.store = store

    def collect(self, incident, logs):
        # Keep this deterministic and bounded; no model produces these arguments.
        if getattr(self.store, "profile", "baseline") == "baseline":
            snippets = [
                row["message"] for row in logs.get("records", []) if row.get("level") == "ERROR"
            ][:2]
            query = " ".join([incident["title"], incident["description"], *snippets])[:500]
        else:
            query = incident_query(incident, logs)
        request = SearchRequest(
            application=incident.get("application", DEFAULT_APPLICATION),
            query=query,
            service=incident["service"],
            environment=incident.get("environment", "local"),
            release=incident.get("release", "demo-v1"),
        )
        try:
            result = self.store.search(request)
        except (SQLAlchemyError, KnowledgeUnavailable, ValueError, RuntimeError):
            result = {
                "availability": "unavailable",
                "source": "versioned_runbooks",
                "query": request.model_dump(),
                "hits": [],
                "error": "knowledge_unavailable",
            }
        return {**result, "collected_at": datetime.now(timezone.utc).isoformat()}
