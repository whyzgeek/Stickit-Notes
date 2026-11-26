# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-26

### Added
- Lesson format schema 1 (Markdown and YAML front matter) with trigger questions,
  scopes (`universal`, `host:`, `project:`), status, ULID identity, and a bundle format v1.
- `/harvest` skill: distills lessons from the current session and the project's
  auto memory (read-only), with user approval for each lesson.
- `/stickit` skill and `stickit` CLI: `init` (including `--clone`), `new`, `add`,
  `update`, `deprecate`, `list`, `show`, `search`, `doctor`, `context`, `export`,
  `import`, `review`, `promote`, `drop`, `sync`, `migrate`.
- Hooks: trigger injection at session start within a budget; one harvest
  reminder per substantial session (end of turn and before compaction).
- Lessons are shareable by construction: saving refuses secrets and personal
  details (paths, user and host names, emails, IPs, custom rules) in any lesson
  unless `--allow-personal`; `/harvest` proposes only lessons that would help
  someone else.
- Export redaction and refusal on secret patterns; quarantined imports with review.
- `remove` command.
- `graduate` command: turns a lesson into a standing instruction in the user's
  `~/.claude/CLAUDE.md`, a project's `CLAUDE.md`/`AGENTS.md`, or any file, inside
  a managed block; the lesson becomes `graduated` (not injected, still shareable);
  `--undo` reverses it.

[Unreleased]: https://github.com/whyzgeek/stickit-notes/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/whyzgeek/stickit-notes/releases/tag/v0.1.0
