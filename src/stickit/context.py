"""Where a session runs: host and project, used to pick scoped lessons.

Detection is filesystem-only (no subprocess) so hooks stay fast.
"""

from __future__ import annotations

import getpass
import socket
from dataclasses import dataclass
from pathlib import Path

from stickit.model import Lesson, ScopeKind


@dataclass(frozen=True, slots=True)
class Context:
    host: str
    project: str | None
    home: Path
    user: str

    def applies(self, lesson: Lesson) -> bool:
        scope = lesson.scope
        if scope.kind is ScopeKind.UNIVERSAL:
            return True
        if scope.kind is ScopeKind.HOST:
            return scope.value == self.host
        return self.project is not None and scope.value == self.project


def short_hostname(raw: str | None = None) -> str:
    name = (raw if raw is not None else socket.gethostname()).split(".")[0].lower()
    return name or "localhost"


def project_root(cwd: Path, home: Path) -> Path | None:
    """The git work tree containing ``cwd``, else ``cwd`` itself.

    Home and filesystem root are not projects: lessons scoped to them would
    apply almost everywhere, which is what ``universal`` is for.
    """
    try:
        cwd = cwd.resolve()
        home = home.resolve()
    except OSError:
        return None
    for candidate in (cwd, *cwd.parents):
        if candidate in (home, candidate.parent):
            break
        if (candidate / ".git").exists():
            return candidate
    if cwd in (home, cwd.parent):
        return None
    return cwd


def project_name(cwd: Path, home: Path) -> str | None:
    """Lowercase name of :func:`project_root`, used for ``project:`` scopes."""
    root = project_root(cwd, home)
    return root.name.lower() if root else None


def detect(
    cwd: Path | None = None, *, home: Path | None = None, host: str | None = None
) -> Context:
    home = home or Path.home()
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = home.name
    return Context(
        host=short_hostname(host),
        project=project_name(cwd or Path.cwd(), home),
        home=home,
        user=user,
    )
