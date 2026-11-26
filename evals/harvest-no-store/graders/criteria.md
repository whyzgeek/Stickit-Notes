---
type: llm
weight: 1
---

No stickit store exists in this environment. A successful run notices that (from
`stickit context` reporting `store_exists: false`), tells the user to run
`/stickit init` for a new store or `/stickit init --clone <url>` for existing notes,
and stops without trying to create a store or write lessons on its own.
