# RAG quality study protocol

Freeze date: 4 November 2026. This protocol is written before running the new question set.

The original knowledge implementation and original seven-document corpus are preserved under baseline-v1, with SHA-256 checksums. Never overwrite that snapshot. Compare the frozen implementation and candidate implementations on the same expanded, explicitly authored corpus using isolated PostgreSQL schemas. Preserve original results separately.

Create 40 authored questions: 20 development and 20 held-out. Split by question family; documents may be shared. One author creates the corpus, questions, and relevance labels, so this is a small internal study, not an independent benchmark. No-answer cases concern knowledge absent from the corpus, rather than live facts that should be obtained from tools. Version/environment distractors are synthetic evaluation material, not real release history.

Evaluate section-level Recall@5, MRR@5, duplicate-aware nDCG@5, no-answer abstention, and measured warm p50/p95 latency. Ground truth is a set of document/heading relevance units; duplicate hits earn no additional relevance credit. Record returned passages and all omissions. A passage ranking is not diagnosis accuracy or claim faithfulness.

Development selection compares frozen hybrid, a query-only intermediate, improved keyword/query/diversity hybrid, and hybrid with a local MiniLM cross-encoder. A v2-baseline ablation isolates chunk-format changes. The reranker has a predeclared raw-score gate of zero, not a probability threshold. Select using the mean of answerable recall and no-answer abstention, then MRR, then latency; a candidate must not lower development answerable recall and must have warm p95 below two seconds. If no candidate qualifies, preserve the legacy default. Do not tune after reading held-out results. Freeze the selected configuration and implementation hashes before one held-out run. Report regressions.

Also record lexical-only, semantic-only, and all-applicable-context baselines. The last baseline establishes available context coverage and token cost; it is not a ranked retrieval model. No claim that RAG is necessary is justified by this small corpus alone.

Only the evaluator mounts evaluation data. No evaluation labels, synthetic distractor documents, or baseline snapshots are copied into application images or production knowledge. Actual agent tools retain only reviewed knowledge, fixed observation sources, and typed permissions.

This first study measures local retrieval. Any separate answer-generation comparison must pin the model, prompt, evidence, context policy, and batch budget, and report citation semantics separately from reference validity.
