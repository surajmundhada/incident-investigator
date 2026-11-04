# RAG quality study — 4 November 2026

The correctness changes are deployed. Baseline ranking remains the production default because the experimental ranking had mixed held-out results. No alternate winner was selected from the held-out set.

## What changed

- Incident environment/release are validated, persisted, and passed to retrieval. Old default-scope idempotency keys remain replayable through versioned request hashing.
- The local log source explicitly returns unavailable for unsupported environments/releases instead of relabeling local observations.
- The first successful knowledge result pins revision and ranking profile for agent follow-up searches. Old citations remain resolvable after publication.
- The chunker preserves Markdown whitespace, lists, indentation, and source line ranges. It remains token-window based; it is not a complete Markdown AST or parent/child retriever.
- Experimental profiles add deterministic keyword shaping, passage diversity, and a pinned local ONNX reranker. The default does not load or use that reranker.
- Reviewed knowledge grew from seven documents/twenty passages to thirteen documents/thirty-two passages. Synthetic version/environment distractors stay evaluation-only.

## Study design

The frozen pre-change implementation and original corpus are under evaluation/baseline-v1. Every ranking method was compared on the same expanded fifteen-document evaluation corpus: thirteen reviewed documents plus two explicitly fictional applicability distractors. Forty authored questions were split into twenty development and twenty held-out cases by question family. Documents can be shared. The implementation assistant authored the corpus, queries, and labels; this is an internal study, not an independent benchmark.

Selection was frozen before the one held-out run. Source and data hashes were checked. Relevant units are document/heading sections, not whole-document hits. Duplicate sections get no additional relevance credit. Warm latency uses two measurements per question after a warm-up, excluding model initialization; these small local timings are not load benchmarks or SLOs.

The lexical baseline uses PostgreSQL plainto_tsquery (AND semantics) and ts_rank_cd. It is intentionally simple and untuned, not BM25. A poor result from this baseline does not establish superiority over a well-tuned lexical system.

## Development results

| Method | Section Recall@5 | MRR@5 | nDCG@5 | Empty result on absent knowledge | Warm p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen keyword AND baseline | 5.9% | 0.029 | 0.037 | 100.0% | 4.8 ms |
| Frozen semantic | 100.0% | 0.833 | 0.876 | 33.3% | 21.2 ms |
| Frozen hybrid | 100.0% | 0.804 | 0.854 | 33.3% | 18.3 ms |
| Preserved formatting + baseline ranking | 100.0% | 0.804 | 0.854 | 33.3% | 12.0 ms |
| Query policy only | 100.0% | 0.853 | 0.890 | 33.3% | 22.3 ms |
| Query + diversity (development selection) | 100.0% | 0.853 | 0.890 | 33.3% | 20.5 ms |
| Query + diversity + reranker gate | 82.4% | 0.794 | 0.802 | 100.0% | 380.1 ms |

## Held-out results

| Method | Section Recall@5 | MRR@5 | nDCG@5 | Empty result on absent knowledge | Warm p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen keyword AND baseline | 0.0% | 0.000 | 0.000 | 100.0% | 1.5 ms |
| Frozen semantic | 86.7% | 0.844 | 0.795 | 40.0% | 9.2 ms |
| Frozen hybrid | 86.7% | 0.844 | 0.795 | 40.0% | 10.1 ms |
| Preserved formatting + baseline ranking | 86.7% | 0.844 | 0.795 | 40.0% | 11.0 ms |
| Query policy only | 96.7% | 0.806 | 0.823 | 40.0% | 7.7 ms |
| Query + diversity (development selection) | 90.0% | 0.789 | 0.794 | 40.0% | 11.5 ms |
| Query + diversity + reranker gate | 76.7% | 0.833 | 0.774 | 100.0% | 348.4 ms |

Development has seventeen answerable and three absent-knowledge questions. Held-out has fifteen answerable and five absent-knowledge questions. Recall is averaged over answerable questions; an empty retrieval is not the same as a generated answer correctly abstaining.

## Rollout decision and failure analysis

Development selected query+diversity, using the preregistered quality and latency criteria. On held-out questions, its mean section recall rose from 86.7% to 90.0%, while MRR fell from 0.844 to 0.789 and nDCG was essentially unchanged/slightly lower. It missed deployment-causality guidance that the original hybrid found. Diversity showed no development relevance gain over query shaping alone.

