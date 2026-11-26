# Contributing

Thanks for helping. Bug reports, ideas and pull requests are welcome.

## Development setup

```bash
git clone https://github.com/whyzgeek/stickit-notes && cd stickit-notes
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pre-commit install            # optional: runs ruff on commit
```

## Checks (same as CI)

```bash
ruff check . && ruff format --check .
mypy                     # strict
pytest --cov             # coverage must stay >= 90%
claude plugin validate . # if Claude Code is installed
```

Tests never touch your real store: `tests/conftest.py` points `STICKIT_DIR`,
the git config and "today" at temporary values.

## Try your checkout in Claude Code

```text
/plugin marketplace add /path/to/stickit-notes
/plugin install stickit-notes@stickit-notes
```

Use a scratch store while experimenting: `export STICKIT_DIR=/tmp/stickit-dev`
before starting `claude`.

## Guidelines

- **Runtime dependencies stay at zero.** Standard library only, Python 3.11+.
- **Hooks must fail open.** Any new hook path catches its errors, stays fast,
  and has a contract test in `tests/test_hooks.py`.
- **Keep the logic pure.** Put it in the I/O-free modules (`model`,
  `ranking`, `render`, `redact`, `bundle`) and keep `cli`/`hooks` thin.
- **Format changes** go in `docs/LESSON-FORMAT.md` first, bump the schema
  version, and come with a migration.
- **Skills** (`skills/*/SKILL.md`) are prompts. Keep them short, and update
  or add a case in `evals/` when you change behavior.
- Add a line to `CHANGELOG.md` under *Unreleased*.

## Releasing (maintainers)

1. Update `version` in `.claude-plugin/plugin.json`, `pyproject.toml` and
   `src/stickit/__init__.py`, and move *Unreleased* to the new version in
   `CHANGELOG.md`.
2. Tag `vX.Y.Z` and push the tag. The release workflow checks that the
   versions match and publishes the GitHub release.
