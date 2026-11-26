# Architecture

## Components

```text
            Claude Code session
   ┌───────────────────────────────────────┐
   │ hooks/hooks.json ──► bin/stickit hook │──┐  SessionStart: inject triggers
   │ skills/harvest   ──► bin/stickit new  │  │  UserPromptSubmit / PostToolUse(Skill):
   │ skills/stickit   ──► bin/stickit ...  │  │    count prompts, notice /harvest
   └───────────────────────────────────────┘  │  Stop / PreCompact: one reminder
                                              ▼
                          src/stickit (stdlib only)
                                              │
                         ~/stickit-notes-data (git repo you own)
                          lessons/  inbox/  stickit.toml  .state/
                                              │  stickit sync (explicit)
                                              ▼
                                your private git remote ──► other machines
```

`bin/stickit` adds `src/` to the import path and runs the package, so the
plugin works from its folder without installing anything.

## Modules

| Module | Responsibility | I/O |
|---|---|---|
| `model` | `Lesson`, `Scope`, `Status`, validation, (de)serialization, ULIDs | none |
| `frontmatter` | strict YAML subset parser and serializer | none |
| `ranking` | which lessons a session sees, within a budget | none |
| `render` | session context text, tables, JSON | none |
| `redact` | personal-data rules, secret detection | none |
| `bundle` | share format v1, input sanitizing | none |
| `graduate` | managed block in CLAUDE.md / AGENTS.md | none |
| `context` | host and project detection | filesystem reads |
| `config` | `stickit.toml` and environment | file read |
| `store` | repository over the folder: atomic writes, `flock` lock | files |
| `session` | per-session counters for the reminder | files |
| `importer`, `doctor` | import workflow, health checks | via `store` |
| `gitops` | git subprocesses with timeouts (argv lists, `--` before URLs) | subprocess |
| `hooks` | hook entry points, fail-open wrapper, time budget | stdin/stdout |
| `cli` | argparse commands, exit codes | stdin/stdout |

Design rule: the pure modules (top half) hold the logic and have no I/O;
the outer modules are thin. That keeps the logic easy to test and the hooks
fast.

## Hook lifecycle

| Event | Handler | Output |
|---|---|---|
| `SessionStart` | load lessons, select by scope and rank, render | `additionalContext` with trigger lines |
| `UserPromptSubmit` | increment the session's prompt count; `/harvest` marks it harvested | none |
| `PostToolUse` (`Skill`) | `harvest` skill used: mark harvested | none |
| `Stop` | prompts ≥ `min_prompts`, not harvested, not yet reminded | `systemMessage` (to the user) |
| `PreCompact` | at least one prompt, not harvested, not yet reminded | `systemMessage` |

All hooks share one contract: read at most 1 MiB of JSON from stdin, finish
within 4 s (`SIGALRM`, plus `timeout` in `hooks.json`), never raise, always
exit 0. Errors are logged to `.state/stickit.log`. A hook that fails costs the
session nothing.

## Ranking

1. Keep `active` lessons whose scope matches this host or project.
2. Sort: project scope, then host, then universal; then lessons tagged with
   the project name; then most recently updated; then id (stable).
3. Fill the budget (`inject.budget` minus a fixed frame reserve) with your own
   lessons first, then imported ones. Anything left out is counted in a
   "+N more" line.

## Decisions

- **No generated index in git.** It would conflict on every sync between
  machines. One file per lesson keeps merges trivial.
- **Trigger lines, not bodies, at session start.** It costs very little per
  session, and Claude reads a body only when a trigger applies.
- **Shareable at save time, not only at export.** Personal details are
  refused when a lesson is written, so the store can itself be a public repo.
  Auto memory remains the place for private, machine-specific knowledge.
- **Export refuses secrets instead of redacting them.** A secret inside a
  lesson is a problem in your own store. Hiding it in the export would leave
  it in your git history.
- **Imports go to an inbox.** Text from other people is untrusted input that
  ends up in Claude's context, so a person reviews it first.
- **The CLI accepts JSON on stdin.** The harvest skill never has to
  shell-quote free text.
- **The reminder uses hook payloads, not transcripts.** Transcript files are
  an internal format. Hook inputs are documented.
