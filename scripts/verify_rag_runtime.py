"""Read-only HTTP verification after a RAG rollout; no generative requests."""

import json
from collections import Counter
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
example = json.loads((root / "docs/example-agent-investigation.json").read_text(encoding="utf-8"))
old = next(row for row in example["evidence"] if row.get("source") == "versioned_runbooks")
base = "http://127.0.0.1:8001"
with httpx.Client(timeout=15, trust_env=False) as client:
    for path in ("/healthz", "/readyz", "/docs"):
        client.get(base + path).raise_for_status()

    def search(**extra):
        response = client.post(
            base + "/api/knowledge/search",
            json={"query": "payment 503", "service": "payment", **extra},
        )
        response.raise_for_status()
        return response.json()

    active = search()
    assert active["ranking_profile"] == "baseline"
    assert active["revision"] != old["revision"]
    pinned = search(revision=old["revision"])
    assert pinned["revision"] == old["revision"] and pinned["hits"]
    passage = client.get(base + "/api/knowledge/passages/" + old["hits"][0]["id"])
    passage.raise_for_status()
    assert passage.json()["revision_id"] == old["revision"]
    candidate = search(profile="improved")
    assert candidate["ranking_profile"] == "improved"
    assert all(hit["service"] in {"payment", "global"} for hit in candidate["hits"])
    assert all(
        count <= 2 for count in Counter(hit["document_id"] for hit in candidate["hits"]).values()
    )
    assert not search(environment="production")["hits"]
    assert not search(release="unknown-version")["hits"]
    schema = client.get(base + "/openapi.json").json()["components"]["schemas"]["IncidentCreate"]
    assert {"environment", "release"}.issubset(schema["properties"])
result = {
    "status": "passed",
    "active_revision": active["revision"],
    "old_revision_still_resolves": old["revision"],
    "default_profile": active["ranking_profile"],
    "generative_calls": 0,
    "checks": [
        "health",
        "ready",
        "docs",
        "scope schema",
        "pinned revision",
        "old citation",
        "candidate diversity",
        "environment filter",
        "release filter",
    ],
}
(root / "work/rag-runtime-verification.json").write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(result))
