"""The Lesson value object and its on-disk format (schema v1).

The format is specified in docs/LESSON-FORMAT.md; this module is its reference
implementation. Lessons are immutable; "editing" one means building a new one
with :func:`dataclasses.replace` and saving it.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import os
import re
import secrets
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from stickit import frontmatter
from stickit.errors import ValidationError

SCHEMA_VERSION = 1

ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
SCOPE_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ORIGIN_RE = re.compile(r"^(?:own|imported:[A-Za-z0-9][A-Za-z0-9._-]{0,63})$")
UID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

MAX_TRIGGER = 200
MAX_BODY = 8000
MAX_TAGS = 12
MAX_RELATED = 20

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_FIELD_ORDER = (
    "schema",
    "id",
    "uid",
    "trigger",
    "scope",
    "tags",
    "status",
    "superseded_by",
    "related",
    "created",
    "updated",
    "review_after",
    "origin",
)


def today() -> dt.date:
    """Today's date; ``STICKIT_TODAY`` overrides it for reproducible tests and demos."""
    override = os.environ.get("STICKIT_TODAY")
    return dt.date.fromisoformat(override) if override else dt.date.today()


class Status(enum.StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"
    GRADUATED = "graduated"  # now a standing instruction in CLAUDE.md / AGENTS.md


class ScopeKind(enum.StrEnum):
    UNIVERSAL = "universal"
    HOST = "host"
    PROJECT = "project"


@dataclass(frozen=True, slots=True)
class Scope:
    """Where a lesson applies: everywhere, on one host, or in one project."""

    kind: ScopeKind
    value: str | None = None

    @classmethod
    def parse(cls, text: str) -> Scope:
        text = text.strip()
        if text == ScopeKind.UNIVERSAL:
            return cls(ScopeKind.UNIVERSAL)
        kind, sep, value = text.partition(":")
        if not sep or kind not in (ScopeKind.HOST, ScopeKind.PROJECT):
            raise ValidationError(
                f"scope must be universal, host:<name> or project:<name>: {text!r}"
            )
        if not SCOPE_VALUE_RE.match(value):
            raise ValidationError(f"invalid scope name {value!r}")
        return cls(ScopeKind(kind), value.lower())

    def __str__(self) -> str:
        return self.kind.value if self.value is None else f"{self.kind.value}:{self.value}"

    @property
    def specificity(self) -> int:
        return {ScopeKind.UNIVERSAL: 0, ScopeKind.HOST: 1, ScopeKind.PROJECT: 2}[self.kind]


UNIVERSAL = Scope(ScopeKind.UNIVERSAL)


def new_uid(*, now_ms: int | None = None, randbytes: bytes | None = None) -> str:
    """A ULID: 48-bit millisecond timestamp + 80 random bits, Crockford base32."""
    ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    rnd = secrets.token_bytes(10) if randbytes is None else randbytes
    if len(rnd) != 10 or not 0 <= ms < 2**48:
        raise ValueError("uid needs a 48-bit timestamp and 10 random bytes")
    number = (ms << 80) | int.from_bytes(rnd, "big")
    return "".join(_CROCKFORD[(number >> shift) & 31] for shift in range(125, -1, -5))


SLUG_MAX = 48


def slugify(text: str, *, max_len: int = SLUG_MAX) -> str:
    """Turn free text into a lesson id, cut at a word boundary (may need a suffix)."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > max_len:
        cut = slug[: max_len + 1]
        slug = cut[: cut.rfind("-")] if "-" in cut else slug[:max_len]
    return slug.strip("-") or "lesson"


@dataclass(frozen=True, slots=True)
class Lesson:
    id: str
    uid: str
    trigger: str
    body: str
    scope: Scope = UNIVERSAL
    tags: tuple[str, ...] = ()
    status: Status = Status.ACTIVE
    superseded_by: str | None = None
    related: tuple[str, ...] = ()
    created: dt.date = field(default_factory=today)
    updated: dt.date = field(default_factory=today)
    review_after: dt.date | None = None
    origin: str = "own"
    schema: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        problems = list(_problems(self))
        if problems:
            raise ValidationError("; ".join(problems), source=self.id or None)

    @property
    def is_imported(self) -> bool:
        return self.origin.startswith("imported:")

    @property
    def is_active(self) -> bool:
        return self.status is Status.ACTIVE

    @property
    def is_current(self) -> bool:
        """Still good advice: active, or graduated into an instructions file."""
        return self.status in (Status.ACTIVE, Status.GRADUATED)

    def with_changes(self, **changes: object) -> Lesson:
        """Copy with changes; bumps ``updated`` unless it is given explicitly."""
        changes.setdefault("updated", today())
        return dataclasses.replace(self, **changes)  # type: ignore[arg-type]

    # ---- serialization -------------------------------------------------
    def to_text(self) -> str:
        values: dict[str, frontmatter.DumpValue] = {
            "schema": self.schema,
            "id": self.id,
            "uid": self.uid,
            "trigger": self.trigger,
            "scope": str(self.scope),
            "tags": list(self.tags),
            "status": self.status.value,
            "superseded_by": self.superseded_by,
            "related": list(self.related),
            "created": self.created,
            "updated": self.updated,
            "review_after": self.review_after,
            "origin": self.origin,
        }
        ordered = {key: values[key] for key in _FIELD_ORDER}
        body = self.body.strip("\n")
        return f"{frontmatter.FENCE}\n{frontmatter.dump(ordered)}{frontmatter.FENCE}\n{body}\n"

    @classmethod
    def from_text(cls, text: str, *, source: str | None = None) -> Lesson:
        block, body = frontmatter.split(text, source=source)
        data = frontmatter.parse(block, source=source)
        unknown = set(data) - set(_FIELD_ORDER)
        if unknown:
            raise ValidationError(f"unknown field(s): {', '.join(sorted(unknown))}", source=source)
        try:
            schema = int(_req_str(data, "schema"))
            if schema > SCHEMA_VERSION:
                raise ValidationError(
                    f"schema {schema} is newer than this stickit (supports {SCHEMA_VERSION}); "
                    "upgrade the plugin"
                )
            return cls(
                schema=schema,
                id=_req_str(data, "id"),
                uid=_req_str(data, "uid"),
                trigger=_req_str(data, "trigger"),
                body=body.strip("\n"),
                scope=Scope.parse(_req_str(data, "scope")),
                tags=tuple(_opt_list(data, "tags")),
                status=_status(_opt_str(data, "status") or Status.ACTIVE.value),
                superseded_by=_opt_str(data, "superseded_by"),
                related=tuple(_opt_list(data, "related")),
                created=_date(_req_str(data, "created"), "created"),
                updated=_date(_req_str(data, "updated"), "updated"),
                review_after=_opt_date(data, "review_after"),
                origin=_opt_str(data, "origin") or "own",
            )
        except ValidationError as exc:
            if source and exc.source != source:
                raise ValidationError(str(exc), source=source) from exc
            raise
        except ValueError as exc:  # int() on schema
            raise ValidationError(f"invalid value: {exc}", source=source) from exc


def _problems(lesson: Lesson) -> Iterable[str]:  # noqa: PLR0912 - one branch per rule
    if lesson.schema != SCHEMA_VERSION:
        yield f"unsupported schema {lesson.schema}"
    if not ID_RE.match(lesson.id):
        yield f"id {lesson.id!r} must be a lowercase slug (a-z, 0-9, '-'), max 64 chars"
    if not UID_RE.match(lesson.uid):
        yield f"uid {lesson.uid!r} is not a ULID"
    trigger = lesson.trigger.strip()
    if not trigger.endswith("?"):
        yield "trigger must be a question ending with '?'"
    if len(trigger) > MAX_TRIGGER or "\n" in trigger:
        yield f"trigger must be one line of at most {MAX_TRIGGER} characters"
    if not lesson.body.strip():
        yield "body is empty"
    if len(lesson.body) > MAX_BODY:
        yield f"body is longer than {MAX_BODY} characters"
    if len(lesson.tags) > MAX_TAGS or any(not TAG_RE.match(t) for t in lesson.tags):
        yield f"tags must be lowercase slugs, at most {MAX_TAGS}"
    if len(set(lesson.tags)) != len(lesson.tags):
        yield "duplicate tags"
    if len(lesson.related) > MAX_RELATED or any(not ID_RE.match(r) for r in lesson.related):
        yield "related must be lesson ids"
    if lesson.status is Status.SUPERSEDED and not lesson.superseded_by:
        yield "superseded lessons need superseded_by"
    if lesson.superseded_by and not ID_RE.match(lesson.superseded_by):
        yield "superseded_by must be a lesson id"
    if lesson.superseded_by == lesson.id:
        yield "a lesson cannot supersede itself"
    if lesson.updated < lesson.created:
        yield "updated is before created"
    if not ORIGIN_RE.match(lesson.origin):
        yield "origin must be 'own' or 'imported:<label>'"
    if _CONTROL_RE.search(lesson.trigger + lesson.body):
        yield "contains control characters"


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _req_str(data: dict[str, frontmatter.Value], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValidationError(f"missing or invalid required field {key!r}")
    return value


def _opt_str(data: dict[str, frontmatter.Value], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"field {key!r} must be a single value")
    return value


def _opt_list(data: dict[str, frontmatter.Value], key: str) -> list[str]:
    value = data.get(key)
    if value is None:
        return []
    if isinstance(value, str):
        raise ValidationError(f"field {key!r} must be a list, e.g. [a, b]")
    return value


def _status(text: str) -> Status:
    try:
        return Status(text)
    except ValueError:
        allowed = ", ".join(s.value for s in Status)
        raise ValidationError(f"status must be one of {allowed}") from None


def _date(text: str, key: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise ValidationError(f"{key} must be a YYYY-MM-DD date") from None


def _opt_date(data: dict[str, frontmatter.Value], key: str) -> dt.date | None:
    text = _opt_str(data, key)
    return _date(text, key) if text else None
