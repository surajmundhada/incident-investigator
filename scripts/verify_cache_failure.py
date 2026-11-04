"""Operator-controlled real Redis stop/restart probe over the main immutable runbooks.

Never creates an incident, modifies a knowledge head or calls a hosted model.
Run `warm`, stop Redis externally, run `down`, restart Redis, then run `restarted`.
"""

import argparse
import json
import os
import time

from investigator.config import Settings
from investigator.db import make_engine
from investigator.knowledge.cache import configured_cache
from investigator.knowledge.embeddings import LocalEmbedder
from investigator.knowledge.store import KnowledgeStore, SearchRequest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["warm", "down", "restarted"])
    args = parser.parse_args()
    engine = make_engine(Settings.from_env())
    cache = configured_cache(engine)
    if cache is None:
        raise ValueError("Enable the optional cache explicitly")
    store = KnowledgeStore(engine, LocalEmbedder(os.environ["KNOWLEDGE_MODEL_DIR"]), cache=cache)
    try:
        request = SearchRequest(query="payment unavailable checkout errors", service="checkout")
        first = store.search(request)
        second = store.search(request)
        assert first == second and first["availability"] == "available"
        metrics = store.metrics.snapshot()
        if args.phase == "down":
            assert metrics.get("errors") == 1 and metrics.get("bypass", 0) >= 1
            assert metrics["ranking_executions"] == 2
        else:
            assert metrics.get("retrieval_hits", 0) >= 1 and metrics.get("errors", 0) == 0
        if args.phase == "restarted":
            assert metrics["retrieval_misses"] == 1  # No persisted cache after restart.
        print(
            json.dumps(
                {
                    "phase": args.phase,
                    "revision": first["revision"],
                    "equal_results": True,
                    "model_calls": 0,
                    "metrics": metrics,
                    "checked_at": time.time(),
                }
            )
        )
    finally:
        store.close()
        engine.dispose()


if __name__ == "__main__":
    main()
