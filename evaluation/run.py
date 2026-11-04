"""Operator-only local retrieval study; no model API key or generative calls."""

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from investigator.knowledge.embeddings import LocalEmbedder
from investigator.knowledge.metrics import measure, summarize
from investigator.knowledge.reranking import LocalReranker
from investigator.knowledge.store import KnowledgeStore, SearchRequest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

HERE = Path(__file__).resolve().parent
ROOT = Path.cwd()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs():
    for base, lock in (
        (HERE, HERE / "data-lock.json"),
        (HERE / "baseline-v1", HERE / "baseline-v1/snapshot.json"),
    ):
        values = json.loads(lock.read_text(encoding="utf-8"))
        for name, expected in values.get("files", values).items():
            if sha(base / name) != expected:
                raise ValueError("Frozen study input changed: " + name)


def implementation_hashes():
    paths = sorted((ROOT / "backend/investigator/knowledge").glob("*.py"))
    paths += [
        ROOT / "knowledge/embedding-lock.json",
        ROOT / "knowledge/reranker-lock.json",
        HERE / "run.py",
        HERE / "STUDY.md",
    ]
    return {
        str(path.relative_to(ROOT))
        if path.is_relative_to(ROOT)
        else "evaluation/" + path.name: sha(path)
        for path in paths
    }


