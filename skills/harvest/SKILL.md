---
name: harvest
description: Distill the shareable lessons learned in this Claude Code session (and the current project's auto memory) into the stickit-notes store, so every future session on any machine, and anyone the user shares with, can use them. Use when the user runs /harvest, or asks to save, keep, capture or remember lessons, learnings, gotchas or "what we learned" from this session.
argument-hint: "[optional focus, e.g. 'the router debugging']"
allowed-tools:
  - Read
  - AskUserQuestion
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/bin/stickit" *)
---

# Harvest lessons into stickit-notes

Goal: turn what this session taught into a few durable, **shareable** lessons,
each with a **trigger question** that will fire at the right moment in a
future session. stickit-notes holds lessons that would help anyone; private
and machine-specific knowledge belongs in auto memory, which stays as it is.
Quality over quantity: three sharp lessons beat ten vague ones. The user
approves every lesson before it is written.

Run the CLI as `python3 "${CLAUDE_PLUGIN_ROOT}/bin/stickit" <command>`
(written `stickit` below).

## 1. Check the store and gather what exists

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/stickit" context
python3 "${CLAUDE_PLUGIN_ROOT}/bin/stickit" list --json --status all
```

If `store_exists` is false, stop and tell the user to run `/stickit init`
(new store) or `/stickit init --clone <url>` (existing notes), then
`/harvest` again.

## 2. Find candidates

Sources, in this order:

1. **This session.** Look for: corrections the user made to you; things that
   failed and the fix that worked; an approach the user confirmed as right
   when it was not obvious; traps in tools, environments or workflows; user
   preferences about how to work. If the user passed a focus
   (`$ARGUMENTS`), stay inside it.
2. **Auto memory of the current project (read-only).** The system prompt
   names its folder ("persistent file-based memory at ..."). Read its
   `MEMORY.md` index, then only the entries that look like durable lessons,
   mainly `feedback` and `user` types. **Never edit, move or delete auto
   memory files.**

Keep only what passes the **sharing test**: *would this help someone else,
on a different machine, in a different project?* Skip anything that is:
- personal: the user's own preferences, habits or working rules;
- machine-specific: this host's hardware, installed tools, paths, services,
  network or accounts;
- project-specific: true only inside this codebase;
- already recorded in code, docs, git history or an existing lesson;
- a one-off task detail, a temporary state, or a status update;
- a secret, credential, or anything about other people.

A specific experience often hides a general lesson: "this server's CPU lacks
AVX2, so npm binaries crash" is machine-specific, but "Is this prebuilt
binary built for an instruction set this CPU lacks?" is shareable. Propose the
general form, and only when it stands on its own.

## 3. Draft each lesson

For every candidate decide **new**, **update** (an existing lesson says the
same thing; improve it instead of duplicating) or **skip**.

- **trigger**: one question, asked at the moment *before* the mistake,
  ending in `?`, at most 200 characters. Good: "Am I about to change a model
  server config before measuring and reporting?" Bad: "Configs" or "Remember
  to be careful."
- **body**: the rule in one or two sentences, then `**Why:**` (the reason or
  incident, told without names, hosts or private details) and
  `**How to apply:**` (concrete steps). Under about 120 words.
- **scope**: `universal`. (The format also supports `host:`/`project:`
  scopes, but /harvest does not propose them; that knowledge stays in auto
  memory.)
- **tags**: 1–4 lowercase words (e.g. `git`, `testing`, `workflow`).
- **id**: short kebab-case slug of the idea (e.g. `measure-before-config-change`).

## 4. Ask the user

Use AskUserQuestion with `multiSelect: true`. One option per candidate:
label = the id (prefix `update:` for updates), description = the trigger and
scope. Up to 4 options per question and 4 questions; if you have more than 16
candidates, offer the best 16. If nothing is worth keeping, say so and stop:
an empty harvest is a fine result.

## 5. Write the approved lessons

Always pass lessons as JSON on stdin with a quoted heredoc, never as shell
arguments (quotes and `$` in text would break):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/stickit" new --json - <<'STICKIT_JSON'
{"id": "measure-before-config-change",
 "trigger": "Am I about to change a model server config before measuring and reporting?",
 "scope": "universal",
 "tags": ["workflow", "infra"],
 "body": "Measure the current state and report before changing any config.\n**Why:** unreviewed changes broke the router twice.\n**How to apply:** measure, write the report, wait for approval, then change."}
STICKIT_JSON
```

For an update: `stickit update <id> --json -` with only the changed fields.

If the CLI rejects a lesson for personal details (paths, names, hosts,
emails, IPs), rewrite it generically: `~/...` for paths, "the server" instead
of a host name. Do not add `--allow-personal` unless the user explicitly asks.
If it reports a possible secret, remove the secret; never work around it.

## 6. Finish

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/stickit" mark-harvested --session "${CLAUDE_SESSION_ID:-}"
```

Then report in two or three lines: which lessons were added or updated (ids)
and, if the store has a git remote, that `/stickit sync` shares them with the
user's other machines.
