from __future__ import annotations

import datetime as dt

import pytest

from conftest import LessonFactory
from stickit.errors import ValidationError
from stickit.model import (
    UID_RE,
    Lesson,
    Scope,
    ScopeKind,
    Status,
    new_uid,
    slugify,
    today,
)


def test_round_trip_preserves_every_field(make_lesson: LessonFactory) -> None:
    lesson = make_lesson(
        scope="project:webapp",
        tags=("infra", "workflow"),
        related=("other-one",),
        review_after=dt.date(2027, 1, 1),
        status=Status.SUPERSEDED,
        superseded_by="newer",
        origin="imported:alice",
        body="Line one.\n\n---\n\nAfter a rule line.",
    )
    assert Lesson.from_text(lesson.to_text()) == lesson


def test_to_text_has_stable_field_order(make_lesson: LessonFactory) -> None:
    text = make_lesson().to_text()
    keys = [line.split(":")[0] for line in text.splitlines()[1:14]]
    assert keys[:4] == ["schema", "id", "uid", "trigger"]
    assert keys[-1] == "origin"


def test_minimal_file_uses_defaults() -> None:
    text = (
        "---\nschema: 1\nid: x\nuid: 01JDX0000000000000000000AB\n"
        "trigger: Is it so?\nscope: universal\ncreated: 2026-01-01\n"
        "updated: 2026-01-02\n---\nBody\n"
    )
    lesson = Lesson.from_text(text)
    assert lesson.status is Status.ACTIVE
    assert lesson.tags == ()
    assert lesson.origin == "own"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"id": "Bad Id"}, "lowercase slug"),
        ({"id": "-x"}, "lowercase slug"),
        ({"uid": "nope"}, "ULID"),
        ({"trigger": "Not a question"}, "question"),
        ({"trigger": "x" * 300 + "?"}, "one line"),
        ({"trigger": "two\nlines?"}, "one line"),
        ({"body": "   "}, "body is empty"),
        ({"body": "x" * 9000}, "longer than"),
        ({"tags": ("Bad Tag",)}, "tags"),
        ({"tags": ("a", "a")}, "duplicate tags"),
        ({"related": ("Not Id",)}, "related"),
        ({"status": Status.SUPERSEDED}, "superseded_by"),
        ({"superseded_by": "Bad Id"}, "superseded_by must"),
        ({"id": "same", "superseded_by": "same"}, "itself"),
        ({"created": dt.date(2026, 2, 1), "updated": dt.date(2026, 1, 1)}, "before created"),
        ({"origin": "stolen"}, "origin"),
        ({"body": "bell \x07"}, "control"),
        ({"schema": 2}, "unsupported schema"),
    ],
)
def test_validation_rules(
    make_lesson: LessonFactory, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        make_lesson(**overrides)


def test_from_text_rejects_unknown_fields(make_lesson: LessonFactory) -> None:
    text = make_lesson().to_text().replace("origin: own", "origin: own\ncolor: red")
    with pytest.raises(ValidationError, match="unknown field"):
        Lesson.from_text(text, source="f.md")


def test_from_text_rejects_newer_schema(make_lesson: LessonFactory) -> None:
    text = make_lesson().to_text().replace("schema: 1", "schema: 9")
    with pytest.raises(ValidationError, match="newer than this stickit"):
        Lesson.from_text(text, source="f.md")


@pytest.mark.parametrize(
    ("find", "replace", "message"),
    [
        ("schema: 1", "schema: one", "invalid value"),
        ("status: active", "status: sleeping", "status must be"),
        ("created: 2026-01-01", "created: yesterday", "YYYY-MM-DD"),
        ("tags: []", "tags: single", "must be a list"),
        ("origin: own", "origin: [a]", "single value"),
        ("trigger: ", "trigger_x: ", "unknown field"),
    ],
)
def test_from_text_field_errors_name_the_source(
    make_lesson: LessonFactory, find: str, replace: str, message: str
) -> None:
    text = make_lesson().to_text().replace(find, replace, 1)
    with pytest.raises(ValidationError, match=message) as info:
        Lesson.from_text(text, source="f.md")
    assert "f.md" in str(info.value)


def test_missing_required_field(make_lesson: LessonFactory) -> None:
    text = "\n".join(
        line for line in make_lesson().to_text().splitlines() if not line.startswith("uid:")
    )
    with pytest.raises(ValidationError, match="'uid'"):
        Lesson.from_text(text + "\n")


def test_with_changes_bumps_updated(make_lesson: LessonFactory) -> None:
    lesson = make_lesson()
    assert lesson.with_changes(body="new body").updated == today()
    assert lesson.with_changes(body="x", updated=lesson.updated).updated == lesson.updated


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("universal", ScopeKind.UNIVERSAL, None),
        ("host:BoxOne", ScopeKind.HOST, "boxone"),
        ("project:web.app_2", ScopeKind.PROJECT, "web.app_2"),
    ],
)
def test_scope_parse(text: str, kind: ScopeKind, value: str | None) -> None:
    scope = Scope.parse(text)
    assert (scope.kind, scope.value) == (kind, value)
    assert Scope.parse(str(scope)) == scope


@pytest.mark.parametrize("text", ["everywhere", "host:", "team:x", "host:bad name", "host:-x"])
def test_scope_parse_rejects(text: str) -> None:
    with pytest.raises(ValidationError):
        Scope.parse(text)


def test_scope_specificity_orders_project_host_universal() -> None:
    order = [Scope.parse(s).specificity for s in ("project:a", "host:b", "universal")]
    assert order == sorted(order, reverse=True)


def test_new_uid_is_ulid_and_time_ordered() -> None:
    a = new_uid(now_ms=1, randbytes=bytes(10))
    b = new_uid(now_ms=2, randbytes=bytes(10))
    assert UID_RE.match(a) and UID_RE.match(b)
    assert a < b
    assert UID_RE.match(new_uid())
    with pytest.raises(ValueError, match="48-bit"):
        new_uid(now_ms=-1)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Am I about to change a config?", "am-i-about-to-change-a-config"),
        ("!!!", "lesson"),
        ("a" * 80, "a" * 48),
        (
            "Before benchmarking, have I checked that no other model is loaded on the GPU?",
            "before-benchmarking-have-i-checked-that-no-other",
        ),
    ],
)
def test_slugify(text: str, expected: str) -> None:
    assert slugify(text) == expected


def test_today_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STICKIT_TODAY", "2030-05-06")
    assert today() == dt.date(2030, 5, 6)
    monkeypatch.delenv("STICKIT_TODAY")
    assert today() == dt.date.today()
