from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest

from conftest import LessonFactory
from stickit import redact
from stickit.context import Context
from stickit.session import (
    SessionState,
    SessionStore,
    is_harvest_prompt,
    is_harvest_skill,
    should_remind,
)

# ---- session -------------------------------------------------------------


def test_should_remind_rules() -> None:
    assert not should_remind(SessionState(prompts=7), min_prompts=8)
    assert should_remind(SessionState(prompts=8), min_prompts=8)
    assert not should_remind(SessionState(prompts=99, harvested=True), min_prompts=8)
    assert not should_remind(SessionState(prompts=99, reminded=True), min_prompts=8)
    assert not should_remind(SessionState(prompts=99), min_prompts=0)
    assert should_remind(SessionState(prompts=1), min_prompts=8, before_compact=True)
    assert not should_remind(SessionState(prompts=0), min_prompts=8, before_compact=True)


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("/harvest", True),
        ("  /harvest now please", True),
        ("/stickit-notes:harvest", True),
        ("/harvester", False),
        ("please /harvest", False),
        ("", False),
    ],
)
def test_is_harvest_prompt(prompt: str, expected: bool) -> None:
    assert is_harvest_prompt(prompt) is expected


def test_is_harvest_skill() -> None:
    assert is_harvest_skill("harvest")
    assert is_harvest_skill("stickit-notes:harvest")
    assert not is_harvest_skill("other:harvest")


def test_session_store_round_trip_and_safety(tmp_path: Path) -> None:
    sessions = SessionStore(tmp_path)
    fresh = sessions.load("new")
    assert (fresh.prompts, fresh.harvested, fresh.reminded) == (0, False, False)
    state = SessionState(prompts=3, harvested=True)
    sessions.save("../../etc/passwd", state)
    assert not (tmp_path.parent / "etc").exists()
    assert sessions.load("../../etc/passwd").prompts == 3
    (sessions.dir / "bad.json").write_text("{not json")
    assert sessions.load("bad").prompts == 0


def test_session_prune(tmp_path: Path) -> None:
    sessions = SessionStore(tmp_path)
    assert sessions.prune() == 0
    sessions.save("old", SessionState())
    sessions.save("new", SessionState())
    old = sessions.dir / "old.json"
    past = time.time() - 30 * 86400
    os.utime(old, (past, past))
    assert sessions.prune() == 1
    assert not old.exists()


# ---- redaction --------------------------------------------------------------

FAKE_SECRETS = {
    "anthropic-key": "sk-ant-api03-" + "a" * 30,
    "openai-style-key": "sk-proj-" + "B" * 30,
    "github-token": "ghp_" + "c" * 36,
    "huggingface-token": "hf_" + "D" * 34,
    "aws-access-key": "AKIA" + "E" * 16,
    "google-api-key": "AIza" + "f" * 35,
    "slack-token": "xoxb-" + "1" * 20,
    "private-key": "-----BEGIN RSA PRIVATE KEY-----",
    "jwt": "eyJ" + "a" * 12 + ".eyJ" + "b" * 12 + "." + "c" * 12,
    "bearer-token": "Bearer " + "z" * 30,
    "assigned-secret": "password = hunter2hunter2",
}


@pytest.mark.parametrize(("name", "secret"), list(FAKE_SECRETS.items()))
def test_find_secrets_detects(name: str, secret: str) -> None:
    assert name in redact.find_secrets(f"before {secret} after")


@pytest.mark.parametrize(
    "text",
    ["use the sk- prefix", "a task list", "token budget of 8 words", "the hf_ prefix", "AKIA"],
)
def test_find_secrets_ignores_lookalikes(text: str) -> None:
    assert redact.find_secrets(text) == []


def test_personal_redaction(ctx: Context) -> None:
    text = (
        f"Look in {ctx.home}/SAS and /home/alice/x. Host boxone at 192.168.1.20, "
        "fe80:0:0:0:200:f8ff:fe21:67cf, mail alice@example.com. "
        "Keep 127.0.0.1 and 0.0.0.0. Alice ran it. Alicevalue stays. Version 1.2.3 stays."
    )
    result = redact.redact(text, redact.personal_rules(ctx))
    assert "~/SAS" in result.text
    assert "~/x" in result.text
    assert "<host>" in result.text and "boxone" not in result.text
    assert "<ip>" in result.text and "192.168" not in result.text
    assert "fe80" not in result.text
    assert "<email>" in result.text
    assert "127.0.0.1" in result.text and "0.0.0.0" in result.text
    assert "<user> ran it" in result.text
    assert "Alicevalue" in result.text
    assert "1.2.3" in result.text
    assert result.hits["home-path"] == 2


def test_allow_list_and_extra_rules(ctx: Context) -> None:
    rules = redact.personal_rules(ctx, [re.compile(r"corp\.internal")])
    result = redact.redact("boxone-docs on boxone via api.corp.internal", rules, ["boxone-docs"])
    assert result.text == "boxone-docs on <host> via api.<redacted>"


def test_short_names_are_not_redacted(tmp_path: Path) -> None:
    ctx = Context(host="ab", project=None, home=tmp_path / "x", user="me")
    names = {r.name for r in redact.personal_rules(ctx)}
    assert "hostname" not in names and "username" not in names


def test_redact_lesson_and_personal_details(ctx: Context, make_lesson: LessonFactory) -> None:
    lesson = make_lesson(body=f"See {ctx.home}/notes on boxone, ask x@corp.example.com.")
    assert redact.personal_details(lesson, ctx) == ["email", "home-path", "hostname"]
    scoped = make_lesson(scope="host:boxone", body="boxone")
    assert redact.personal_details(scoped, ctx) == ["hostname"], "applies to every scope"
    assert redact.personal_details(scoped, ctx, allow=["boxone"]) == []
    assert redact.personal_details(
        make_lesson(body="internal.corp"), ctx, [re.compile(r"internal\.corp")]
    ) == ["custom"]
    assert redact.personal_details(make_lesson(), ctx) == []
    result = redact.redact_lesson(lesson, redact.personal_rules(ctx))
    assert "See ~/notes on <host>, ask <email>." in result.text
    assert result.hits == {"home-path": 1, "hostname": 1, "email": 1}
