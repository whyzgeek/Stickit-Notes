"""Claude Code hook entry points: ``stickit hook <event>`` with the payload on stdin.

Contract: a hook never breaks a session. Every failure (bad payload, broken
store, timeout, bug) is logged and the process exits 0 with no output.
"""

from __future__ import annotations

import json
import signal
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from types import FrameType
from typing import Any, TextIO

from stickit import config as config_mod
from stickit import context, ranking, render
from stickit.log import configure as configure_log
from stickit.log import get as get_log
from stickit.session import (
    SessionStore,
    is_harvest_prompt,
    is_harvest_skill,
    should_remind,
)
from stickit.store import Area, Store

TIME_BUDGET_S = 4
MAX_PAYLOAD = 1024 * 1024
REMIND_MESSAGE = (
    "stickit-notes: this session may hold lessons worth keeping. "
    "Run /harvest to save them (shown once per session)."
)

Payload = Mapping[str, Any]
Output = dict[str, Any] | None


class _HookTimeoutError(Exception):
    pass


def _on_alarm(signum: int, frame: FrameType | None) -> None:
    raise _HookTimeoutError


def main(
    event: str,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(TIME_BUDGET_S)
    try:
        raw = stdin.read(MAX_PAYLOAD)
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
        result = dispatch(event, payload, env=env)
        if result is not None:
            stdout.write(json.dumps(result))
            stdout.flush()
    except _HookTimeoutError:
        get_log().warning("hook %s exceeded %ss and was skipped", event, TIME_BUDGET_S)
    except Exception:  # fail open: a hook must never break the session
        get_log().exception("hook %s failed", event)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    return 0


def dispatch(event: str, payload: Payload, *, env: Mapping[str, str] | None = None) -> Output:
    handler = HANDLERS.get(event)
    if handler is None:
        get_log().warning("unknown hook event %r", event)
        return None
    root = config_mod.resolve_store_root(env)
    if not Store.is_store(root):
        configure_log(None)
        if event == "session-start":
            return _context_output(render.missing_store_hint(root))
        return None
    store = Store(root)
    configure_log(store.state_dir)
    get_log().debug("hook %s, payload keys: %s", event, sorted(payload))
    return handler(store, payload)


def _context_output(text: str) -> Output:
    if not text:
        return None
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}


def _session_id(payload: Payload) -> str:
    value = payload.get("session_id")
    return value if isinstance(value, str) and value else "unknown"


def on_session_start(store: Store, payload: Payload) -> Output:
    cfg = store.config()
    cwd = payload.get("cwd")
    ctx = context.detect(Path(cwd) if isinstance(cwd, str) and cwd else None)
    loaded = store.load_all()
    for error in loaded.errors:
        get_log().warning("invalid lesson skipped: %s", error)
    selection = ranking.select(
        loaded.lessons,
        ctx,
        budget=cfg.inject_budget - render.FRAME_RESERVE,
        cost=render.line_cost,
    )
    sessions = SessionStore(store.state_dir)
    sessions.prune()
    sid = _session_id(payload)
    sessions.save(sid, sessions.load(sid))  # keep counters across resume/compact
    text = render.inject(
        selection, lessons_dir=store.area_dir(Area.LESSONS), invalid=len(loaded.errors)
    )
    return _context_output(text)


def on_user_prompt(store: Store, payload: Payload) -> Output:
    sessions = SessionStore(store.state_dir)
    sid = _session_id(payload)
    state = sessions.load(sid)
    state.prompts += 1
    prompt = payload.get("prompt", payload.get("user_prompt", ""))
    if isinstance(prompt, str) and is_harvest_prompt(prompt):
        state.harvested = True
    sessions.save(sid, state)
    return None


def on_post_tool_use(store: Store, payload: Payload) -> Output:
    if payload.get("tool_name") != "Skill":
        return None
    tool_input = payload.get("tool_input")
    skill = tool_input.get("skill") if isinstance(tool_input, dict) else None
    get_log().debug("Skill tool used: %r (input keys: %s)", skill, sorted(tool_input or {}))
    if isinstance(skill, str) and is_harvest_skill(skill):
        sessions = SessionStore(store.state_dir)
        sid = _session_id(payload)
        state = sessions.load(sid)
        state.harvested = True
        sessions.save(sid, state)
    return None


def _remind(store: Store, payload: Payload, *, before_compact: bool) -> Output:
    if payload.get("stop_hook_active"):
        return None
    sessions = SessionStore(store.state_dir)
    sid = _session_id(payload)
    state = sessions.load(sid)
    min_prompts = store.config().remind_min_prompts
    if not should_remind(state, min_prompts=min_prompts, before_compact=before_compact):
        return None
    state.reminded = True
    sessions.save(sid, state)
    return {"systemMessage": REMIND_MESSAGE}


def on_stop(store: Store, payload: Payload) -> Output:
    return _remind(store, payload, before_compact=False)


def on_pre_compact(store: Store, payload: Payload) -> Output:
    return _remind(store, payload, before_compact=True)


HANDLERS: dict[str, Callable[[Store, Payload], Output]] = {
    "session-start": on_session_start,
    "user-prompt": on_user_prompt,
    "post-tool-use": on_post_tool_use,
    "stop": on_stop,
    "pre-compact": on_pre_compact,
}