The query-only profile scored better on held-out recall, but switching to it now would use test results for selection. It was not promoted. Baseline ranking was retained as a post-study rollout hold; the experimental profiles remain explicit options for a future study with new held-out questions. This is a deployment decision, not a retuned benchmark claim.

The reranker rejected all absent-knowledge queries but reduced answerable recall (development 82.4%, held-out 76.7%). It failed the development recall requirement and was not selected. Its raw-score threshold of zero is not a calibrated confidence score. No thresholds were changed after these outcomes.

Applicable full-context coverage contained every labeled answerable section. Context sizes ranged up to 1,722 embedding tokens. This corpus is small enough for an all-applicable-runbooks baseline; the experiment does not show that retrieval is necessary or solves a large-scale search problem.

## Fixed-evidence answer comparison

A separate exploratory check used the saved checkout/payment example, four questions, and four context methods. It reused selected old observations rather than an independently captured complete incident. Only finish_investigation was allowed, so this is not an active-agent diagnosis comparison. All methods used the same prompt and model. Root checkout/global applicability was fixed for guidance; payment-specific guidance could therefore be excluded even when payment observations were supplied.

| Context | Structurally valid reports |
| --- | ---: |
| logs_only | 4/4 |
| all_context | 4/4 |
| v2_baseline | 3/4 |
| development_selected | 3/4 |

The batch completed 16 actual Free-tier requests and recorded 64,449 tokens, within its predeclared limits. No provider retry or paid fallback was used. The earlier qualification/account-wide usage is outside this batch total.

Logs-only and all-context also described the failure path and avoided asserting a specific database/deployment cause in these questions. This sample provides no evidence of improved answer quality from retrieval. The shared system prompt already instructs every method to avoid unsupported causal claims.

Two deployment-question outputs failed schema/reference validation. The first runner saved their status and usage but not their rejected bodies, so the exact defect cannot be reconstructed. That retention gap is disclosed; the original runner is preserved and future runs now retain the raw declared action before validation. The completed batch was not rerun.

Assistant review found two structurally valid observations whose text included checkout 502 while their direct references omitted the 502 completion record. The complete supplied context did contain that fact. This is partial per-claim citation support, demonstrating why valid IDs do not establish semantic grounding. Some database-oriented follow-up suggestions also need applicability review against the actual no-business-database demo. No faithfulness percentage or independent-review claim is made.

## Verification and reproduction

All 98 tests passed in the Python 3.12 agent container, including thirteen PostgreSQL tests. The host run passed 85 with thirteen PostgreSQL skips. Read-only HTTP verification passed active/old revision selection, preserved old citations, metadata filters, candidate diversity, and the new incident scope schema.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
docker compose -f compose.yaml -f compose.evaluation.yaml --profile evaluation run --build --rm rag-evaluator python /evaluation/run.py development
docker compose -f compose.yaml -f compose.evaluation.yaml --profile evaluation run --rm rag-evaluator python /evaluation/run.py heldout
```

The evaluator refuses to overwrite recorded phases. Reproducing as a new run requires an explicitly separate results directory/workspace; do not erase these results to reuse the held-out set as if unseen. It uses a dedicated investigator_rag_study database and owned random schemas, then drops only those schemas. It has no Gemini key and makes zero generative calls. Evaluation data is excluded from application images and is not ingested into production knowledge.

For a separate reproduction using already-seen questions, keep the original files and mount an empty output directory over /evaluation/results. For example, add --volume E:/incident-investigator/work/rag-reproduction:/evaluation/results to both evaluator run commands (adjust the host workspace path). Those repeated questions must not be described as a new held-out set.

Source artifacts: evaluation/STUDY.md, evaluation/data-lock.json, evaluation/results/development.json, heldout.json, selection-lock.json, answers.json, and answer-review.json. The answer protocol and capped operator runner are evaluation/ANSWER_STUDY.md and evaluation/answers.py. The runtime verification is work/rag-runtime-verification.json.

## Next experiments

- Improve keyword-query semantics and diversity policy using fresh development cases, then collect a new held-out set.
- Evaluate evidence-aware dependency guidance retrieval with the same permitted scope and pinned revision, rather than assuming root-only context is sufficient.
- Add procedure/parent-section expansion only where token-window failures justify it; preserve source/version references and context budgets.
- Strengthen semantic claim and suggested-check review independently of citation existence. Keep human/assistant judgments distinct from deterministic tests.
- Compare embeddings or score thresholds only under a new, versioned study. Redis and S3 remain separate later increments.
