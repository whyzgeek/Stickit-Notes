"""Import lessons written by others into the inbox (never straight into lessons/)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stickit import bundle, redact
from stickit.errors import ValidationError
from stickit.model import ORIGIN_RE, Lesson, today
from stickit.store import Area, Store

MAX_FILES = 500


@dataclass(frozen=True, slots=True)
class ImportResult:
    status: str  # added | update | duplicate | skipped
    lesson_id: str
    detail: str = ""
    path: Path | None = None


def _files(path: Path) -> list[Path]:
    if path.is_dir():
        files = sorted(p for p in path.rglob("*.md") if p.is_file() and not p.is_symlink())
        if len(files) > MAX_FILES:
            raise ValidationError(f"more than {MAX_FILES} files", source=str(path))
        return files
    if not path.is_file():
        raise ValidationError("no such file or folder", source=str(path))
    return [path]


def _same_content(a: Lesson, b: Lesson) -> bool:
    keys = ("trigger", "body", "scope", "tags", "status", "superseded_by", "related")
    return all(getattr(a, k) == getattr(b, k) for k in keys)


def import_path(store: Store, path: Path, *, label: str) -> list[ImportResult]:
    origin = f"imported:{label}"
    if not ORIGIN_RE.match(origin):
        raise ValidationError(f"invalid label {label!r} (letters, digits, . _ -)")
    incoming: list[Lesson] = []
    for file in _files(path):
        incoming.extend(bundle.parse(file.read_text(encoding="utf-8"), source=str(file)))
    results: list[ImportResult] = []
    for raw in incoming:
        lesson = raw.with_changes(origin=origin, updated=raw.updated)
        secrets = redact.find_secrets(f"{lesson.trigger}\n{lesson.body}")
        if secrets:
            results.append(
                ImportResult("skipped", lesson.id, f"possible secret ({', '.join(secrets)})")
            )
            continue
        existing = store.find_uid(lesson.uid)
        if existing and _same_content(existing, lesson):
            results.append(ImportResult("duplicate", existing.id, "already in your lessons"))
            continue
        pending = store.find_uid(lesson.uid, Area.INBOX)
        if pending:
            if _same_content(pending, lesson):
                results.append(ImportResult("duplicate", pending.id, "already in inbox"))
                continue
            lesson = lesson.with_changes(id=pending.id, updated=today())
            saved = store.save(lesson, Area.INBOX, overwrite=True)
            results.append(ImportResult("update", lesson.id, "replaced inbox copy", saved))
            continue
        if existing:
            lesson = lesson.with_changes(id=store.unique_id(existing.id), updated=lesson.updated)
            saved = store.save(lesson, Area.INBOX)
            results.append(ImportResult("update", lesson.id, f"changes {existing.id}", saved))
            continue
        lesson = lesson.with_changes(id=store.unique_id(lesson.id), updated=lesson.updated)
        saved = store.save(lesson, Area.INBOX)
        results.append(ImportResult("added", lesson.id, "", saved))
    return results
