"""Logging to the store's private state directory (never to stdout: hooks own it)."""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

LOGGER_NAME = "stickit"
_MAX_BYTES = 256 * 1024


def get() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def configure(state_dir: Path | None) -> logging.Logger:
    """Send logs to ``<state_dir>/stickit.log``; ``STICKIT_DEBUG=1`` adds debug lines."""
    logger = get()
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG if os.environ.get("STICKIT_DEBUG") == "1" else logging.INFO)
    if state_dir is None:
        logger.addHandler(logging.NullHandler())
        return logger
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            state_dir / "stickit.log", maxBytes=_MAX_BYTES, backupCount=1, encoding="utf-8"
        )
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger
