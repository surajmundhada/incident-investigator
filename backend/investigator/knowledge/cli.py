import argparse
import json
import os
from pathlib import Path

from investigator.config import Settings
from investigator.db import make_engine

from .cache import configured_cache
from .embeddings import LocalEmbedder
from .store import KnowledgeStore, SearchRequest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["ingest", "search"])
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[3] / "knowledge"
    )
    parser.add_argument("--model-dir", default=os.environ.get("KNOWLEDGE_MODEL_DIR"))
    parser.add_argument("--query", default="payment 503")
    parser.add_argument("--service", default="payment")
    parser.add_argument("--application", default="shopping-demo")
    args = parser.parse_args()
    if not args.model_dir:
        parser.error("Supply --model-dir or KNOWLEDGE_MODEL_DIR")
    engine = make_engine(Settings.from_env())
    store = None
    try:
        store = KnowledgeStore(
            engine, LocalEmbedder(args.model_dir), cache=configured_cache(engine)
        )
        result = (
            store.ingest(args.root)
            if args.action == "ingest"
            else store.search(
                SearchRequest(query=args.query, service=args.service, application=args.application)
            )
        )
        print(json.dumps(result, indent=2))
    finally:
        if store is not None:
            store.close()
        engine.dispose()


if __name__ == "__main__":
    main()
