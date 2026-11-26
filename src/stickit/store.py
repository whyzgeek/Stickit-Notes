"""The lessons store: one Markdown file per lesson in a (usually git-backed) folder.

Layout::

    <root>/stickit.toml     configuration and store_version (marks a store)
    <root>/lessons/<id>.md  accepted lessons
    <root>/inbox/<id>.md    imported lessons awaiting review
    <root>/.state/          private, gitignored: sessions, lock, log

Writes are atomic (temp file + rename) and serialized with an advisory lock,
so concurrent Claude Code sessions cannot corrupt a file.
"""

from __future__ import annotations

import contextlib
import enum
import fcntl
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from stickit import config as config_mod
from stickit.errors import StoreError, StoreNotFoundError, ValidationError
from stickit.model import Lesson

GITIGNORE = ".state/\n"


class Area(enum.StrEnum):
    LESSONS = "lessons"
    INBOX = "inbox"


@dataclass(frozen=True, slots=True)
class LoadResult:
    lessons: list[Lesson] = field(default_factory=list)
    errors: list[ValidationError] = field(default_factory=list)


class Store:
    """Repository for lessons under one root folder."""

    def __init__(self, root: Path) -> None:
        self.root = root

    # ---- paths ----------------------------------------------------------
    @property
    def config_path(self) -> Path:
        return self.root / config_mod.CONFIG_NAME

    @property
    def state_dir(self) -> Path:
        return self.root / ".state"

    def area_dir(self, area: Area) -> Path:
        return self.root / area.value

    def path_for(self, lesson_id: str, area: Area = Area.LESSONS) -> Path:
        return self.area_dir(area) / f"{lesson_id}.md"

    # ---- lifecycle ------------------------------------------------------
    @staticmethod
    def is_store(root: Path) -> bool:
        return (root / config_mod.CONFIG_NAME).is_file()

    @classmethod
    def open(cls, root: Path) -> Store:
        if not cls.is_store(root):
            raise StoreNotFoundError(f"no stickit store at {root}")
        return cls(root)

    @classmethod
    def create(cls, root: Path) -> Store:
        """Create the store layout. Refuses a non-empty folder that is not a store."""
        if cls.is_store(root):
            raise StoreError(f"a store already exists at {root}")
        if root.exists() and any(p.name != ".git" for p in root.iterdir()):
            raise StoreError(f"{root} exists and is not an empty folder or a stickit store")
        store = cls(root)
        for area in Area:
            store.area_dir(area).mkdir(parents=True, exist_ok=True)
            (store.area_dir(area) / ".gitkeep").touch()
        atomic_write(store.config_path, config_mod.DEFAULT_CONFIG_TEXT)
        atomic_write(root / ".gitignore", GITIGNORE)
        return store

    def config(self) -> config_mod.Config:
        return config_mod.load(self.config_path)

    # ---- reading --------------------------------------------------------
    def iter_paths(self, area: Area = Area.LESSONS) -> Iterator[Path]:
        folder = self.area_dir(area)
        if folder.is_dir():
            yield from sorted(p for p in folder.glob("*.md") if p.is_file())

    def load_all(self, area: Area = Area.LESSONS) -> LoadResult:
        """Load every lesson; invalid files are reported, never fatal."""
        result = LoadResult()
        for path in self.iter_paths(area):
            try:
                lesson = _read(path)
            except ValidationError as exc:
                result.errors.append(exc)
                continue
            if lesson.id != path.stem:
                result.errors.append(
                    ValidationError(f"id {lesson.id!r} does not match file name", source=str(path))
                )
                continue
            result.lessons.append(lesson)
        return result

    def get(self, lesson_id: str, area: Area = Area.LESSONS) -> Lesson:
        path = self.path_for(lesson_id, area)
        if not path.is_file():
            raise StoreError(f"no lesson {lesson_id!r} in {area.value}/")
        return _read(path)

    def exists(self, lesson_id: str, area: Area = Area.LESSONS) -> bool:
        return self.path_for(lesson_id, area).is_file()

    def find_uid(self, uid: str, area: Area = Area.LESSONS) -> Lesson | None:
        return next((x for x in self.load_all(area).lessons if x.uid == uid), None)

    # ---- writing --------------------------------------------------------
    def save(self, lesson: Lesson, area: Area = Area.LESSONS, *, overwrite: bool = False) -> Path:
        path = self.path_for(lesson.id, area)
        with self.lock():
            if path.exists() and not overwrite:
                raise StoreError(f"lesson {lesson.id!r} already exists in {area.value}/")
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, lesson.to_text())
        return path

    def delete(self, lesson_id: str, area: Area = Area.LESSONS) -> Path:
        path = self.path_for(lesson_id, area)
        with self.lock():
            try:
                path.unlink()
            except FileNotFoundError:
                raise StoreError(f"no lesson {lesson_id!r} in {area.value}/") from None
        return path

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with (self.state_dir / "store.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def unique_id(self, wanted: str) -> str:
        """``wanted`` if free in both areas, else ``wanted-2``, ``wanted-3``, ..."""
        candidate, n = wanted, 1
        while any(self.exists(candidate, area) for area in Area):
            n += 1
            candidate = f"{wanted[:60].rstrip('-')}-{n}"
        return candidate


def _read(path: Path) -> Lesson:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(f"cannot read: {exc}", source=str(path)) from exc
    return Lesson.from_text(text, source=str(path))


def atomic_write(path: Path, text: str) -> None:
    """Write via a temp file in the same folder, fsync, then rename over ``path``."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
