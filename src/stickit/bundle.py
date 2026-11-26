"""Bundle format v1: several lessons in one human-readable, pasteable Markdown file.

::

    <!-- stickit-bundle v1 -->
    # stickit-notes bundle
    ...prose...
    <!-- stickit:lesson -->
    ---
    (lesson front matter)
    ---
    (lesson body)
    <!-- stickit:lesson -->
    ...

The HTML comments are invisible when the file is rendered on GitHub. A plain
single lesson file (starting with ``---``) is accepted by :func:`parse` too.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence

from stickit.errors import ValidationError
from stickit.model import Lesson

VERSION = 1
HEADER = f"<!-- stickit-bundle v{VERSION} -->"
MARKER = "<!-- stickit:lesson -->"
_HEADER_RE = re.compile(r"^<!-- stickit-bundle v(\d+) -->\s*$")
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_BUNDLE_BYTES = 2 * 1024 * 1024


def dump(lesson_texts: Sequence[str], *, exported: dt.date) -> str:
    """Join already-serialized (and redacted) lessons into a bundle."""
    for text in lesson_texts:
        if MARKER in text:
            raise ValidationError("a lesson contains the bundle marker line")
    head = (
        f"{HEADER}\n# stickit-notes bundle\n\n"
        f"{len(lesson_texts)} lesson(s), exported {exported.isoformat()}. "
        "Import with `/stickit import <this file>` "
        "(see https://github.com/whyzgeek/stickit-notes).\n"
    )
    return head + "".join(f"\n{MARKER}\n{text.rstrip()}\n" for text in lesson_texts)


def sanitize(text: str) -> str:
    """Strip terminal escapes and control characters from untrusted input."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL_RE.sub("", _ANSI_RE.sub("", text))


def parse(text: str, *, source: str) -> list[Lesson]:
    """Lessons from a bundle or a single lesson file. All-or-nothing on errors."""
    if len(text.encode("utf-8")) > MAX_BUNDLE_BYTES:
        raise ValidationError("file is larger than 2 MiB", source=source)
    text = sanitize(text)
    first = text.lstrip().split("\n", 1)[0]
    header = _HEADER_RE.match(first)
    if header is None:
        if text.lstrip().startswith("---"):
            return [Lesson.from_text(text.lstrip(), source=source)]
        raise ValidationError("not a stickit bundle or lesson file", source=source)
    version = int(header.group(1))
    if version > VERSION:
        raise ValidationError(
            f"bundle v{version} is newer than this stickit supports (v{VERSION})", source=source
        )
    chunks = text.split(f"\n{MARKER}\n")[1:]
    if not chunks:
        raise ValidationError("bundle contains no lessons", source=source)
    return [
        Lesson.from_text(chunk.strip("\n") + "\n", source=f"{source}#{index}")
        for index, chunk in enumerate(chunks, start=1)
    ]
