"""Store health checks behind ``stickit doctor``."""

from __future__ import annotations

import datetime as dt
import difflib
import re
from collections import defaultdict
from dataclasses import dataclass, field

from stickit import redact
from stickit.context import Context
from stickit.errors import ValidationError
from stickit.store import Area, Store

NEAR_DUPLICATE = 0.88


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked: int = 0

    def lines(self) -> list[str]:
        out = [f"error: {e}" for e in self.errors] + [f"warning: {w}" for w in self.warnings]
        out.append(
            f"{self.checked} lesson(s) checked: {len(self.errors)} error(s), "
            f"{len(self.warnings)} warning(s)."
        )
        return out


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def run(store: Store, ctx: Context, *, today: dt.date) -> Report:  # noqa: PLR0912 - checklist
    report = Report()
    extra: tuple[re.Pattern[str], ...] = ()
    allow: tuple[str, ...] = ()
    try:
        cfg = store.config()
        extra, allow = cfg.redact_extra, cfg.redact_allow
    except ValidationError as exc:
        report.errors.append(f"config: {exc}")
    loaded = store.load_all(Area.LESSONS)
    inbox = store.load_all(Area.INBOX)
    report.errors += [str(e) for e in loaded.errors + inbox.errors]
    lessons = loaded.lessons
    report.checked = len(lessons)
    ids = {x.id for x in lessons}

    by_uid: dict[str, list[str]] = defaultdict(list)
    for lesson in lessons:
        by_uid[lesson.uid].append(lesson.id)
    for uid, owners in by_uid.items():
        if len(owners) > 1:
            report.errors.append(f"uid {uid} is used by {', '.join(owners)}")

    for lesson in lessons:
        for ref in lesson.related:
            if ref not in ids:
                report.warnings.append(f"{lesson.id}: related lesson {ref!r} does not exist")
        if lesson.superseded_by and lesson.superseded_by not in ids:
            report.errors.append(f"{lesson.id}: superseded_by {lesson.superseded_by!r} missing")
        if lesson.review_after and lesson.review_after < today and lesson.is_active:
            report.warnings.append(f"{lesson.id}: review was due {lesson.review_after}")
        secrets = redact.find_secrets(f"{lesson.trigger}\n{lesson.body}")
        if secrets:
            report.errors.append(f"{lesson.id}: possible secret ({', '.join(secrets)})")
        personal = redact.personal_details(lesson, ctx, extra, allow)
        if personal:
            report.warnings.append(
                f"{lesson.id}: contains personal details ({', '.join(personal)}); "
                "generalize it before sharing"
            )

    active = [x for x in lessons if x.is_active]
    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            ratio = difflib.SequenceMatcher(None, _norm(a.trigger), _norm(b.trigger)).ratio()
            if ratio >= NEAR_DUPLICATE:
                report.warnings.append(
                    f"{a.id} and {b.id} have near-identical triggers ({ratio:.0%}); merge them?"
                )
    if inbox.lessons:
        report.warnings.append(
            f"{len(inbox.lessons)} lesson(s) waiting in inbox (`stickit review`)"
        )
    return report