def make_schema(admin, url, name):
    with admin.begin() as db:
        db.execute(CreateSchema(name))
    scoped = url.update_query_dict({"options": f"-csearch_path={name},public"})
    os.environ["DATABASE_URL"] = scoped.render_as_string(hide_password=False)
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    return create_engine(scoped, pool_pre_ping=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["development", "heldout"])
    parser.add_argument("--model-dir", default="/models/minilm")
    parser.add_argument("--reranker-dir", default="/models/reranker")
    args = parser.parse_args()
    verify_inputs()
    results_dir = HERE / "results"
    results_dir.mkdir(exist_ok=True)
    selection_path = results_dir / "selection-lock.json"
    result_path = results_dir / (args.phase + ".json")
    if result_path.exists():
        raise ValueError("Refusing to overwrite a recorded study phase")
    hashes = implementation_hashes()
    if args.phase == "heldout":
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        if selection["implementation_hashes"] != hashes or selection["data_lock_hash"] != sha(
            HERE / "data-lock.json"
        ):
            raise ValueError("Implementation or dataset changed after selection was frozen")
    cases = json.loads((HERE / "data" / (args.phase + ".json")).read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location(
        "frozen_knowledge",
        HERE / "baseline-v1/knowledge/__init__.py",
        submodule_search_locations=[str(HERE / "baseline-v1/knowledge")],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["frozen_knowledge"] = module
    spec.loader.exec_module(module)
    from frozen_knowledge.store import KnowledgeStore as FrozenStore
    from frozen_knowledge.store import SearchRequest as FrozenRequest

    url = make_url(os.environ["DATABASE_URL"])
    if url.get_backend_name() != "postgresql":
        raise ValueError("The study requires the local PostgreSQL/pgvector stack")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = "investigator_rag_study"
    with admin.connect() as db:
        if not db.scalar(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}):
            db.execute(text("CREATE DATABASE investigator_rag_study"))
    admin.dispose()
    url = url.set(database=name)
    admin = create_engine(url)
    schema_names, engines = [], []
    try:
        embedder = LocalEmbedder(args.model_dir)
        reranker = LocalReranker(args.reranker_dir)
        stores = []
        for prefix, store_class in (("legacy", FrozenStore), ("candidate", KnowledgeStore)):
            schema = "rag_" + prefix + "_" + uuid.uuid4().hex
            schema_names.append(schema)
            engine = make_schema(admin, url, schema)
            engines.append(engine)
            store = store_class(engine, embedder)
            stores.append(store)
            store.ingest(HERE / "data/corpus")
        legacy, candidate = stores
        candidate.reranker = reranker
        variants = {
            "frozen_lexical": (legacy, FrozenRequest, "lexical", None),
            "frozen_semantic": (legacy, FrozenRequest, "semantic", None),
            "frozen_hybrid": (legacy, FrozenRequest, "hybrid", None),
            "v2_baseline": (candidate, SearchRequest, "hybrid", "baseline"),
            "query": (candidate, SearchRequest, "hybrid", "query"),
            "improved": (candidate, SearchRequest, "hybrid", "improved"),
            "rerank": (candidate, SearchRequest, "hybrid", "rerank"),
        }
        report = {
            "phase": args.phase,
            "data_lock_hash": sha(HERE / "data-lock.json"),
            "implementation_hashes": hashes,
            "embedding_id": embedder.identity,
            "reranker_id": reranker.identity,
            "generative_calls": 0,
            "variants": {},
            "all_context": [],
        }
        for variant, (store, request_class, mode, profile) in variants.items():
            rows = []
            for case in cases:
                arguments = {
                    key: case[key] for key in ("query", "service", "environment", "release")
                }
                arguments.update(mode=mode, limit=5)
                if profile:
                    arguments["profile"] = profile
                request = request_class(**arguments)
                if not rows:
                    store.search(
                        request
                    )  # warm-up; exclude model construction/JIT from warm latency
                timings = []
                for _ in range(2):
                    started = time.perf_counter()
                    result = store.search(request)
                    timings.append((time.perf_counter() - started) * 1000)
                hits = result["hits"]
                rows.append(
                    {
                        "id": case["id"],
                        "query": case["query"],
                        "relevant": case["relevant"],
                        "metrics": measure(hits, case["relevant"]),
                        "latencies_ms": timings,
                        "revision": result["revision"],
                        "hits": [
                            {
                                key: hit[key]
                                for key in ("id", "document_id", "heading", "rerank_score")
                                if key in hit
                            }
                            for hit in hits
                        ],
                    }
                )
            summary = summarize(rows)
            report["variants"][variant] = {"summary": summary, "cases": rows}
            print(json.dumps({"phase": args.phase, "variant": variant, **summary}), flush=True)
        with engines[1].connect() as db:
            for case in cases:
                rows = (
                    db.execute(
                        text("""SELECT document_id, heading, token_count FROM knowledge_chunks
                    WHERE environment=:environment AND release=:release AND service IN (:service,'global')"""),
                        case,
                    )
                    .mappings()
                    .all()
                )
                units = {(row["document_id"], row["heading"]) for row in rows}
                expected = {(row["document"], row["heading"]) for row in case["relevant"]}
                report["all_context"].append(
                    {
                        "id": case["id"],
                        "passages": len(rows),
                        "context_tokens": sum(row["token_count"] for row in rows),
                        "available_relevance_coverage": len(units & expected) / len(expected)
                        if expected
                        else None,
                    }
                )
        if args.phase == "development":
            base = report["variants"]["frozen_hybrid"]["summary"]
            choices = [("baseline", base)]
            for profile in ("query", "improved", "rerank"):
                value = report["variants"][profile]["summary"]
                if value["recall_at_5"] >= base["recall_at_5"] and value["p95_ms"] < 2000:
                    choices.append((profile, value))
            selected, metrics = max(
                choices,
                key=lambda pair: (
                    (pair[1]["recall_at_5"] + pair[1]["no_answer_abstention"]) / 2,
                    pair[1]["mrr_at_5"],
                    -pair[1]["p95_ms"],
                ),
            )
            selection = {
                "selected_profile": selected,
                "development_metrics": metrics,
                "implementation_hashes": hashes,
                "data_lock_hash": sha(HERE / "data-lock.json"),
            }
            selection_path.write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
            report["selected_profile"] = selected
        else:
            report["selected_profile"] = selection["selected_profile"]
        result_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    finally:
        for engine in engines:
            engine.dispose()
        with admin.begin() as db:
            for schema in schema_names:
                db.execute(DropSchema(schema, cascade=True))
        admin.dispose()


if __name__ == "__main__":
    main()
