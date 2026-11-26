"""Graduating lessons into CLAUDE.md / AGENTS.md."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import LessonFactory, RunCli
from stickit import graduate
from stickit.errors import ValidationError
from stickit.model import Status
from stickit.store import Store

BODY = (
    "Measure before you change anything.\n"
    "**Why:** it broke once.\n"
    "**How to apply:** measure, report, then change."
)


def test_entry_is_one_line_with_rule_and_how(make_lesson: LessonFactory) -> None:
    line = graduate.entry(make_lesson(id="m", trigger="Am I measuring first?", body=BODY))
    assert line == (
        "- **Am I measuring first?** Measure before you change anything. "
        "How to apply: measure, report, then change. <!-- stickit:m -->"
    )
    plain = graduate.entry(make_lesson(id="p", body="Just\n  a rule."))
    assert plain.endswith("Just a rule. <!-- stickit:p -->")


def test_upsert_creates_appends_replaces_and_keeps_user_text(make_lesson: LessonFactory) -> None:
    a = make_lesson(id="a")
    b = make_lesson(id="b")
    doc = graduate.upsert("", a)
    assert doc.startswith(graduate.BEGIN) and doc.endswith(graduate.END + "\n")
    own = "# My rules\n\n- keep this\n"
    doc = graduate.upsert(own, a)
    assert doc.startswith(own.rstrip("\n"))
    doc = graduate.upsert(doc + "\n## After\ntext\n", b)
    assert graduate.ids(doc) == ["a", "b"]
    assert doc.rstrip().endswith("## After\ntext")
    doc = graduate.upsert(doc, a.with_changes(body="Changed rule."))
    assert graduate.ids(doc) == ["a", "b"]
    assert "Changed rule." in doc and doc.count("<!-- stickit:a -->") == 1


def test_remove_and_empty_block_disappears(make_lesson: LessonFactory) -> None:
    own = "# Mine\n"
    doc = graduate.upsert(graduate.upsert(own, make_lesson(id="a")), make_lesson(id="b"))
    doc = graduate.remove(doc, "a")
    assert graduate.ids(doc) == ["b"]
    assert graduate.remove(doc, "b") == own
    with pytest.raises(ValidationError, match="not in this file"):
        graduate.remove(own, "b")


@pytest.mark.parametrize(
    "doc",
    [
        f"{graduate.BEGIN}\n",
        f"{graduate.END}\n{graduate.BEGIN}\n",
        f"{graduate.BEGIN}\n{graduate.BEGIN}\n{graduate.END}\n",
    ],
)
def test_damaged_markers_are_refused(doc: str, make_lesson: LessonFactory) -> None:
    with pytest.raises(ValidationError, match="damaged"):
        graduate.upsert(doc, make_lesson())
    assert graduate.ids("no block here") == []


def _new(run_cli: RunCli, lesson_id: str, *extra: str) -> None:
    result = run_cli(
        "new",
        "--id",
        lesson_id,
        "--trigger",
        f"Is {lesson_id} relevant?",
        *extra,
        "--body-file",
        "-",
        stdin=BODY,
    )
    assert result.code == 0, result.err


def test_graduate_universal_goes_to_user_claude_md(
    run_cli: RunCli, store_root: Path, tmp_path: Path
) -> None:
    assert run_cli("init").code == 0
    _new(run_cli, "measure")
    target = tmp_path / "claude-config" / "CLAUDE.md"
    dry = run_cli("graduate", "measure", "--dry-run")
    assert dry.code == 0 and "+- **Is measure relevant?**" in dry.out
    assert not target.exists()
    assert run_cli("graduate", "measure").code == 0
    assert graduate.ids(target.read_text()) == ["measure"]
    store = Store(store_root)
    assert store.get("measure").status is Status.GRADUATED
    assert "measure" not in run_cli("hook", "session-start", stdin="{}").out
    assert run_cli("graduate", "measure").code == 0, "re-graduating refreshes the entry"
    assert run_cli("export", "--out", str(tmp_path / "x.md")).code == 0, "still shareable"
    undo = run_cli("graduate", "measure", "--undo")
    assert undo.code == 0
    assert target.read_text() == ""
    assert store.get("measure").status is Status.ACTIVE
    assert run_cli("graduate", "measure", "--undo").code == 1


def test_graduate_project_lesson_and_agents_md(run_cli: RunCli, tmp_path: Path) -> None:
    assert run_cli("init").code == 0
    project = tmp_path / "webapp"
    (project / ".git").mkdir(parents=True)
    (project / "src").mkdir()
    (project / "CLAUDE.md").write_text("# Project rules\n")
    _new(run_cli, "proj-rule", "--scope", "project:webapp")
    _new(run_cli, "shared")
    assert run_cli("graduate", "proj-rule", cwd=project / "src").code == 0
    assert graduate.ids((project / "CLAUDE.md").read_text()) == ["proj-rule"]
    assert (project / "CLAUDE.md").read_text().startswith("# Project rules\n")
    assert run_cli("graduate", "shared", "--agents", "--to", "project", cwd=project).code == 0
    assert graduate.ids((project / "AGENTS.md").read_text()) == ["shared"]
    assert run_cli("graduate", "shared", "--agents").code == 1, "no user-level AGENTS.md"
    custom = tmp_path / "notes" / "RULES.md"
    assert run_cli("graduate", "shared", "--file", str(custom)).code == 0
    assert graduate.ids(custom.read_text()) == ["shared"]


def test_graduate_refusals(run_cli: RunCli, tmp_path: Path) -> None:
    assert run_cli("init").code == 0
    _new(run_cli, "old")
    run_cli("deprecate", "old")
    assert "cannot graduate" in run_cli("graduate", "old").err
    _new(run_cli, "p", "--scope", "project:x")
    assert "not inside a project" in run_cli("graduate", "p", cwd=Path("/")).err
    assert run_cli("graduate", "missing").code == 2
