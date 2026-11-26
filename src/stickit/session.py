"""Per-session counters behind the harvest reminder (kept in ``.state/sessions``)."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from stickit.log import get as get_log

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")
MAX_AGE_DAYS = 14


@dataclass(slots=True)
class SessionState:
    prompts: int = 0
    harvested: bool = False
    reminded: bool = False
    started: float = field(default_factory=time.time)


def should_remind(state: SessionState, *, min_prompts: int, before_compact: bool = False) -> bool:
    """One reminder per session, only when there is something worth harvesting."""
    if state.harvested or state.reminded or min_prompts == 0:
        return False
    if before_compact:
        return state.prompts >= 1
    return state.prompts >= min_prompts


def is_harvest_prompt(prompt: str) -> bool:
    """True for ``/harvest`` and the namespaced ``/stickit-notes:harvest``."""
    first = prompt.strip().split(maxsplit=1)[0] if prompt.strip() else ""
    return first in ("/harvest", "/stickit-notes:harvest")


def is_harvest_skill(skill: str) -> bool:
    return skill in ("harvest", "stickit-notes:harvest")


class SessionStore:
    def __init__(self, state_dir: Path) -> None:
        self.dir = state_dir / "sessions"

    def _path(self, session_id: str) -> Path:
        safe = _SAFE_ID.sub("_", session_id)[:128] or "unknown"
        return self.dir / f"{safe}.json"

    def load(self, session_id: str) -> SessionState:
        try:
            data = json.loads(self._path(session_id).read_text(encoding="utf-8"))
            return SessionState(
                prompts=int(data.get("prompts", 0)),
                harvested=bool(data.get("harvested", False)),
                reminded=bool(data.get("reminded", False)),
                started=float(data.get("started", time.time())),
            )
        except FileNotFoundError:
            return SessionState()
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            get_log().warning("session state %s unreadable, starting fresh: %s", session_id, exc)
            return SessionState()

    def save(self, session_id: str, state: SessionState) -> None:
        path = self._path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(state)), encoding="utf-8")
        tmp.replace(path)

    def prune(self, *, now: float | None = None, max_age_days: int = MAX_AGE_DAYS) -> int:
        cutoff = (now or time.time()) - max_age_days * 86400
        removed = 0
        if not self.dir.is_dir():
            return 0
        for path in self.dir.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed
