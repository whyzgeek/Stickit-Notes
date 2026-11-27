# Stickit-Notes

**Shareable lessons learned for Claude Code.** `/harvest` turns what a session
taught into short, general lessons, each with a *trigger question*. They live
in a git repo you own (public if you like). Every new Claude Code session, on
any machine and for anyone who uses your lessons, starts with those questions
in mind, so the same mistake is not made twice.

```text
- Am I about to change a shared service's config before measuring and reporting? → measure-before-config-change
- Before the first commit of a repo I will publish, is git set to a noreply email? → public-repo-git-identity
```

[![CI](https://github.com/whyzgeek/stickit-notes/actions/workflows/ci.yml/badge.svg)](https://github.com/whyzgeek/stickit-notes/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Why

Claude Code's auto memory is tied to one project folder on one machine, and
it is private. Lessons that would help everyone (yourself on another machine,
a teammate, the community) never leave it. stickit-notes is the other half:
auto memory keeps what is personal or machine-specific; stickit-notes keeps
general lessons, small enough to load into every session and clean enough to
publish.

- **Cheap:** a session gets one line per lesson (a question and an id), under
  6,000 characters. Claude reads the full lesson only when a question applies.
- **Portable:** the store is a plain git repo of Markdown files. Clone it on a
  new machine and you are done.
- **Shareable by construction:** a lesson is refused when saved if it
  contains a secret or personal details (home paths, user and host names,
  emails, IP addresses), so the store is always safe to publish. `/harvest`
  proposes only lessons that would help someone else.
- **Safe to receive:** lessons from others land in an inbox until you review
  them, and are labeled as someone else's text in your sessions.
- **No dependencies:** Python 3.11+ standard library only. No network calls
  except an explicit `/stickit sync`.

## Install

In Claude Code:

```text
/plugin marketplace add whyzgeek/stickit-notes
/plugin install stickit-notes@stickit-notes
```

Then create your store (once):

```text
/stickit init
```

This creates `~/stickit-notes-data` as a git repo. To use it on other
machines and share it, create an **empty** repository (public if you want
others to use your lessons) and pass it as the remote:
`/stickit init --remote git@github.com:<you>/my-stickit-notes.git`, then
`/stickit sync`.

### On another machine

```text
/plugin marketplace add whyzgeek/stickit-notes
/plugin install stickit-notes@stickit-notes
/stickit init --clone git@github.com:<you>/my-stickit-notes.git
```

`--clone` puts your notes where the hooks look for them. Until it is done,
each session shows a one-line hint.

## Use

| You run | What happens |
|---|---|
| `/harvest` | Claude reviews the session and the project's auto memory (read-only), proposes the lessons that would help someone else, and saves the ones you pick. |
| `/stickit` | List, search, show, edit, deprecate, `doctor`, export, import, review and sync lessons. |
| `/stickit graduate <id>` | A lesson you always want applied becomes a standing instruction in `~/.claude/CLAUDE.md` (or the project's `CLAUDE.md` / `AGENTS.md`). It stays in the store for sharing but is no longer injected twice. `--undo` reverses it. |
| *(automatic)* | At session start the matching triggers are added to context. After a substantial session without `/harvest` you get one reminder. |

Lessons are Markdown files with YAML front matter (see
[docs/LESSON-FORMAT.md](docs/LESSON-FORMAT.md)), readable on GitHub and in
Obsidian:

```markdown
---
schema: 1
id: measure-before-config-change
uid: 01JDXQ8Z0V7Q4M2N6P3R5S7T9W
trigger: Am I about to change a shared service's config before measuring and reporting?
scope: universal
tags: [workflow, infra]
status: active
superseded_by:
related: []
created: 2026-11-26
updated: 2026-11-26
review_after:
origin: own
---
Measure the current state and report before changing the config of a shared service.
**Why:** an unreviewed context-size change ran a GPU server out of memory.
**How to apply:** measure, write the report, wait for approval, then change.
```

## Sharing lessons

The simplest way is to make your store's remote a public repository: others
clone it, or import from it. For a selection, export a file:

```text
/stickit export --out lessons.md          # all universal lessons, redacted, as one bundle
/stickit export measure-before-config-change --out one.md
```

Export runs the same personal-detail redaction once more (useful for lessons
saved with `--allow-personal`) and shows a diff of anything it changed. Send
the file however you like. The recipient runs:

```text
/stickit import lessons.md --label alice
/stickit review          # read each one
/stickit promote <id>    # or: /stickit drop <id>
```

Imported lessons are tagged `origin: imported:<label>`. In sessions they are
listed separately, labeled as reference data written by someone else, and
they can never push your own lessons out of the budget.

## Command line

Everything the skills do goes through one CLI. To use it in a terminal, run
it from a clone (no install needed) or install it:

```bash
git clone https://github.com/whyzgeek/stickit-notes && cd stickit-notes
python3 bin/stickit --help          # straight from the checkout
pipx install .  &&  stickit --help  # or as a command on PATH
```

`init` · `new` · `add` · `update` · `deprecate` · `remove` · `graduate` · `list` · `show` · `search` ·
`doctor` · `context` · `export` · `import` · `review` · `promote` · `drop` ·
`sync` · `migrate`. Exit codes: `0` ok, `1` invalid input, `2` store or git
error, `3` export refused (possible secret).

## Scopes

Lessons can be `universal` (default), `host:<name>` or `project:<name>`. A
scoped lesson only shows up on that host or in that project. `/harvest` does
not propose scoped lessons, since that knowledge usually belongs in auto memory,
but you can create them with `/stickit` if you want machine-specific notes to
travel with your store.

## Configuration

The store location is `$STICKIT_DIR`, or `~/stickit-notes-data` by default. The store's
`stickit.toml` holds the injection budget, the reminder threshold and extra
redaction rules. See [docs/CONFIG.md](docs/CONFIG.md).

## Platform support

Linux and macOS, with Python 3.11 or newer as `python3`. If `python3` is
older, the hooks stay silent and the CLI prints a version hint. Windows is
untested.

## Documentation

- [Architecture](docs/ARCHITECTURE.md): components, hook lifecycle, design decisions
- [Lesson format](docs/LESSON-FORMAT.md): the versioned file and bundle spec
- [Configuration](docs/CONFIG.md)
- [Security](SECURITY.md): threat model and how to report a vulnerability
- [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE)
