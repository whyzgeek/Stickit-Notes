from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import LessonFactory
from stickit import config
from stickit.context import Context, detect, project_name, short_hostname
from stickit.errors import ValidationError


def test_resolve_store_root_env_and_default(tmp_path: Path) -> None:
    assert config.resolve_store_root({"STICKIT_DIR": "~/x"}) == Path("~/x").expanduser()
    assert config.resolve_store_root({}, home=tmp_path) == tmp_path / "stickit-notes-data"
    assert config.resolve_store_root({"STICKIT_DIR": "  "}, home=tmp_path) == (
        tmp_path / "stickit-notes-data"
    )


def test_default_config_text_parses_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "stickit.toml"
    path.write_text(config.DEFAULT_CONFIG_TEXT)
    assert config.load(path) == config.Config()
    assert config.load(tmp_path / "missing.toml") == config.Config()


def test_custom_values(tmp_path: Path) -> None:
    path = tmp_path / "stickit.toml"
    path.write_text(
        "[inject]\nbudget = 4000\n[remind]\nmin_prompts = 0\n"
        '[redact]\nextra = ["corp\\\\.internal"]\nallow = ["webapp"]\n'
    )
    cfg = config.load(path)
    assert cfg.inject_budget == 4000
    assert cfg.remind_min_prompts == 0
    assert cfg.redact_extra[0].pattern == r"corp\.internal"
    assert cfg.redact_allow == ("webapp",)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("store_version = 9\n", "newer"),
        ("color = 1\n", "unknown key"),
        ("[inject]\nbudget = 100\n", "between"),
        ('[inject]\nbudget = "big"\n', "integer"),
        ("[inject]\nbudget = true\n", "integer"),
        ("inject = 3\n", "must be a table"),
        ('[redact]\nextra = "x"\n', "list of non-empty"),
        ('[redact]\nextra = ["("]\n', "redact.extra"),
        ("not toml = = \n", "invalid TOML"),
    ],
)
def test_invalid_config(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "stickit.toml"
    path.write_text(text)
    with pytest.raises(ValidationError, match=message):
        config.load(path)


def test_short_hostname() -> None:
    assert short_hostname("Box.Example.com") == "box"
    assert short_hostname("") == "localhost"
    assert short_hostname()


def test_project_name_prefers_git_toplevel(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = home / "code" / "WebApp"
    (repo / ".git").mkdir(parents=True)
    (repo / "src" / "deep").mkdir(parents=True)
    assert project_name(repo / "src" / "deep", home) == "webapp"


def test_project_name_falls_back_to_folder_and_ignores_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "notes").mkdir(parents=True)
    assert project_name(home / "notes", home) == "notes"
    assert project_name(home, home) is None
    assert project_name(Path("/"), home) is None


def test_detect_uses_given_values(tmp_path: Path) -> None:
    ctx = detect(tmp_path, home=tmp_path.parent, host="h.example")
    assert ctx.host == "h"
    assert ctx.project == tmp_path.name.lower()


def test_context_applies(ctx: Context, make_lesson: LessonFactory) -> None:
    assert ctx.applies(make_lesson())
    assert ctx.applies(make_lesson(scope="host:boxone"))
    assert not ctx.applies(make_lesson(scope="host:other"))
    assert ctx.applies(make_lesson(scope="project:webapp"))
    assert not ctx.applies(make_lesson(scope="project:other"))
    homeless = Context(host="boxone", project=None, home=ctx.home, user="alice")
    assert not homeless.applies(make_lesson(scope="project:webapp"))


def test_config_patterns_are_compiled() -> None:
    cfg = config.from_mapping({"redact": {"extra": ["a+"]}})
    assert isinstance(cfg.redact_extra[0], re.Pattern)
