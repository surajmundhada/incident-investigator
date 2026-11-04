"""One-time authored fixture creation; never run to overwrite frozen study data."""

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent

DOCS = {
    "http-validation": (
        "checkout",
        "Cart validation and HTTP client errors",
        [
            (
                "Invalid carts",
                "The checkout schema accepts the book item and quantities from one through ten. A missing or invalid field, zero quantity, or quantity eleven is rejected with HTTP 422 before business processing. Extra fields are forbidden. Invalid input is not evidence of a failing dependency.",
            ),
            (
                "Client errors versus dependency failures",
                "HTTP 422 describes invalid cart input. HTTP 502 describes checkout failing to complete a downstream call. Compare the response, dependency field, and correlated logs. Do not attribute a rejected cart to payment or inventory without observations of those services.",
            ),
        ],
    ),
    "request-correlation": (
        "global",
        "Request ID correlation across HTTP services",
        [
            (
                "Joining observations",
                "Use request_id to join checkout, inventory, and payment logs in the same observation window. Accepted IDs contain exactly 32 lowercase hexadecimal characters. Invalid supplied IDs are replaced at ingress. Timestamp proximity alone does not establish that two errors belong to the same request.",
            ),
            (
                "Partial correlation",
                "A matching request ID supports following a dependency boundary. A missing match can arise from log retention, an incorrect time window, a transport failure, or a request that never reached the downstream service. Preserve missing evidence; do not invent a trace or assume downstream success.",
            ),
        ],
    ),
    "source-failures": (
        "global",
        "Operational log adapter availability",
        [
            (
                "Adapter failure outcomes",
                "source_timeout, source_unreachable, source_http_error, and invalid_source_response mean logs are unavailable. These adapter errors do not prove target application failure or target health. A successful empty query is a different outcome. Preserve the source error, query scope, and truncation status.",
            ),
            (
                "Bounded evidence reads",
                "The adapter permits a fixed configured source URL, a service allowlist, ordered incident windows no longer than an hour, at most 100 returned records, and a response-size cap. It does not accept arbitrary SQL, shell commands, or user-selected destinations.",
            ),
        ],
    ),
    "health-semantics": (
        "global",
        "Process liveness versus business availability",
        [
            (
                "A reachable process can reject work",
                "A successful health endpoint establishes that the service process responded. It does not establish that payment charge requests or inventory business requests succeeded. Compare business request status and correlated caller logs before claiming recovery or availability.",
            ),
            (
                "Observed recovery",
                "A later business request returning HTTP 200 demonstrates recovery for that request at that time. It does not prove service health during an earlier incident or reveal why the earlier request failed. Avoid extending one observation into a continuous availability claim.",
            ),
        ],
    ),
    "retry-safety": (
        "global",
        "Read-only investigation and transaction retry safety",
        [
            (
                "No automatic transaction retries",
                "Checkout does not automatically retry inventory or payment transactions. The investigator's tools only read observations and reviewed guidance. Suggested verification steps must not become automatic restarts, configuration changes, repeated charges, or shell execution.",
            ),
            (
                "Guidance is not evidence",
                "A procedure describes what an operator might verify. It does not establish that its described failure is happening now. Link current observations to each hypothesis, acknowledge contradictory evidence, and leave the underlying cause inconclusive when available signals cannot distinguish alternatives.",
            ),
        ],
    ),
    "configuration-scope": (
        "global",
        "Applicability of versioned operational guidance",
        [
            (
                "Environment and release",
                "Choose guidance for the incident environment and release, retaining applicable global guidance. A staging or archived release procedure can describe different dependencies. Similar words do not override applicability metadata.",
            ),
            (
                "Revision reproducibility",
                "Preserve the knowledge revision and immutable passage references used by an investigation. Publishing a new index must not rewrite old citations or silently change follow-up retrieval in an ongoing investigation. A failed publication leaves the previous corpus usable.",
            ),
        ],
    ),
}


def case(case_id, family, query, service, relevant, **scope):
    return {
        "id": case_id,
        "family": family,
        "query": query,
        "service": service,
        "environment": scope.get("environment", "local"),
        "release": scope.get("release", "demo-v1"),
        "relevant": [{"document": doc, "heading": heading} for doc, heading in relevant],
    }


