import argparse
import json
import os
from pathlib import Path

from investigator.config import Settings
from investigator.db import make_engine

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
    parser.add_argument(
        "--service", choices=["checkout", "payment", "inventory"], default="payment"
    )
    args = parser.parse_args()
    if not args.model_dir:
        parser.error("Supply --model-dir or KNOWLEDGE_MODEL_DIR")
    engine = make_engine(Settings.from_env())
    try:
        store = KnowledgeStore(engine, LocalEmbedder(args.model_dir))
        result = (
            store.ingest(args.root)
            if args.action == "ingest"
            else store.search(SearchRequest(query=args.query, service=args.service))
        )
        print(json.dumps(result, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
