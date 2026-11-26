# Configuration

## Store location

| Source | Value |
|---|---|
| `--store PATH` (CLI only) | highest priority |
| `STICKIT_DIR` environment variable | e.g. `export STICKIT_DIR=~/notes/stickit` |
| default | `~/stickit-notes-data` |

The hooks run inside Claude Code, so set `STICKIT_DIR` where Claude Code
inherits it (your shell profile, or `env` in `~/.claude/settings.json`).

## `stickit.toml`

Created by `stickit init` with every key commented. All keys are optional.

```toml
store_version = 1

[inject]
budget = 6000        # max characters added to each session (500-9500; hook limit is 10000)

[remind]
min_prompts = 8      # remind to /harvest after this many prompts; 0 disables reminders

[redact]
extra = ["corp\\.internal", "build-\\d+"]   # extra regexes redacted on export
allow = ["webapp"]                           # strings never redacted
```

An invalid `stickit.toml` makes the session-start hook skip silently (logged)
and `stickit doctor` report the error.

## Other environment variables

| Variable | Effect |
|---|---|
| `STICKIT_DEBUG=1` | debug lines in `.state/stickit.log` |
| `STICKIT_TODAY=YYYY-MM-DD` | fixed "today", for tests and demos |

## Logs

Hooks never write to the terminal. Problems are logged to
`<store>/.state/stickit.log` (rotated at 256 KB).
