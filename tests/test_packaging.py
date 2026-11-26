"""Release hygiene: versions agree, manifests are valid, examples follow the spec."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

import stickit
from stickit import bundle
from stickit.hooks import HANDLERS
from stickit.model import Lesson

ROOT = Path(__file__).resolve().parents[1]


def test_versions_agree() -> None:
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert plugin["version"] == project["version"] == stickit.__version__
    assert f"## [{stickit.__version__}]" in changelog


def test_marketplace_points_at_this_plugin() -> None:
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert [p["name"] for p in market["plugins"]] == [plugin["name"]]
    assert market["plugins"][0]["source"] == "./"


def test_hooks_json_calls_known_events_with_timeouts() -> None:
    config = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    seen = set()
    for groups in config.values():
        for group in groups:
            for hook in group["hooks"]:
                match = re.search(r'bin/stickit" hook ([a-z-]+)$', hook["command"])
                assert match, hook["command"]
                assert "${CLAUDE_PLUGIN_ROOT}" in hook["command"]
                assert 0 < hook["timeout"] <= 10
                seen.add(match.group(1))
    assert seen == set(HANDLERS)


@pytest.mark.parametrize("skill", ["harvest", "stickit"])
def test_skills_have_frontmatter(skill: str) -> None:
    text = (ROOT / "skills" / skill / "SKILL.md").read_text()
    assert text.startswith(f"---\nname: {skill}\ndescription: ")
    assert 'Bash(python3 "${CLAUDE_PLUGIN_ROOT}/bin/stickit" *)' in text


def test_examples_are_valid_lessons() -> None:
    files = sorted((ROOT / "examples" / "lessons").glob("*.md"))
    assert files
    for path in files:
        lesson = Lesson.from_text(path.read_text(), source=str(path))
        assert lesson.id == path.stem
        assert lesson.to_text() == path.read_text(), f"{path.name} is not in canonical form"


def test_example_bundle_parses() -> None:
    path = ROOT / "examples" / "bundle.md"
    lessons = bundle.parse(path.read_text(), source=str(path))
    assert len(lessons) == 2


def test_no_personal_data_in_repo() -> None:
    """The public repo must not carry the maintainer's machine details or email."""
    email = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}")
    allowed_domains = ("example.com", "example.invalid", "noreply.github.com", "git@github.com")
    home = re.compile(r"/(?:home|Users)/(?!alice\b|<user>|\{|you\b)[a-z][a-z0-9_-]*")
    for path in ROOT.rglob("*"):
        if any(
            part
            in {
                ".git",
                ".venv",
                "__pycache__",
                ".mypy_cache",
                ".ruff_cache",
                ".pytest_cache",
                "build",
            }
            or part.endswith(".egg-info")
            for part in path.parts
        ):
            continue
        if path.is_file() and path.suffix in {".md", ".py", ".json", ".toml", ".yml", ".sh", ""}:
            text = path.read_text(errors="ignore")
            where = path.relative_to(ROOT)
            for match in email.finditer(text):
                assert match.group(0).endswith(allowed_domains), f"email in {where}"
            assert not home.search(text), f"home path in {where}: {home.search(text)}"
