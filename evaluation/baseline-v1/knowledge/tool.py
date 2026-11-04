import os
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from .embeddings import LocalEmbedder
from .store import KnowledgeStore, KnowledgeUnavailable, SearchRequest


def configured_store(engine):
    if os.environ.get("KNOWLEDGE_ENABLED") != "1":
        return None
    directory = os.environ.get("KNOWLEDGE_MODEL_DIR")
    if not directory:
        raise ValueError("KNOWLEDGE_MODEL_DIR must point to verified local model files")
    return KnowledgeStore(engine, LocalEmbedder(directory))


class RunbookTool:
    def __init__(self, store):
        self.store = store

    def collect(self, incident, logs):
        # Keep this deterministic and bounded; no model produces these arguments.
        snippets = [row["message"] for row in logs.get("records", []) if row["level"] == "ERROR"][
            :2
        ]
        query = " ".join([incident["title"], incident["description"], *snippets])[:500]
        request = SearchRequest(query=query, service=incident["service"])
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
