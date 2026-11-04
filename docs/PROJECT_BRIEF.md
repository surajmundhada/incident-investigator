# Project brief

## Decision and audience

Develop our own focused incident investigator for AI engineering and backend/SDE placement interviews. It must complete a useful task, produce verifiable evidence, and be understandable end to end by the user.

The target user is a developer investigating a failure in a small distributed application. The system helps gather and interpret evidence; it does not replace the operator or guarantee causal diagnosis.

## Problem

Investigating a failure requires correlating logs, metrics, traces, deployment history, and operational documentation. Relevant evidence is distributed across sources, some sources may be unavailable, and outdated guidance or coincidental changes can mislead an investigation.

## Intended behavior

The reusable first release now includes versioned application/service registration and developer-supplied captured logs. The shopping application remains a built-in live reference source. Other applications can be investigated from bounded JSONL snapshots without investigator source changes; live cloud connectors and broader user-benefit evaluation remain future work. See APPLICATIONS.md for the implemented contract and limits.

Input: affected service, symptoms, and time window, entered manually or received through an alert webhook.

Output: observed symptoms and timeline; ranked hypotheses; supporting and contradictory evidence; missing information; suggested verification steps; termination reason; and investigation usage.

Example: checkout errors begin after a deployment. The agent checks whether payment failures are caused by the release, a database connectivity problem, or a slow dependency. Its report cites actual observations and explains what cannot be established.

## Scope of the first complete version

- A three-service shopping application: checkout, payment, and inventory.
- Real operational telemetry and recorded replay scenarios.
- Markdown runbooks, architecture notes, and reviewed incident guidance.
- Hybrid retrieval, one bounded agent, typed read-only tools, and selected MCP exposure.
- A dashboard with manual incidents, alert-driven investigations, live progress, evidence, and reports.
- Durable investigation state in PostgreSQL; disposable caches in Redis; private artifacts in S3.
- Recovery, duplicate handling, and explicit behavior for unavailable sources.
- Reproducible comparisons of a fixed summary, RAG, and RAG with active tools.

## Boundaries

No automatic remediation, arbitrary command execution, Kubernetes hosting, multi-cloud integrations, multi-tenancy, fine-tuning, graph database, or enterprise secrets manager in v1. PDF and scanned-document ingestion are deferred. Existing products already address the broad problem; neither the category nor a fault benchmark is claimed as novel.

## Practical constraints

- 3–4 week target for the complete version.
- Windows development machine with 16 GB RAM.
- Local Docker Compose plus AWS S3, rather than public AWS hosting.
- Hosted model API behind a provider adapter. Provider, exact model, current pricing, and credentials must be qualified before live use.
- A provisional $10 evaluation allowance, with explicit application budgets. It is not an account-level billing guarantee or authorization to spend immediately.
- First backend slice is implemented; see STATUS.md for evidence and limitations. The earlier RetrievalLab prototype belongs to another folder and is unrelated.

## First release target

After the full roadmap was documented, a focused three-day first-demo scope was discussed for placement readiness: fewer services and incidents, logs/metrics before distributed tracing, a minimal dashboard, and a small evaluation. Preserve the full architecture as a roadmap and qualify each increment honestly. The first completed slice is backend evidence collection; it is not yet an AI investigator.

## Success criteria

A clean checkout can reproduce the documented demo. The system investigates at least one real injected failure end to end, preserves evidence, handles selected infrastructure failures correctly, and publishes held-out evaluation results including failures. The user can explain each major component, accepted tradeoffs, and what the evaluation does and does not establish.

We will not set or claim an accuracy improvement until experiments have been run. A defensible negative result is preferable to manufactured success.
