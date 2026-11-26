"""Graduate lessons into an agent instructions file (CLAUDE.md, AGENTS.md).

A lesson that keeps firing deserves to be a standing instruction. Graduated
lessons are written into a block that stickit owns and can update or remove
again; everything else in the file is left untouched::

    <!-- stickit:begin -->
    ## Lessons learned (managed by stickit-notes)

    - **Trigger question?** The rule. How to apply: ... <!-- stickit:lesson-id -->
    <!-- stickit:end -->

All functions here are pure: they take and return the file's text.
"""

from __future__ import annotations

import re

from stickit.errors import ValidationError
from stickit.model import Lesson

BEGIN = "<!-- stickit:begin -->"
END = "<!-- stickit:end -->"
HEADING = "## Lessons learned (managed by stickit-notes)"
_ENTRY_RE = re.compile(r"^- .* <!-- stickit:([a-z0-9][a-z0-9-]*) -->$")
_WHY_RE = re.compile(r"\*\*Why:\*\*", re.IGNORECASE)
_HOW_RE = re.compile(r"\*\*How to apply:\*\*\s*(.*?)(?=\*\*[A-Z][^*]*:\*\*|\Z)", re.S | re.I)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def entry(lesson: Lesson) -> str:
    """One line: trigger, the rule (the body before **Why:**), and how to apply it."""
    rule = _one_line(_WHY_RE.split(lesson.body, maxsplit=1)[0])
    rule = _one_line(_HOW_RE.sub("", rule))
    how = _HOW_RE.search(lesson.body)
    text = rule
    if how and _one_line(how.group(1)):
        text = f"{rule} How to apply: {_one_line(how.group(1))}".strip()
    return f"- **{lesson.trigger.strip()}** {text} <!-- stickit:{lesson.id} -->"


def _split(doc: str) -> tuple[str, list[str], str] | None:
    """``(before, block_lines, after)`` or None when the file has no stickit block."""
    lines = doc.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise ValidationError(
            f"the stickit block markers are damaged; fix {BEGIN} / {END} by hand first"
        )
    start, end = starts[0], ends[0]
    before = "\n".join(lines[:start])
    after = "\n".join(lines[end + 1 :])
    return before, lines[start + 1 : end], after


def ids(doc: str) -> list[str]:
    parts = _split(doc)
    if parts is None:
        return []
    return [m.group(1) for line in parts[1] if (m := _ENTRY_RE.match(line))]


def _render(before: str, entries: list[str], after: str) -> str:
    chunks = []
    if before.strip():
        chunks.append(before.rstrip("\n"))
    if entries:
        chunks.append("\n".join([BEGIN, HEADING, "", *entries, END]))
    if after.strip():
        chunks.append(after.strip("\n"))
    return ("\n\n".join(chunks) + "\n") if chunks else ""


def upsert(doc: str, lesson: Lesson) -> str:
    """Add the lesson's entry, or replace it if it is already there."""
    new = entry(lesson)
    parts = _split(doc)
    if parts is None:
        return _render(doc, [new], "")
    before, block, after = parts
    entries = [line for line in block if _ENTRY_RE.match(line)]
    marker = f"<!-- stickit:{lesson.id} -->"
    if any(line.endswith(marker) for line in entries):
        entries = [new if line.endswith(marker) else line for line in entries]
    else:
        entries.append(new)
    return _render(before, entries, after)


def remove(doc: str, lesson_id: str) -> str:
    """Drop the lesson's entry; drop the whole block when it becomes empty."""
    parts = _split(doc)
    marker = f"<!-- stickit:{lesson_id} -->"
    if parts is None or not any(line.endswith(marker) for line in parts[1]):
        raise ValidationError(f"{lesson_id} is not in this file's stickit block")
    before, block, after = parts
    entries = [line for line in block if _ENTRY_RE.match(line) and not line.endswith(marker)]
    return _render(before, entries, after)
