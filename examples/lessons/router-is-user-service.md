---
schema: 1
id: router-is-user-service
uid: 01JDXQAB2C3D4E5F6G7H8J9KMN
trigger: Before restarting the inference router, is it a user service on this machine?
scope: host:workstation
tags: [systemd, infra]
status: active
superseded_by:
related: []
created: 2026-11-26
updated: 2026-11-26
review_after:
origin: own
---
On this machine the router runs as a systemd **user** unit.
**Why:** `systemctl restart` on the system unit silently does nothing useful here.
**How to apply:** `systemctl --user restart llama-router`; check with `systemctl --user status`.
