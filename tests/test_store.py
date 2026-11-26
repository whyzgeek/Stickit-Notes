from __future__ import annotations

import threading
from pathlib import Path

import pytest

from conftest import LessonFactory
from stickit.errors import StoreError, StoreNotFoundError
from stickit.store import Area, Store


def test_create_layout(store: Store) -> None:
    assert Store.is_store(store.root)
    for area in Area:
        assert store.area_dir(area).is_dir()
    assert (store.root / ".gitignore").read_text() == ".state/\n"


def test_create_refuses_existing_store_or_non_empty_dir(store: Store, tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="already exists"):
        Store.create(store.root)
    other = tmp_path / "other"
    other.mkdir()
    (other / "file.txt").write_text("x")
    with pytest.raises(StoreError, match="not an empty folder"):
        Store.create(other)


def test_create_accepts_empty_git_clone(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    (root / ".git").mkdir(parents=True)
    assert Store.is_store(Store.create(root).root)


def test_open_missing(tmp_path: Path) -> None:
    with pytest.raises(StoreNotFoundError):
        Store.open(tmp_path / "nope")


def test_save_get_list_delete(store: Store, make_lesson: LessonFactory) -> None:
    lesson = make_lesson()
    path = store.save(lesson)
    assert path == store.path_for(lesson.id)
    assert store.get(lesson.id) == lesson
    assert store.exists(lesson.id)
    assert store.find_uid(lesson.uid) == lesson
    assert store.find_uid("missing") is None
    assert store.load_all().lessons == [lesson]
    with pytest.raises(StoreError, match="already exists"):
        store.save(lesson)
    store.save(lesson.with_changes(body="changed"), overwrite=True)
    assert store.get(lesson.id).body == "changed"
    store.delete(lesson.id)
    assert not store.exists(lesson.id)
    with pytest.raises(StoreError, match="no lesson"):
        store.delete(lesson.id)
    with pytest.raises(StoreError, match="no lesson"):
        store.get(lesson.id)


def test_load_all_reports_invalid_files_without_failing(
    store: Store, make_lesson: LessonFactory
) -> None:
    good = make_lesson()
    store.save(good)
    (store.area_dir(Area.LESSONS) / "broken.md").write_text("not a lesson")
    (store.area_dir(Area.LESSONS) / "renamed.md").write_text(make_lesson(id="other").to_text())
    (store.area_dir(Area.LESSONS) / "binary.md").write_bytes(b"\xff\xfe")
    result = store.load_all()
    assert result.lessons == [good]
    assert len(result.errors) == 3
    assert any("does not match file name" in str(e) for e in result.errors)


def test_unique_id_checks_both_areas(store: Store, make_lesson: LessonFactory) -> None:
    store.save(make_lesson(id="tip"))
    store.save(make_lesson(id="tip-2"), Area.INBOX)
    assert store.unique_id("tip") == "tip-3"
    assert store.unique_id("free") == "free"


def test_atomic_write_leaves_no_temp_files(store: Store, make_lesson: LessonFactory) -> None:
    store.save(make_lesson())
    leftovers = [p for p in store.area_dir(Area.LESSONS).iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_concurrent_saves_do_not_corrupt(store: Store, make_lesson: LessonFactory) -> None:
    lessons = [make_lesson() for _ in range(20)]

    def worker(chunk: list[object]) -> None:
        for lesson in chunk:
            store.save(lesson, overwrite=True)  # type: ignore[arg-type]

    threads = [threading.Thread(target=worker, args=(lessons[i::4],)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    result = store.load_all()
    assert len(result.lessons) == 20
    assert result.errors == []
