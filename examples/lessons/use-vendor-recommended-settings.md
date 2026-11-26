---
schema: 1
id: use-vendor-recommended-settings
uid: 01JDXQ9A1B2C3D4E5F6G7H8J9K
trigger: Am I about to benchmark models with one shared sampling config?
scope: universal
tags: [benchmarking, llm]
status: active
superseded_by:
related: [measure-before-config-change]
created: 2026-11-26
updated: 2026-11-26
review_after: 2027-06-01
origin: own
---
Benchmark each model with the sampling settings, effort and chat template from its own
model card, not one shared config.
**Why:** a shared temperature made one model look far worse than it is.
**How to apply:** read each model card first; record the settings next to the results.
