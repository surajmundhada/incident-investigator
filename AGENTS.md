# Project instructions

## Purpose and current phase

Build a focused AI incident investigator for a placement portfolio. The user wants to understand and defend the system end to end. This repository is our own application, inspired by Aurora and HolmesGPT, not a renamed fork.

Read `docs/STATUS.md`, `docs/PROJECT_BRIEF.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, and `docs/PLAN.md` before substantial work. These documents preserve the decisions made in the original planning chat.

The current phase is implementation. Durable admission, leased workers, a live three-service demo, PostgreSQL/pgvector retrieval, and a bounded LangGraph workflow are implemented. A confirmed Free-tier Gemini key is configured locally; gemini-3.5-flash-lite completed one actual-model failure-localization smoke investigation. Follow docs/STATUS.md and docs/AGENT.md for verified behavior, configuration, and limits. Do not describe the full roadmap as implemented or turn one smoke test into an accuracy claim.

## RAG quality milestone

The frozen 40-question internal study and bounded 16-call answer comparison are complete; see docs/RAG_QUALITY_STUDY.md. All 98 tests passed. Scope propagation, legacy idempotency compatibility, preserved Markdown whitespace, and knowledge/profile pinning are deployed. Baseline ranking remains the production default because the experimental query/diversity profile had mixed held-out results. The local reranker is experimental, not enabled by default. Do not tune against these already-seen held-out questions or erase frozen results. Evaluation labels and synthetic distractors stay outside application images and production knowledge.

## Security and dashboard milestone

The React dashboard and model-boundary controls are implemented; see docs/DASHBOARD.md and docs/SECURITY.md. Current workflow is bounded-investigator-v5 (historical v4 results remain attributed), security version model-boundary-v2. Application registration, scoped knowledge and captured-log onboarding are documented in docs/APPLICATIONS.md. Final regression passed 151 backend and eleven browser tests; connected new-application checks were evidence-only, not actual-model diagnosis evaluation. Snapshot records receive recognised-pattern redaction before storage; legacy live/incident data is not retroactively sanitised. Do not relabel historical RAG studies as results for the changed prompt/corpus metadata.

## Operational constraints

- Target a 3â€“4 week complete version, replacing the earlier two-day deadline.
- A focused three-day first-demo target was subsequently discussed. Deliver working increments toward that target; the full architecture remains a roadmap.
- Development machine: Windows, 16 GB RAM.
- Run locally through staged Docker Compose profiles; use a private AWS S3 bucket for artifacts.
- Use PostgreSQL plus pgvector, Redis for disposable caching, and S3 for durable object artifacts.
- Investigations may start manually or through a local alert webhook.
- Agent tools are read-only. No automatic remediation or arbitrary shell execution in v1.
- Kubernetes, Memgraph, and Vault are deferred.
- Hosted LLM access is acceptable with explicit configuration and spending limits. The proposed $10 evaluation allowance is not permission to incur charges automatically.
- No cloud provisioning, paid API calls, publishing, or external messages have been performed or authorized merely by writing this plan.
- The user explicitly authorized free-tier model setup and confirmed the key's project is Free. The key stays in ignored .env. Small qualification and the first live smoke run were performed; future broad evaluations or paid upgrades are not automatically authorized by this fact.

## Engineering standards

- Explain substantial design decisions, alternatives, tradeoffs, and verification in plain language. Keep decision records current.
- Implement in vertical slices. Distinguish implemented, tested, proposed, mocked, and externally verified behavior.
- Keep application correctness outside model prompts: typed tool schemas, ownership checks, limits, and permissions are enforced by code.
- PostgreSQL is the source of truth. Redis must be disposable. S3 uploads and database updates require explicit reconciliation.
- Do not claim exactly-once execution, calibrated confidence, universal root-cause accuracy, or production readiness without evidence.
- Separate observed facts from hypotheses. An unavailable source is not an empty successful result.
- Pin model, prompt, corpus, scenario, and software versions for evaluations. Ground-truth fault labels must be inaccessible to the agent.
- Never fabricate evaluation results, citations, live model activity, or benchmark comparisons.
- Do not put secrets in source files, browser responses, logs, or committed artifacts.
- Attribute reused code and preserve its license. References are inspiration, not evidence that our implementation inherits their capabilities.
- Keep tests proportional to the behavior, with particular attention to retries, duplicates, interrupted workers, cache outages, artifact consistency, and evaluation leakage.

## Continuity

The user authorized continuing remaining local implementation. Optional Redis, guarded Markdown publication, SSE/polling fallback, normalized alerts and a local leased artifact archive are implemented. Optional MCP/S3 adapters have separate SDK/cloud qualification status in STATUS.md. No AWS resources or new hosted-model evaluations are authorized by SDK installation. The user asked to be notified when it is time to connect AWS; do not ask for keys in chat. Keep DECISIONS.md/STATUS.md and the new operator/interview guides current.

The user resumed the reusable-application/captured-log increment. docs/RESUME.md preserves the earlier pause checkpoint; STATUS.md is authoritative for current deployment and verification. Keep historical study results intact.

Update `docs/STATUS.md` at meaningful milestones with what changed, what was actually verified, unresolved issues, and the next step. Record changed architectural decisions in `docs/DECISIONS.md`. Do not mark planning targets as implemented features.

## Latest feature/evaluation checkpoint

Local release checkpoint: v5 report semantics/grounding guard is deployed. The production-code reserved comparison is INCOMPLETE, stopped on provider error after ten attempted episodes, nine validated reports and fourteen starts (60,138 reported tokens); development also stopped on its first timeout. Never overwrite/retry those phase outputs or call the partial run final accuracy. Twelve held-out cases remain untouched. A future continuation requires a frozen protocol preserving prior failures; no changes were selected from held-out outcomes.

The clean-source export passed 249 local CI-equivalent checks with real PostgreSQL/Redis and all SDKs, no skips; eighteen Edge checks passed, as did the fresh-cache frontend install/build. Configured-secret scans had no matches but are not exhaustive. The external RCAEval excerpt verifies onboarding only, not independent production-user value. README contains a read-only saved-demo video; RESUME_BULLETS.md explains defensible claims. RELEASE_READINESS.md is the current release-gate inventory. No remote publishing/CI execution was performed.

The original S3 watcher completed one timed renewal then later exited on AWS CLI failure. The revised launcher has exclusive locking, bounded transient-only renewal retries and an expiry guard; its initial scoped session passed, but no sustained timed-cycle claim is justified yet. Keep cache off by default and never pass human setup credentials into app containers.

The read-only Cache status view at /#cache extends /api/diagnostics/cache with API-process-only counters, empty-safe hit rates, snapshot timestamps/instance IDs and bounded per-path retrieval latency. It never probes Redis, exposes only whitelisted counters, and does not toggle Docker configuration. Worker/indexer activity and Redis server memory are explicitly excluded. Keep startup controls and S3-watcher configuration consistent as documented in CACHE.md. Main cache mode remains off. Latest cache-panel regression: 239 Docker passes/two MCP SDK skips, 217 Windows passes/24 PostgreSQL-dependent skips, eighteen browser passes; isolated actual Redis hit/miss/outage status and fallback checks passed with no model calls or cloud writes. Historical benchmark timings were not remeasured after instrumentation.

Native bounded Alertmanager version-4 admission, timeout/handler-error demo scenarios and the aggregate Evaluation dashboard are implemented and deployed. The latest regression passed 235 Docker tests with real PostgreSQL/Redis (two MCP SDK skips) and 213 Windows tests (24 PostgreSQL-dependent skips); all sixteen Edge tests passed. S3 is connected through the approved restricted temporary role; migration 0008 and the real synthetic checksum round trip are qualified. Follow STATUS.md/S3_CONNECTION.md for the foreground refresh watcher's current limits.

The separately frozen diagnosis-v2 dataset contains 24 controlled real-HTTP windows, eight development and sixteen held-out; these are correlated synthetic instances, not independent production evidence. The four-development-case, twelve-call Free-tier fixed-evidence pilot completed and is recorded under evaluation/diagnosis-v2/results. It does not establish RAG superiority or diagnosis accuracy. Review found partial per-claim citations and ambiguous affected/source-service semantics; do not invent a responsible-service or faithfulness score. No production ranking/prompt was changed from this pilot. Do not overwrite/repeat it or consume the sixteen reserved cases without a new frozen production-workflow evaluation protocol. Do not tune against either study's already-seen held-out questions. EVALUATION_PROGRESS.md preserves usable resume wording and measured tradeoffs.


## Public-source release checkpoint

User approved local release fixes and documentation on 5 November 2026. Keep .env, runtime data and all frozen evaluation inputs/results unchanged. Current source uses model-boundary-v3; API starts with create_app --factory and host database processes require explicit DATABASE_URL. Source IAM policy is a ${ARTIFACT_S3_BUCKET} template. Do not deploy/restart the original runtime, delete files, add remotes, push or change visibility. Verification must use a separate clean copy/local checkout and separate Compose project. The app remains unauthenticated and loopback-only; default container users/shared database roles remain disclosed limits. Record actual checks and failures without relabeling old model studies.
