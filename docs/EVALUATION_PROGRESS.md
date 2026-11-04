# Measured progress and resume claims

The Evaluation tab at http://127.0.0.1:5173/#evaluation shows aggregate measurements and their source hashes. It makes no provider call. Generate it with scripts/build_evaluation_summary.py, then format/build the frontend. Historical study results and the fresh pilot are distinct experiments, not a single accuracy trend.

## Actual comparisons

| Measurement | Before | Candidate | Decision and limits |
| --- | ---: | ---: | --- |
| Historical held-out section Recall@5 | 86.7% | 90.0% | +3.3 percentage points; candidate query/diversity ranking not promoted |
| Same experiment MRR@5 | 0.844 | 0.789 | Ranking regressed; do not report recall alone as overall improvement |
| Local repeated-query retrieval p50 | 9.245 ms | 1.694 ms | 81.7% lower with both caches; 40 sequential measured requests per mode, identical results |
| Local unique-query retrieval p50 | 9.781 ms | 12.466 ms | 27.4% slower with both caches; Redis stays optional/default-off |

RAG relevance units are document/heading sections, not whole-document hits. The original study has twenty development/twenty held-out authored questions; held-out has fifteen answerable and five absent-knowledge cases. These are internal measurements, not independent benchmark or diagnosis accuracy. Warm local timings are not load SLOs. See RAG_QUALITY_STUDY.md and CACHE.md for the frozen methods/results and limitations.

## Fresh controlled-capture development pilot

Twenty-four complete windows were recorded from actual local HTTP traffic, before model queries: six instances of each healthy/unavailable/slow/injected-handler-error family. Eight are development and sixteen held out; families are shared, so the instances are correlated. Capture hashes and split/label hashes are frozen under evaluation/diagnosis-v2/captures. No labels or questions enter application images or production knowledge.

The first four development windows, one per family, were compared across three methods with identical complete logs/topology and the same model/system prompt/output schema. The model could only finish_investigation. This is not the production active-tool workflow comparison.

| Context | Structurally valid reports |
| --- | ---: |
| Logs only | 4/4 |
| All applicable reviewed guidance | 3/4 |
| Production-baseline hybrid RAG | 4/4 |

The capped Free-tier run completed twelve calls, 61,104 provider-reported tokens and 177,851 serialized input bytes, with no retries, fallback model, billing upgrade or held-out calls. Original outputs are retained in results/development-pilot.json, including the raw parsed action of the rejected report. These are batch counts, not account-wide billing totals.

The rejected full-context report used a runbook passage ID in an observation-ID field. Same-assistant qualitative review also found claims whose direct citations omit part of the claim, a database-oriented follow-up poorly matched to the no-business-database demo, and mixed affected/source-service interpretations in hypotheses. Raw evidence may support a claim somewhere in the context while its direct references remain incomplete. Do not equate structural validity with faithfulness or automatically turn hypothesis.service into responsible-service accuracy. Review notes and source hash are in results/review.json.

No RAG answer-quality benefit is established here. No production ranking/prompt was changed based on this pilot. The sixteen held-out windows remain unused by the model; freeze the full replay comparison and semantic review rubric before evaluating them. Independently produced second-app incidents remain a separate usefulness gate.

## Resume wording that the evidence supports

“Built a bounded AI incident investigator with PostgreSQL-backed leased jobs, scoped hybrid RAG, immutable citations and private S3 archives; verified replay/recovery, cache outages and checksum-based artifact reconciliation.”

“Reduced median hybrid-retrieval latency by 81.7% on a local repeated-query benchmark (9.245 to 1.694 ms), preserving results; retained optional caching after measuring regression on unique queries.”

The RAG experiment is a strong interview discussion about evaluation and rejecting a harmful rollout. It does not support “improved AI accuracy to 90%.” A future improvement claim must identify the baseline, exact metric, dataset/version, denominator and rollout status, and report important regressions. A change from 78% to 90% would be twelve percentage points, not twelve percent relative improvement.

## Release evidence and remaining boundaries

The new feature build passed 235 Docker tests with real PostgreSQL/Redis (two MCP SDK skips) and 213 Windows tests (24 PostgreSQL-dependent skips, actual MCP checks passed). All sixteen Edge tests, frontend production build, Prettier and Python lint/format passed. A read-only connected desktop/mobile review had no errors, mutations or page overflow. Native Alertmanager parsing is qualified, but no alert server/subscription is provisioned. S3 has a bounded real round trip and manual credential renewal, not sustained production qualification. Public authentication, full telemetry backends, independent usefulness, load testing and remote CI remain separate work.

## Reserved production-workflow comparison: incomplete

The preregistered v5 comparison ran actual Repository/SnapshotStore/worker/Toolset/LangGraph code, using isolated SQLite replay persistence and the real pinned-revision API/PostgreSQL retrieval. Development stopped after its first model request timed out; that outcome was not retried. An independent protocol-readiness request succeeded, then the held-out phase completed nine reports before a provider request failure stopped episode ten. It started fourteen model calls and reported 60,138 tokens; provider-error outcomes may have unreported usage. The fifty-two planned episodes (forty-eight method comparisons plus four ablations) were not completed. Twelve captured instances remain untouched.

No final accuracy or superiority fraction is published. Partial typed counts are retained with null final fractions, and grader tests reject duplicate episode replacement and incomplete-run accuracy publication. Completed healthy examples had no causal hypotheses, and completed failure examples used payment as the originating service, but that observation is not a controlled before/after accuracy gain. The known provider timeout/failure remains part of the evidence; do not rerun or silently replace those episodes. A future continuation needs an explicit frozen protocol preserving every attempted outcome, not a new supposedly unseen test set.

The external RCAEval excerpt verifies registration/capture/deduplication on independently produced controlled data, not model diagnosis or real-user usefulness. The local 120-request concurrent read check is operational qualification only; raw data is in work/api-read-benchmark.json. Neither closes the remaining independent-benefit/full-model-evaluation gate.