DEV = [
    case(
        "d01",
        "gateway-status",
        "checkout 502 payment downstream failure",
        "checkout",
        [("checkout-downstream", "HTTP 502 from checkout")],
    ),
    case(
        "d02",
        "payment-response",
        "What does payment HTTP 503 establish about the failed request?",
        "payment",
        [("payment-errors", "Payment HTTP 503")],
    ),
    case(
        "d03",
        "call-order",
        "Inventory failed so was payment supposed to receive that checkout request?",
        "inventory",
        [("inventory-errors", "Inventory is checked before payment")],
    ),
    case(
        "d04",
        "transport-types",
        "A downstream request unavailable log has no HTTP response status. Could it be DNS or a refused connection?",
        "checkout",
        [("network-timeouts", "Response failure versus transport failure")],
    ),
    case(
        "d05",
        "id-format",
        "How can I join observations by request_id and what format is accepted?",
        "checkout",
        [("request-correlation", "Joining observations")],
    ),
    case(
        "d06",
        "verbose-gateway",
        "Please help me understand why checkout is returning bad gateway errors when calling a dependency",
        "checkout",
        [("checkout-downstream", "HTTP 502 from checkout")],
    ),
    case(
        "d07",
        "impact-comparison",
        "Some payment calls returned 503 but others succeeded. How should I assess impact?",
        "payment",
        [("payment-errors", "Check impact and recovery")],
    ),
    case(
        "d08",
        "adapter-outcome",
        "source_timeout means the application was healthy because no logs came back right?",
        "payment",
        [("source-failures", "Adapter failure outcomes")],
    ),
    case(
        "d09",
        "response-versus-connectivity",
        "How does a received downstream 503 differ from a connection that could not complete?",
        "checkout",
        [("network-timeouts", "Response failure versus transport failure")],
    ),
    case(
        "d10",
        "cart-range",
        "quantity zero gets 422 before checkout finishes, which component validates this?",
        "checkout",
        [("http-validation", "Invalid carts")],
    ),
    case(
        "d11",
        "cart-boundary",
        "Can the book cart contain eleven units or extra JSON fields?",
        "checkout",
        [("http-validation", "Invalid carts")],
    ),
    case(
        "d12",
        "inventory-counterevidence",
        "Inventory succeeded for the same request but payment failed. Is inventory the cause?",
        "inventory",
        [("inventory-errors", "Compare inventory observations")],
    ),
    case(
        "d13",
        "missing-request-match",
        "Why could a correlated request be missing from the downstream logs?",
        "payment",
        [("request-correlation", "Partial correlation")],
    ),
    case(
        "d14",
        "timeout-interpretation",
        "Does the configured one second client timeout prove every unavailable request timed out?",
        "checkout",
        [("network-timeouts", "Bounded requests")],
    ),
    case(
        "d15",
        "read-authority",
        "May a log query choose a URL or execute SQL to find extra records?",
        "checkout",
        [("source-failures", "Bounded evidence reads")],
    ),
    case(
        "d16",
        "coupon-absence",
        "What precedence rules combine stacked promotional coupons with tax-inclusive pricing?",
        "checkout",
        [],
    ),
    case(
        "d17",
        "settlement-absence",
        "Describe the bank settlement file schema and merchant reconciliation schedule",
        "payment",
        [],
    ),
    case(
        "d18",
        "warehouse-absence",
        "Which warehouse replenishment policy assigns stock to regional fulfillment zones?",
        "inventory",
        [],
    ),
    case(
        "d19",
        "legacy-applicability",
        "Which dependency is checked first in the archived evaluation release?",
        "checkout",
        [("checkout-archive", "Archived order")],
        release="demo-v0",
    ),
    case(
        "d20",
        "staging-applicability",
        "Which payment endpoint is used by the staging evaluation gateway integration?",
        "payment",
        [("payment-staging", "Staging endpoint")],
        environment="staging",
    ),
]

