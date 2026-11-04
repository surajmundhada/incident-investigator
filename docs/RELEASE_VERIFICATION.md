# Local release verification — 5 November 2026

This is an author/AI-assisted self-review, not an independent audit. Verification used a separate freshly initialized local checkout populated by direct-path Git fetch/checkout from the cleaned repository. No named remote was registered. This is the local clone equivalent chosen to preserve the no-remotes constraint; it is not a different-machine test or remote CI.

## Final observed results

| Check | Result | Evidence |
|---|---|---|
| Backend/integration suite | 286 passed, no skips, no failures | [captured output](verification/backend-suite.txt) |
| Browser suite | 18 passed in headless Edge | [observed summary](release-verification.json) |
| Python lint and formatting | Passed; 118 Python files checked for formatting | [verification record](release-verification.json) |
| Frontend locked install, build, formatting | Passed from corrected fresh checkout | [verification record](release-verification.json) |
| Metrics and frozen-input hashes | 96 read-only checks passed | [fields and values](release-verification.json), [checker](../scripts/verify_documented_metrics.py) |
| Documentation | README/evaluation/security rendered; four Mermaid diagrams rendered; no broken checked local links | [verification record](release-verification.json) |
| README startup | Separate Compose stack healthy; migrations applied; ready endpoint returned 200 | [runtime smoke record](release-verification.json) |
| Optional local RAG | Pinned download checksums passed, index built, search returned six passages, synthetic investigation completed with zero model calls | [runtime smoke record](release-verification.json) |
| Configuration | .env.example base Compose and full optional override resolution passed using dummy cloud identifiers | [verification record](release-verification.json) |

The complete integration image contained pinned optional SDKs and used real PostgreSQL/Redis, owned test schemas and selected local MCP stdio tests. Browser API responses are controlled fixtures. Installed base/dependency caches were reused where available; dependency/model downloads and fresh npm installation also completed. The original application stack was not rebuilt, restarted or used as the test database. Test projects used separate names and loopback ports to avoid existing listeners.

## Failures found and resolved

The first fresh checkout passed application/browser tests but failed Prettier because Windows Git converted files to CRLF. .gitattributes now keeps normal source LF while preserving frozen evaluation/JSON/lock bytes. A second fresh checkout passed formatting. The previous unanchored data/ exclusion omitted evaluation/data; it is now root-only /data/, and the frozen inputs are included without changes and validated against their locks.

One later full integration run reported one failure and 285 passes: the concurrent Redis test required a waiting-thread metric even when scheduling allowed one query to finish before contention. The documented bounded cache contract permits duplicate computation after a wait timeout. The test now checks consistent concurrent results, bounded work/hit accounting and a subsequent actual Redis hit rather than requiring a scheduler event. Runtime cache behavior was not changed. The following complete run passed all 286 checks. Earlier failures were not presented as a passing run.

## Secret-scanner outcome

Gitleaks 8.30.1 scanned the cleaned tree and its new local history with fully redacted output. It returned exit code 1: 14 tree alerts and 28 historical alerts, all reviewed SHA-256 metadata matches in model locks/source-result hashes. No broad allowlist or suppression was introduced. No confirmed credential was identified. Exact configured-secret matching and privacy checks must still be retained for the final source candidate; scanner patterns do not establish comprehensive absence of sensitive data. The actual bucket identifier was removed from public source; private .env, original Git metadata and runtime files remain local and are excluded from this repository.

## Numbers and remaining limits

Current README and evaluation-table claims were reconciled with preserved source JSON. The unique-query median overhead computes to 27.441%, rounded to 27.4%; older prose's approximate 27.5% was corrected without altering measurements. Frozen questions, captures and result records were not rerun or edited. Historical test counts and the operator-recorded 6,743-byte S3 round trip in older notes do not all have their raw logs in public source; those are historical author records, not newly re-established release measurements. A public raw S3 transcript is deliberately absent because operator evidence stays private.

The app remains local-only and unauthenticated. Default container users and shared privileged database credentials remain disclosed limits; no unverified non-root or role split is claimed. Original incident/live evidence may remain in local records and exports despite outbound model redaction. Hosted-provider behavior, renewed live S3 connectivity, sustained watcher renewal, independent usefulness/semantic review, container-OS vulnerability scanning and remote CI were not established by this release verification. The original running stack still needs an explicit later rebuild to load these source changes; release work did not redeploy it.

## Release checklist

- Credential aliases and explicit database configuration have regression coverage.
- Published Compose ports remain loopback-only and are tested.
- MIT license, third-party notices and adjacent RCAEval MIT attribution are present.
- Redis server and Python client licenses are distinguished.
- Clean copy excludes original .git and ignored runtime/dependency material.
- Original .env and inventoried frozen evidence remain unchanged.
- No pre-existing user files or volumes were deleted; temporary test resources are owned by their test runs.
- No remote was added, no push occurred and no repository visibility changed.
- Final source review and any eventual publishing remain owner actions.
