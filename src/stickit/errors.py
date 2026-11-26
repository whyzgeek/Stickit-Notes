"""Exception hierarchy. Every error stickit raises on purpose is a StickitError."""

from __future__ import annotations


class StickitError(Exception):
    """Base class; the CLI maps subclasses to exit codes."""

    exit_code = 1


class ValidationError(StickitError):
    """A lesson, bundle or config file does not satisfy the format."""

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        super().__init__(f"{source}: {message}" if source else message)


class StoreError(StickitError):
    """The store is missing, unreadable or in an unexpected state."""

    exit_code = 2


class StoreNotFoundError(StoreError):
    """No store exists at the resolved location."""


class GitError(StoreError):
    """A git command failed or timed out."""


class RedactionError(StickitError):
    """Export refused because content would leak a secret."""

    exit_code = 3
