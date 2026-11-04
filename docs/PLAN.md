# Build and evaluation plan

## Milestones

| Period | Work | Exit evidence |
| --- | --- | --- |
| Week 1 | Environment qualification, architecture decisions, Compose setup, instrumented demo application, incident admission, first injected fault | One fault can be traced manually through real operational signals |
| Week 2 | Markdown ingestion, hybrid retrieval, typed tools, bounded agent, evidence-linked report | One live investigation completes; missing evidence is represented correctly |
| Week 3 | Redis, S3, leases/recovery, deduplication, SSE progress, MCP | Required failure tests pass and persistence survives interruption |
| Week 4 | Held-out evaluation, UI polish, documentation, reproducible demo | Results reproduce from saved snapshots and versioned configuration |

These are planning targets, not deadlines guaranteed before environment qualification. Deliver a working vertical slice before expanding the number of services or scenarios.

## First implementation increment

The user authorized starting implementation. The first backend slice is complete and tested: incident creation, a durable job, a worker, one read-only observation tool, and a persisted report. Dependencies are locked. Docker, PostgreSQL migrations, and local worker concurrency are now qualified with all 37 container tests passing; see STATUS.md.

The intended top-level layout is backend, frontend, demo-app, scenarios, infra, tests, and docs. These directories now exist, including the React dashboard; see DASHBOARD.md.

The second increment runs real HTTP checkout/payment/inventory services, request-correlated logs, an isolated temporary payment fault controller, and a read-only live log source. All 43 container tests passed and a real healthy/failure/recovery script persisted live evidence through the existing worker. See LIVE_DEMO.md. This is one availability scenario and evidence collection, not AI diagnosis or the full planned telemetry stack.

The third increment adds seven operational runbooks, local pinned MiniLM embeddings, PostgreSQL/pgvector hybrid retrieval, immutable citations, and saved guidance alongside logs. All 57 container tests passed, plus actual-model HTTP development checks and live failure/recovery. This completes retrieval mechanics for the current corpus; generative reasoning and the agent loop remain next. See RETRIEVAL.md.

The fourth increment adds a bounded LangGraph/native-Gemini loop, typed tools, application-owned durable state, request reservations, report reference validation, and cancellation. All 88 container tests passed. An actual Free-tier Flash-Lite investigation followed checkout's payment dependency and completed with two model calls. This is one failure-localization smoke example, not held-out root-cause accuracy. See AGENT.md.

## RAG quality milestone

The fifth increment freezes the original retrieval baseline, expands reviewed knowledge, deploys scope/revision/formatting correctness fixes, and records a forty-question internal retrieval study plus a sixteen-request fixed-context answer comparison. All 98 tests passed. Experimental ranking was not promoted because held-out outcomes were mixed. Further ranking tuning requires new versioned development/held-out data; see RAG_QUALITY_STUDY.md.

The sixth increment adds scoped reviewed architecture context, best-effort outbound credential redaction, deterministic malicious-action boundary tests, and a React investigation dashboard. The dashboard has submission/retry, reports, evidence/citation lookup, cancellation, event polling and export. Seven scripted browser checks passed. This does not establish live-model prompt-injection resistance; see SECURITY.md and STATUS.md for verification and infrastructure recovery.

## Additional incident scenarios

The reliability/integration increment implements optional application/revision-aware Redis caches with actual local measurements, guarded operator Markdown publication, persisted SSE with polling fallback, normalized alert admission and a leased local archive plus optional S3 adapter. MCP exposes selected local read-only API operations. STATUS.md distinguishes proxy/contract checks, SDK qualification and actual external connectivity. The remaining release gates are independent second-app usefulness/diagnosis evidence, private S3 qualification when the user connects AWS, reproducibility/resource checks and optional external host setup. Full telemetry/native alert adapters/public hosting remain separate roadmap expansions.

The seventh increment completes versioned application/service registration and captured-log onboarding through the real dashboard/API. Two labelled synthetic booking examples demonstrate configuration without source edits; they are not independently captured production incidents. Final regression passed 151 backend and eleven browser tests. Old demo failure/recovery and citations still resolve after migrations. New onboarding checks made no actual-model calls. Next, obtain independently produced second-app evidence and validate usefulness before broad infrastructure expansion; see APPLICATIONS.md.

