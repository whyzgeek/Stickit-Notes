"""Configuration: environment > store ``stickit.toml`` > built-in defaults."""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stickit.errors import ValidationError

ENV_STORE = "STICKIT_DIR"
DEFAULT_STORE_NAME = "stickit-notes-data"
CONFIG_NAME = "stickit.toml"
STORE_VERSION = 1


@dataclass(frozen=True, slots=True)
class Config:
    store_version: int = STORE_VERSION
    inject_budget: int = 6000
    remind_min_prompts: int = 8
    redact_extra: tuple[re.Pattern[str], ...] = field(default=())
    redact_allow: tuple[str, ...] = field(default=())


DEFAULT_CONFIG_TEXT = f"""\
# stickit-notes store configuration. Every key is optional.
store_version = {STORE_VERSION}

[inject]
# Max characters of lesson triggers added to each new session (hook limit is 10000).
budget = 6000

[remind]
# Remind to /harvest at the end of a turn once a session has this many prompts.
min_prompts = 8

[redact]
# Extra regular expressions to redact on export, e.g. internal hostnames.
extra = []
# Exact strings that must never be redacted (e.g. a public project name).
allow = []
"""


def resolve_store_root(env: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    """Where the store lives: ``$STICKIT_DIR`` or ``~/stickit-notes-data``."""
    env = os.environ if env is None else env
    override = env.get(ENV_STORE, "").strip()
    if override:
        return Path(override).expanduser()
    return (home or Path.home()) / DEFAULT_STORE_NAME


def load(path: Path) -> Config:
    """Read and validate ``stickit.toml``. A missing file means defaults."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Config()
    except tomllib.TOMLDecodeError as exc:
        raise ValidationError(f"invalid TOML: {exc}", source=str(path)) from exc
    return from_mapping(data, source=str(path))


def from_mapping(data: Mapping[str, Any], *, source: str = CONFIG_NAME) -> Config:
    known = {"store_version", "inject", "remind", "redact"}
    unknown = set(data) - known
    if unknown:
        raise ValidationError(f"unknown key(s): {', '.join(sorted(unknown))}", source=source)
    version = _int(data, "store_version", STORE_VERSION, source, low=1)
    if version > STORE_VERSION:
        raise ValidationError(
            f"store_version {version} is newer than this stickit supports ({STORE_VERSION})",
            source=source,
        )
    inject = _table(data, "inject", source)
    remind = _table(data, "remind", source)
    redact = _table(data, "redact", source)
    extra = []
    for pattern in _str_list(redact, "extra", source):
        try:
            extra.append(re.compile(pattern))
        except re.error as exc:
            raise ValidationError(f"redact.extra {pattern!r}: {exc}", source=source) from exc
    return Config(
        store_version=version,
        inject_budget=_int(inject, "budget", 6000, source, low=500, high=9500),
        remind_min_prompts=_int(remind, "min_prompts", 8, source, low=0),
        redact_extra=tuple(extra),
        redact_allow=tuple(_str_list(redact, "allow", source)),
    )


def _table(data: Mapping[str, Any], key: str, source: str) -> Mapping[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValidationError(f"[{key}] must be a table", source=source)
    return value


def _int(
    data: Mapping[str, Any],
    key: str,
    default: int,
    source: str,
    *,
    low: int | None = None,
    high: int | None = None,
) -> int:
    value = data.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{key} must be an integer", source=source)
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValidationError(f"{key} must be between {low} and {high}", source=source)
    return value


def _str_list(data: Mapping[str, Any], key: str, source: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ValidationError(f"{key} must be a list of non-empty strings", source=source)
    return list(value)
