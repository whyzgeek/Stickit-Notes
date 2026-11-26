"""Hook contract: valid JSON or nothing on stdout, exit 0 always, fast."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import LessonFactory, payload
from stickit import hooks
from stickit.model import Lesson
from stickit.session import SessionStore
from stickit.store import Area, Store

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ["session-start", "user-prompt", "post-tool-use", "stop", "pre-compact"]
FIXTURE_FOR = {
    "session-start": "session_start",
    "user-prompt": "user_prompt",
    "post-tool-use": "post_tool_use_skill",
    "stop": "stop",
    "pre-compact": "pre_compact",
}


def run_hook(event: str, stdin: str) -> tuple[int, str]:
    out = io.StringIO()
    code = hooks.main(event, stdin=io.StringIO(stdin), stdout=out)
    return code, out.getvalue()


def test_missing_store_session_start_gives_hint() -> None:
    code, out = run_hook("session-start", payload("session_start"))
    assert code == 0
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "No stickit-notes store" in context


@pytest.mark.parametrize("event", EVENTS[1:])
def test_missing_store_other_hooks_are_silent(event: str) -> None:
    assert run_hook(event, payload(FIXTURE_FOR[event])) == (0, "")


def test_session_start_injects_applicable_lessons(
    store: Store, make_lesson: LessonFactory, tmp_path: Path
) -> None:
    project = tmp_path / "webapp"
    (project / ".git").mkdir(parents=True)
    store.save(make_lesson(id="everywhere"))
    store.save(make_lesson(id="this-project", scope="project:webapp"))
    store.save(make_lesson(id="other-project", scope="project:other"))
    store.save(make_lesson(id="inbox-only"), Area.INBOX)
    (store.area_dir(Area.LESSONS) / "broken.md").write_text("junk")
    code, out = run_hook("session-start", payload("session_start", cwd=str(project)))
    assert code == 0
    data = json.loads(out)
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    context = data["hookSpecificOutput"]["additionalContext"]
    assert "→ everywhere" in context
    assert "→ this-project [project]" in context
    assert "other-project" not in context
    assert "inbox-only" not in context
    assert "1 lesson file(s) are invalid" in context


def test_session_start_respects_budget(store: Store, make_lesson: LessonFactory) -> None:
    for i in range(300):
        store.save(make_lesson(id=f"l-{i}", trigger=f"Is lesson number {i} relevant here now?"))
    _, out = run_hook("session-start", payload("session_start"))
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert len(context) <= store.config().inject_budget
    assert "more lessons not shown" in context


def test_session_start_empty_store_is_silent(store: Store) -> None:
    assert run_hook("session-start", payload("session_start")) == (0, "")


def test_reminder_flow(store: Store) -> None:
    for _ in range(7):
        run_hook("user-prompt", payload("user_prompt"))
    assert run_hook("stop", payload("stop")) == (0, "")
    run_hook("user-prompt", payload("user_prompt"))
    _, out = run_hook("stop", payload("stop"))
    assert "/harvest" in json.loads(out)["systemMessage"]
    assert run_hook("stop", payload("stop")) == (0, ""), "only once per session"
    assert run_hook("pre-compact", payload("pre_compact")) == (0, "")


def test_no_reminder_after_harvest_prompt(store: Store) -> None:
    for _ in range(10):
        run_hook("user-prompt", payload("user_prompt"))
    run_hook("user-prompt", payload("user_prompt_harvest"))
    assert run_hook("stop", payload("stop")) == (0, "")


def test_no_reminder_after_harvest_skill(store: Store) -> None:
    for _ in range(10):
        run_hook("user-prompt", payload("user_prompt"))
    run_hook("post-tool-use", payload("post_tool_use_bash"))
    assert SessionStore(store.state_dir).load("sess-1").harvested is False
    run_hook("post-tool-use", payload("post_tool_use_skill"))
    assert SessionStore(store.state_dir).load("sess-1").harvested is True
    assert run_hook("stop", payload("stop")) == (0, "")


def test_pre_compact_reminds_early(store: Store) -> None:
    run_hook("user-prompt", payload("user_prompt"))
    _, out = run_hook("pre-compact", payload("pre_compact"))
    assert "systemMessage" in json.loads(out)


def test_stop_hook_active_is_respected(store: Store) -> None:
    for _ in range(10):
        run_hook("user-prompt", payload("user_prompt"))
    assert run_hook("stop", payload("stop", stop_hook_active=True)) == (0, "")


def test_sessions_are_independent(store: Store) -> None:
    for _ in range(8):
        run_hook("user-prompt", payload("user_prompt", session_id="a"))
    assert run_hook("stop", payload("stop", session_id="b")) == (0, "")
    assert run_hook("stop", payload("stop", session_id="a"))[1]


@pytest.mark.parametrize("stdin", ["", "not json", "[1, 2]", '"str"', "{" * 50])
@pytest.mark.parametrize("event", EVENTS)
def test_garbage_payload_never_fails(store: Store, event: str, stdin: str) -> None:
    code, out = run_hook(event, stdin)
    assert code == 0
    if out:
        json.loads(out)


def test_broken_config_fails_open(store: Store) -> None:
    store.config_path.write_text("inject = = broken")
    assert run_hook("session-start", payload("session_start")) == (0, "")
    assert "hook session-start failed" in (store.state_dir / "stickit.log").read_text()


def test_unknown_event_is_ignored(store: Store) -> None:
    assert hooks.dispatch("nope", {}) is None


def test_timeout_is_caught(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(store: Store, payload: object) -> None:
        raise hooks._HookTimeoutError

    monkeypatch.setitem(hooks.HANDLERS, "stop", slow)
    assert run_hook("stop", payload("stop")) == (0, "")


def test_launcher_end_to_end_and_speed(store: Store, make_lesson: LessonFactory) -> None:
    """Through bin/stickit as Claude Code runs it; 500 lessons stay well under budget."""
    for i in range(500):
        lesson: Lesson = make_lesson(id=f"l-{i}")
        store.save(lesson)
    started = time.perf_counter()
    done = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "stickit"), "hook", "session-start"],
        input=payload("session_start"),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    elapsed = time.perf_counter() - started
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
    assert done.stderr == ""
    assert elapsed < 2.0, f"session-start took {elapsed:.2f}s"
