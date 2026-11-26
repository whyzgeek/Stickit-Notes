<!-- stickit-bundle v1 -->
# stickit-notes bundle

2 lesson(s), exported 2026-11-26. Import with `/stickit import <this file>` (see https://github.com/whyzgeek/stickit-notes).

<!-- stickit:lesson -->
---
schema: 1
id: measure-before-config-change
uid: 01JDXQ8Z0V7Q4M2N6P3R5S7T9W
trigger: Am I about to change a model server config before measuring and reporting?
scope: universal
tags: [workflow, infra]
status: active
superseded_by:
related: [use-vendor-recommended-settings]
created: 2026-11-26
updated: 2026-11-26
review_after:
origin: own
---
Measure the current state and write a short report before changing any model server
config, then wait for approval.
**Why:** an unreviewed context-size change ran the GPU out of memory mid-benchmark.
**How to apply:** measure (memory, latency, settings), report, get a yes, change, re-measure.

<!-- stickit:lesson -->
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
