"""Choose which lessons a session sees, within a character budget. Pure functions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from stickit.context import Context
from stickit.model import Lesson


@dataclass(frozen=True, slots=True)
class Selection:
    own: list[Lesson] = field(default_factory=list)
    imported: list[Lesson] = field(default_factory=list)
    omitted: int = 0

    @property
    def shown(self) -> int:
        return len(self.own) + len(self.imported)


def applicable(lessons: Iterable[Lesson], ctx: Context) -> list[Lesson]:
    return [lesson for lesson in lessons if lesson.is_active and ctx.applies(lesson)]


def rank_key(lesson: Lesson, ctx: Context) -> tuple[int, int, int, str]:
    """Most specific scope first, then lessons tagged with the project, then newest."""
    tagged = ctx.project is not None and ctx.project in lesson.tags
    return (-lesson.scope.specificity, -int(tagged), -lesson.updated.toordinal(), lesson.id)


def select(
    lessons: Iterable[Lesson],
    ctx: Context,
    *,
    budget: int,
    cost: Callable[[Lesson], int],
) -> Selection:
    """Greedily fill ``budget`` with the best-ranked applicable lessons.

    Own lessons are considered before imported ones, so lessons from others
    can never push your own out of the session.
    """
    ranked = sorted(applicable(lessons, ctx), key=lambda lesson: rank_key(lesson, ctx))
    own = [x for x in ranked if not x.is_imported]
    imported = [x for x in ranked if x.is_imported]
    remaining = budget
    chosen: dict[bool, list[Lesson]] = {False: [], True: []}
    omitted = 0
    for lesson in (*own, *imported):
        price = cost(lesson)
        if price <= remaining:
            chosen[lesson.is_imported].append(lesson)
            remaining -= price
        else:
            omitted += 1
    return Selection(own=chosen[False], imported=chosen[True], omitted=omitted)
