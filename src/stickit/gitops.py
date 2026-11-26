"""Thin, timeout-guarded wrappers around the git CLI (argv lists only, never a shell)."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from stickit.errors import GitError

LOCAL_TIMEOUT = 30
NETWORK_TIMEOUT = 120


def available() -> bool:
    return shutil.which("git") is not None


def run(args: Sequence[str], cwd: Path | None = None, *, timeout: int = LOCAL_TIMEOUT) -> str:
    if not available():
        raise GitError("git is not installed or not on PATH")
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=None,
        )
    except subprocess.TimeoutExpired:
        raise GitError(f"git {args[0]} timed out after {timeout}s") from None
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        raise GitError(f"git {args[0]} failed: {detail[-1] if detail else done.returncode}")
    return done.stdout


def is_repo(path: Path) -> bool:
    return (path / ".git").exists()


def init(path: Path) -> None:
    run(["init", "-q", "-b", "main"], cwd=path)


def clone(url: str, dest: Path) -> None:
    if url.startswith("-"):
        raise GitError("refusing a clone URL that starts with '-'")
    run(["clone", "-q", "--", url, str(dest)], timeout=NETWORK_TIMEOUT)


def has_identity(path: Path) -> bool:
    try:
        return bool(run(["config", "user.name"], cwd=path).strip()) and bool(
            run(["config", "user.email"], cwd=path).strip()
        )
    except GitError:
        return False


def commit(path: Path, paths: Sequence[Path], message: str) -> bool:
    """Stage ``paths`` (added, changed or deleted) and commit. False if nothing changed."""
    rel = [str(p.relative_to(path)) for p in paths]
    run(["add", "-A", "--", *rel], cwd=path)
    staged = run(["diff", "--cached", "--name-only", "--", *rel], cwd=path).strip()
    if not staged:
        return False
    run(["commit", "-q", "-m", message, "--", *rel], cwd=path)
    return True


def remotes(path: Path) -> list[str]:
    return run(["remote"], cwd=path).split()


def add_remote(path: Path, url: str, name: str = "origin") -> None:
    if url.startswith("-"):
        raise GitError("refusing a remote URL that starts with '-'")
    run(["remote", "add", name, url], cwd=path)


def current_branch(path: Path) -> str:
    return run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path).strip()


def has_commits(path: Path) -> bool:
    try:
        run(["rev-parse", "--verify", "-q", "HEAD"], cwd=path)
    except GitError:
        return False
    return True


def has_upstream(path: Path) -> bool:
    try:
        run(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=path)
    except GitError:
        return False
    return True


def sync(path: Path) -> list[str]:
    """Pull (rebase) then push. Returns human-readable steps taken."""
    if not remotes(path):
        raise GitError("the store has no git remote; add one with `stickit init --remote URL`")
    steps = []
    branch = current_branch(path)
    if has_upstream(path):
        run(["pull", "-q", "--rebase", "--autostash"], cwd=path, timeout=NETWORK_TIMEOUT)
        steps.append("pulled (rebase)")
        run(["push", "-q"], cwd=path, timeout=NETWORK_TIMEOUT)
    else:
        try:
            run(["pull", "-q", "--rebase", "origin", branch], cwd=path, timeout=NETWORK_TIMEOUT)
            steps.append(f"pulled origin/{branch}")
        except GitError as exc:
            if "couldn't find remote ref" not in str(exc).lower():
                raise
        run(["push", "-q", "-u", "origin", branch], cwd=path, timeout=NETWORK_TIMEOUT)
    steps.append(f"pushed {branch}")
    return steps
