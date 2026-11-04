# Local release readiness

This is a portfolio-ready local implementation with explicit qualification limits, not a public production release. The project is prepared for review; no remote repository was created/pushed and no remote CI run is claimed.

## Verified local deliverables

- Report workflow v5: originating-service definitions, narrow per-claim citation instructions, direct-reference HTTP-status consistency and service anchoring. This is not complete semantic entailment checking.
- Existing durable admission, leased/fenced workers, replay/checkpoints, scoped hybrid RAG, cache controls/diagnostics, captures/runbooks, SSE, alerts, MCP and private S3 exports remain in the app. STATUS.md separates historical and current milestones.
- Clean-source export excluded ignored credentials, model weights, node_modules and runtime databases. A local CI-equivalent Python 3.12 image with all pinned optional SDKs ran **249 checks with no skips**, using real PostgreSQL test schemas and a disposable Redis. This includes three evaluation-grader checks. It reused installed/base dependencies and local service infrastructure; it is not an independent new-machine or remote-CI test.
- Windows application suite: 222 passed/24 PostgreSQL-dependent skips, plus the three grader tests passed separately. All eighteen real Edge browser tests passed. The clean export installed its locked frontend dependencies from local npm cache and passed the production build/Prettier checks.
- Configured-secret exact matching found no matches in candidate source, and private runtime material was excluded. This is a scoped check, not a comprehensive secret-audit guarantee. Review before publishing.
- The Python base, pgvector database and Redis images are pinned to locally qualified digests. The CI workflow installs all optional SDK locks and includes grader checks; its remote execution remains unverified.
- The bounded cache-off local read check completed forty serial and eighty concurrency-four RAG reads with zero errors and stable result identities. It is not a load SLO or production capacity estimate.
- An external MIT-licensed RCAEval excerpt passed application/capture/deduplication through the real API. Its unknown-severity, incomplete-topology and tiny-window limitations are explicit. It does not prove independent user usefulness or diagnosis accuracy.
- A 20.72-second, 1440×1000 saved-workspace walkthrough is in docs/assets/demo.webm, with a screenshot in docs/assets/overview.png. It issued no mutations or new model calls. README links the demo, study limits and interview guide.

## Model evaluation is not complete

The four-case development pilot remains frozen separately. The new production-code comparison stopped on provider errors: development timed out on its first request; after a separate protocol qualification succeeded, held-out stopped at its tenth attempted episode. Nine reports completed, fourteen held-out model starts were recorded, and 60,138 tokens were reported. Unknown/error usage may be missing. No request was retried and no successful output replaced a failure.

The planned fifty-two-episode comparison did not finish. Twelve captured cases remain untouched. Mechanical summary publishes no final accuracy fractions for an incomplete phase. Do not claim “90% diagnosis accuracy,” a validated RAG answer-quality gain or a completed held-out agent comparison. A future continuation needs an explicit frozen protocol preserving prior outcomes and a stable configured provider; do not rerun existing phase directories as supposedly unseen tests.

## Remaining external/operational gates

1. Finish the bounded model comparison when the configured provider is reliable, using the preserved failure record and a documented continuation protocol. No automatic retries or alternate paid model are configured.
2. Obtain independently produced real-app evidence and independent usefulness/claim-support review. The public benchmark onboarding check is a partial substitute only.
3. Run setup on another machine and the remote CI workflow after the owner chooses/connects the target repository. Local source/export tests are not remote CI evidence.
4. Observe sustained renewal under the revised S3 watcher. One original timed renewal succeeded and a later original CLI refresh failed. The revised watcher’s bounded retries, expiry guard and exclusive lock have tests and a successful initial real session, but not a complete timed cycle yet.

## Before publishing

Run scripts/release_check.py, inspect the candidate files and test results, preserve external licenses, choose the project's own distribution license, and review any external data/recorded screenshots. Keep .env, .aws, work, data, runtime databases and private keys out of Git. Review/stage/commit locally only after checking the content, then connect the intended repository. A remote push/public release is a separate owner action; no credentials should be pasted into chat or committed.

Use RESUME_BULLETS.md for the three concise, defensible bullets. The strongest established improvement is the local repeated-query retrieval median reduction; it is not model accuracy or end-to-end investigation speed.
