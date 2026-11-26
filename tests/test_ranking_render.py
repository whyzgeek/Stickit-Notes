from __future__ import annotations

import datetime as dt
from pathlib import Path

from conftest import LessonFactory
from stickit import ranking, render
from stickit.context import Context
from stickit.model import Status


def test_select_filters_inactive_and_foreign_scopes(
    ctx: Context, make_lesson: LessonFactory
) -> None:
    lessons = [
        make_lesson(id="u"),
        make_lesson(id="dep", status=Status.DEPRECATED),
        make_lesson(id="foreign", scope="host:elsewhere"),
        make_lesson(id="mine", scope="host:boxone"),
    ]
    sel = ranking.select(lessons, ctx, budget=10_000, cost=render.line_cost)
    assert [x.id for x in sel.own] == ["mine", "u"]
    assert sel.omitted == 0


def test_rank_order(ctx: Context, make_lesson: LessonFactory) -> None:
    lessons = [
        make_lesson(id="old", updated=dt.date(2026, 1, 1)),
        make_lesson(id="new", updated=dt.date(2026, 6, 1)),
        make_lesson(id="tagged", tags=("webapp",)),
        make_lesson(id="host", scope="host:boxone"),
        make_lesson(id="proj", scope="project:webapp"),
    ]
    sel = ranking.select(lessons, ctx, budget=10_000, cost=render.line_cost)
    assert [x.id for x in sel.own] == ["proj", "host", "tagged", "new", "old"]


def test_budget_and_own_before_imported(ctx: Context, make_lesson: LessonFactory) -> None:
    own = [make_lesson(id=f"own-{i}") for i in range(3)]
    imported = [make_lesson(id="theirs", origin="imported:bob", updated=dt.date(2026, 9, 9))]
    per_line = render.line_cost(own[0])
    sel = ranking.select([*imported, *own], ctx, budget=per_line * 3, cost=render.line_cost)
    assert len(sel.own) == 3
    assert sel.imported == []
    assert sel.omitted == 1
    assert sel.shown == 3


def test_inject_text(ctx: Context, make_lesson: LessonFactory, tmp_path: Path) -> None:
    sel = ranking.Selection(
        own=[make_lesson(id="a", scope="host:boxone")],
        imported=[make_lesson(id="b", origin="imported:bob")],
        omitted=2,
    )
    text = render.inject(sel, lessons_dir=tmp_path, invalid=1)
    assert text.startswith(render.INJECT_TITLE)
    assert f"`{tmp_path}/<id>.md`" in text
    assert "→ a [host]" in text
    assert render.IMPORTED_TITLE in text
    assert text.index(render.IMPORTED_TITLE) < text.index("→ b")
    assert "+2 more" in text
    assert "1 lesson file(s) are invalid" in text


def test_inject_empty_is_silent(tmp_path: Path) -> None:
    assert render.inject(ranking.Selection(), lessons_dir=tmp_path) == ""


def test_frame_reserve_covers_fixed_text(make_lesson: LessonFactory, tmp_path: Path) -> None:
    sel = ranking.Selection(own=[], imported=[make_lesson(origin="imported:x")], omitted=999)
    framed = render.inject(sel, lessons_dir=tmp_path / ("d" * 200), invalid=99)
    assert len(framed) - render.line_cost(sel.imported[0]) < render.FRAME_RESERVE


def test_table_and_json(make_lesson: LessonFactory) -> None:
    lessons = [make_lesson(id="a", trigger="Is this a very long trigger " + "x" * 80 + "?")]
    table = render.table(lessons)
    assert table.splitlines()[0].startswith("ID")
    assert "…" in table
    assert render.table([]) == "No lessons.\n"
    assert '"id": "a"' in render.as_json(lessons)
    assert '"body"' not in render.as_json(lessons)
    assert '"body"' in render.as_json(lessons, with_body=True)


def test_missing_store_hint(tmp_path: Path) -> None:
    assert "/stickit init --clone" in render.missing_store_hint(tmp_path)
