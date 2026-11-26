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