HELDOUT = [
    case(
        "h01",
        "deployment-causality",
        "An error began around the release. Is the deployment definitely responsible?",
        "checkout",
        [("release-correlation", "Timing is not causation")],
    ),
    case(
        "h02",
        "deployment-history",
        "Can we produce a verified deployment timeline from these tools?",
        "checkout",
        [("release-correlation", "Missing deployment history")],
    ),
    case(
        "h03",
        "old-guidance",
        "Could an old architecture note send us to a dependency that no longer exists?",
        "payment",
        [
            ("release-correlation", "Applicability of guidance"),
            ("configuration-scope", "Environment and release"),
        ],
    ),
    case(
        "h04",
        "corpus-update",
        "If the runbook index changes halfway through an investigation what should happen to its references?",
        "checkout",
        [("configuration-scope", "Revision reproducibility")],
    ),
    case(
        "h05",
        "corpus-failure",
        "An updated knowledge index failed publication. Can old investigations still use the previous guidance?",
        "payment",
        [("configuration-scope", "Revision reproducibility")],
    ),
    case(
        "h06",
        "empty-versus-missing",
        "The source successfully found zero matching rows. Is that equivalent to an unreadable log file?",
        "inventory",
        [("missing-evidence", "Empty results versus unavailable sources")],
    ),
    case(
        "h07",
        "retention",
        "The logs rotated and results are truncated. Do we have a complete history of the incident?",
        "checkout",
        [("missing-evidence", "Retention and truncated evidence")],
    ),
    case(
        "h08",
        "causal-abstention",
        "The available records cannot distinguish competing explanations. What should the report say?",
        "payment",
        [
            ("missing-evidence", "Abstain when support is missing"),
            ("retry-safety", "Guidance is not evidence"),
        ],
    ),
    case(
        "h09",
        "score-meaning",
        "Does the nearest passage distance represent a calibrated probability of the cause?",
        "payment",
        [("missing-evidence", "Abstain when support is missing")],
    ),
    case(
        "h10",
        "liveness",
        "Health returns OK while charge requests fail. Are those observations contradictory?",
        "payment",
        [
            ("health-semantics", "A reachable process can reject work"),
            ("payment-errors", "Competing explanations"),
        ],
    ),
    case(
        "h11",
        "recovery-time",
        "One request succeeds after the incident. Does that establish availability throughout the earlier window?",
        "checkout",
        [("health-semantics", "Observed recovery")],
    ),
    case(
        "h12",
        "live-cause-limit",
        "Does a later successful business operation reveal why an earlier operation was rejected?",
        "payment",
        [("health-semantics", "Observed recovery")],
    ),
    case(
        "h13",
        "automatic-remediation",
        "May the investigator restart a service or repeat a charge suggested by a runbook?",
        "checkout",
        [
            ("retry-safety", "No automatic transaction retries"),
            ("checkout-downstream", "Verification and limits"),
        ],
    ),
    case(
        "h14",
        "documentation-versus-fact",
        "Can a relevant procedure itself prove the current incident is caused by that procedure's failure mode?",
        "payment",
        [("retry-safety", "Guidance is not evidence")],
    ),
    case(
        "h15",
        "scope-preservation",
        "Does semantic similarity make staging guidance applicable to a local release?",
        "checkout",
        [("configuration-scope", "Environment and release")],
    ),
    case(
        "h16",
        "fraud-absence",
        "What fraud scoring weights and chargeback dispute SLA does the merchant use?",
        "payment",
        [],
    ),
    case(
        "h17",
        "loyalty-absence",
        "Explain the loyalty point expiry and customer membership upgrade algorithm",
        "checkout",
        [],
    ),
    case(
        "h18",
        "forecast-absence",
        "Which seasonal demand forecast determines automated supplier purchase orders?",
        "inventory",
        [],
    ),
    case(
        "h19",
        "wrong-release-filter",
        "How do we correlate payment errors?",
        "payment",
        [],
        release="unknown-version",
    ),
    case(
        "h20",
        "wrong-environment-filter",
        "How should checkout bad gateway be investigated?",
        "checkout",
        [],
        environment="production",
    ),
]


def main():
    if (HERE / "data").exists():
        raise SystemExit("Refusing to overwrite frozen study data")
    manifest_path = ROOT / "knowledge" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for doc_id, (service, title, sections) in DOCS.items():
        path = ROOT / "knowledge" / "runbooks" / f"{doc_id}.md"
        path.write_text(
            "# "
            + title
            + "\n\n"
            + "\n\n".join("## " + heading + "\n\n" + text for heading, text in sections)
            + "\n",
            encoding="utf-8",
        )
        manifest["documents"].append(
            {"id": doc_id, "path": f"runbooks/{doc_id}.md", "title": title, "service": service}
        )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    corpus = HERE / "data" / "corpus"
    shutil.copytree(ROOT / "knowledge" / "runbooks", corpus / "runbooks")
    extras = [
        {
            "id": "checkout-archive",
            "path": "runbooks/checkout-archive.md",
            "title": "Archived evaluation checkout ordering",
            "service": "checkout",
            "release": "demo-v0",
        },
        {
            "id": "payment-staging",
            "path": "runbooks/payment-staging.md",
            "title": "Staging evaluation payment routing",
            "service": "payment",
            "environment": "staging",
        },
    ]
    (corpus / "runbooks" / "checkout-archive.md").write_text(
        "# Archived evaluation checkout ordering\n\n## Archived order\n\nThis synthetic archived evaluation release checks payment before inventory. It is not real release history and is not applicable to the current local demo-v1 application.\n",
        encoding="utf-8",
    )
    (corpus / "runbooks" / "payment-staging.md").write_text(
        "# Staging evaluation payment routing\n\n## Staging endpoint\n\nThis fictional staging evaluation variant sends payment calls to the gateway-staging charge endpoint. It does not describe the local demo, which has no external gateway.\n",
        encoding="utf-8",
    )
    (corpus / "manifest.json").write_text(
        json.dumps({"documents": manifest["documents"] + extras}, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "data" / "development.json").write_text(
        json.dumps(DEV, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "data" / "heldout.json").write_text(
        json.dumps(HELDOUT, indent=2) + "\n", encoding="utf-8"
    )
    checksums = {
        path.relative_to(HERE).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((HERE / "data").rglob("*"))
        if path.is_file()
    }
    (HERE / "data-lock.json").write_text(json.dumps(checksums, indent=2) + "\n", encoding="utf-8")
    print(
        {
            "development": len(DEV),
            "heldout": len(HELDOUT),
            "evaluation_documents": len(manifest["documents"]) + len(extras),
        }
    )


if __name__ == "__main__":
    main()