Implement database connectivity failure, exhausted connections, a slow dependency, an unavailable service, wrong downstream configuration, and a deployment-induced application error. Include healthy behavior, insufficient evidence, and an unrelated deployment that creates a misleading correlation.

The fault controller knows the ground truth but exposes only normal operational symptoms to the investigator. Labels must not leak through scenario names, environment variables, image names, file paths, tool output, or access to the fault API.

## Evaluation

Start with 24 recorded incident instances: eight development and sixteen held-out. Vary parameters and traffic; hold out selected combinations. Repeated model runs are trials, not independent new incidents.

Compare a fixed incident summary, summary plus RAG, and RAG plus active tools using the same model, budgets, and frozen incident evidence. Evaluate missing traces and stale runbooks as ablations.

Capture scenario telemetry independently of any particular agent's query trajectory. Replay adapters answer supported bounded queries from snapshots; unavailable snapshot coverage is explicit. An artifact containing only the original agent's chosen observations is insufficient for a fair general replay comparison.

Measure root-cause family accuracy, responsible-service accuracy, top-three hypothesis accuracy, evidence retrieval, unsupported claims, appropriate abstention, tool count, duration, and tokens/cost. Use deterministic ground truth where possible and a human-review rubric for semantic evidence support. Model judging is supplementary.

Pin software revision, model identifier, prompts, corpus revision, embedding model, scenario parameters, and replay snapshot. Publish failures and limitations. Do not promise improvements before experiments.

## Acceptance checks

- Duplicate alert delivery creates one incident; later recurrences remain separate.
- Incident admission and job insertion are atomic.
- Two workers cannot finalize the same owned attempt.
- Expired leases recover and stale owners cannot advance investigation state.
- Worker interruption preserves completed progress and handles repeated reads honestly.
- Redis outage leaves source queries and investigations functional.
- Retrieval caches change when the knowledge revision changes.
- S3 interruption recovers or stays visibly failed/pending; object/database disagreement is reconciled.
- SSE reconnect replays ordered progress without duplicate UI entries.
- Cancellation and budgets prevent further actions at the defined boundaries.
- Invalid tool arguments, unknown tools, and invalid evidence references are rejected.
- Unavailable telemetry is not treated as a successful empty response.
- Prompt-like instructions in data do not change permissions.
- Ground truth is inaccessible to the agent.
- A clean checkout reproduces the setup and documented demonstration.
- CI and unit tests do not make paid model calls.

## Documentation and learning

Maintain the brief, architecture, decisions, current status, setup guide, API reference, data model, evaluation report, failure analysis, demo script, and interview handbook. The handbook must explain actual implemented decisions, alternatives, limits, and measured outcomes rather than memorized claims about unbuilt features.

## Spending and deployment gates

Require configured provider credentials and explicit model/batch budgets before live evaluation. The provisional $10 allowance requires confirmation in operational configuration before use. Application estimates cannot guarantee provider-wide billing limits. AWS provisioning, permissions, storage region, and lifecycle policies remain a separate setup step.

No public deployment is planned in v1. Do not provision cloud resources, publish the application, or incur charges as part of documentation preparation.

## Completed feature/evaluation increment (4 November)

Native version-4 alerts, timeout/handler-error demo scenarios, complete pre-agent 24-window capture and an aggregate Evaluation UI are implemented; see STATUS.md for final tests. The private S3 round trip is complete. The fresh twelve-call, four-development-case fixed-evidence pilot is recorded separately with negative findings and no held-out calls. It is not the planned full active-workflow comparison or an independent benchmark. Next freeze responsible-service semantics/claim-support rubric and a production-workflow replay protocol before consuming the sixteen reserved cases; obtain independent second-app evidence and qualify remote CI/restart/load behavior. Full telemetry backends and public hosting remain deliberate separate expansions.

## Local release result

v5 report-grounding semantics, external benchmark onboarding, pinned images, the guarded S3 watcher, clean-source verification and recruiter assets are complete locally. Clean-export CI-equivalent tests passed 249/no skips; eighteen Edge tests and clean frontend install/build passed. The full model comparison is not complete: provider errors stopped development and held-out, with failures retained and no retries. Do not tune on those outcomes or silently rerun. RELEASE_READINESS.md lists the remaining provider, independent-user and remote/different-machine gates. No paid upgrade or public/remote publishing occurred.
