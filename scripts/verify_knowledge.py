"""Small authored development checks; not a held-out diagnosis evaluation."""

import argparse
import json
from pathlib import Path

import httpx

CASES = [
    ("payment 503", "payment", "payment-errors"),
    ("bad gateway downstream", "checkout", "checkout-downstream"),
    ("stock check fails before charging the customer", "inventory", "inventory-errors"),
    ("request cannot reach a downstream endpoint", "checkout", "network-timeouts"),
    ("no logs were returned and the source is unavailable", "payment", "missing-evidence"),
    (
        "a release happened near the errors but could be unrelated",
        "checkout",
        "release-correlation",
    ),
]


def verify(api):
    modes = {}
    revision = None
    with httpx.Client(timeout=30, trust_env=False) as client:
        for mode in ("lexical", "semantic", "hybrid"):
            rows = []
            for query, service, expected in CASES:
                response = client.post(
                    api + "/api/knowledge/search",
                    json={"query": query, "service": service, "mode": mode, "limit": 3},
                )
                response.raise_for_status()
                result = response.json()
                if revision is not None and revision != result["revision"]:
                    raise AssertionError("Knowledge revision changed during development checks")
                revision = result["revision"]
                if result["context_tokens"] > 1200:
                    raise AssertionError("Context budget exceeded")
                if any(hit["service"] not in (service, "global") for hit in result["hits"]):
                    raise AssertionError("A service filter leaked unrelated guidance")
                returned = [hit["document_id"] for hit in result["hits"]]
                if result["hits"]:
                    citation = client.get(api + result["hits"][0]["citation_url"])
                    citation.raise_for_status()
                    if citation.json()["revision_id"] != revision:
                        raise AssertionError("Citation resolved to the wrong revision")
                rows.append(
                    {
                        "query": query,
                        "expected_document": expected,
                        "returned_documents": returned,
                        "found_at_3": expected in returned,
                    }
                )
            modes[mode] = {
                "found_at_3": sum(row["found_at_3"] for row in rows),
                "total": len(rows),
                "cases": rows,
            }
        response = client.post(
            api + "/api/knowledge/search",
            json={"query": "payment", "service": "payment", "release": "nonexistent-release"},
        )
        response.raise_for_status()
        if response.json()["hits"]:
            raise AssertionError("Release filtering leaked unrelated guidance")
    return {
        "kind": "authored_retrieval_development_checks",
        "revision": revision,
        "modes": modes,
        "limitations": "Six author-written cases on the development corpus; not held-out evidence of accuracy or improvement.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8001")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.api.rstrip("/"))
    serialized = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
