# Small fixed-evidence answer study

This is a separate exploratory generation check after the retrieval study, not an extension of its held-out model-selection process. Do not change ranking or thresholds from these outputs.

Use the previously saved actual checkout/payment incident observations. These were selected by one earlier agent trajectory, not independently recorded complete telemetry. Consequently this cannot compare full agent diagnosis accuracy. The context methods are logs-only, all applicable reviewed passages, v2 baseline with the legacy ranking policy, and the development-selected experimental ranking. The corpus revision and evidence are fixed across methods.

Four questions cover failure localization, unsupported database attribution, misleading deployment correlation, and missing payment-side observations. Each method receives the same selected log evidence for a question. It can call only finish_investigation, not collect extra evidence. At most sixteen explicit Free-tier requests, 2,048 requested output tokens each, 512 KB aggregate serialized input, and 100,000 provider-reported total tokens. No automatic retries or paid fallback; stop on provider errors. These are application batch limits, not a provider-wide billing guarantee.

Check structural reference validity in code. Review natural-language claims separately against supplied records and guidance, distinguishing failure propagation from its underlying cause. Record unsupported assumptions, missed limitations, and incomplete answers. The reviewer is the same assistant working on the implementation, so these are exploratory judgments, not independent human ratings or a benchmark percentage.

Full-corpus context is deliberately included because the current reviewed corpus is small enough to fit. Save every output and usage, including failures. Do not claim that retrieval improves answer quality if all-context or logs-only performs as well.
