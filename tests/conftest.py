from __future__ import annotations

import datetime as dt
import io
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from stickit import cli
from stickit.context import Context
from stickit.model import Lesson, Scope, new_uid
from stickit.store import Store

FIXTURES = Path(__file__).parent / "fixtures"

LessonFactory = Callable[..., Lesson]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No test may touch the real store, git identity or date."""
    monkeypatch.setenv("STICKIT_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("STICKIT_TODAY", "2026-11-26")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    (tmp_path / "gitconfig").write_text(
        "[user]\n\tname = Test\n\temail = test@example.invalid\n[init]\n\tdefaultBranch = main\n"
    )
    monkeypatch.delenv("STICKIT_DEBUG", raising=False)


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "store"


@pytest.fixture
def store(store_root: Path) -> Store:
    return Store.create(store_root)


@pytest.fixture
def ctx(tmp_path: Path) -> Context:
    return Context(host="boxone", project="webapp", home=tmp_path / "home" / "alice", user="alice")


@pytest.fixture
def make_lesson() -> LessonFactory:
    counter = iter(range(10_000))

    def factory(**overrides: Any) -> Lesson:
        n = next(counter)
        fields: dict[str, Any] = {
            "id": f"lesson-{n}",
            "uid": new_uid(now_ms=1_700_000_000_000 + n, randbytes=n.to_bytes(10, "big")),
            "trigger": f"Am I about to do thing {n}?",
            "body": f"Do it carefully, case {n}.\n**Why:** reasons.",
            "created": dt.date(2026, 1, 1),
            "updated": dt.date(2026, 1, 1),
        }
        if "scope" in overrides and isinstance(overrides["scope"], str):
            overrides["scope"] = Scope.parse(overrides["scope"])
        fields.update(overrides)
        return Lesson(**fields)

    return factory


class Result:
    def __init__(self, code: int, out: str, err: str) -> None:
        self.code, self.out, self.err = code, out, err


RunCli = Callable[..., Result]


@pytest.fixture
def run_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RunCli:
    def runner(*argv: str, stdin: str = "", cwd: Path | None = None) -> Result:
        out, err = io.StringIO(), io.StringIO()
        app = cli.App(
            env=dict(os.environ),
            cwd=cwd or tmp_path,
            out=out,
            err=err,
            stdin=io.StringIO(stdin),
        )
        code = cli.main(list(argv), app)
        return Result(code, out.getvalue(), err.getvalue())

    return runner


def payload(name: str, **changes: Any) -> str:
    data = json.loads((FIXTURES / "hooks" / f"{name}.json").read_text())
    data.update(changes)
    return json.dumps(data)


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=30
    ).stdout
