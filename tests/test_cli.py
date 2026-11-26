"""CLI integration tests on a real temporary store with git."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from conftest import LessonFactory, RunCli, git
from stickit import bundle
from stickit.store import Area, Store

BODY = "Measure first, then report, then wait for approval.\n**Why:** surprises broke it."


def init(run_cli: RunCli) -> None:
    assert run_cli("init").code == 0


def new(run_cli: RunCli, trigger: str = "Am I about to change config?", *extra: str) -> str:
    result = run_cli("new", "--trigger", trigger, "--body-file", "-", *extra, stdin=BODY)
    assert result.code == 0, result.err
    return result.out.split()[1]


def test_version_and_help(run_cli: RunCli, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        run_cli("--version")
    assert info.value.code == 0
    assert "stickit-notes 0.1.0" in capsys.readouterr().out


def test_init_creates_git_store(run_cli: RunCli, store_root: Path) -> None:
    result = run_cli("init")
    assert result.code == 0
    assert "new git repo" in result.out
    assert "stickit: create store" in git("log", "--oneline", cwd=store_root)
    assert run_cli("init").code == 2


def test_init_no_git_and_remote(run_cli: RunCli, store_root: Path, tmp_path: Path) -> None:
    assert run_cli("init", "--no-git").code == 0
    assert not (store_root / ".git").exists()
    other = tmp_path / "other"
    result = run_cli("--store", str(other), "init", "--remote", str(tmp_path / "remote.git"))
    assert result.code == 0
    assert "origin" in git("remote", cwd=other)


def test_commands_without_store_explain(run_cli: RunCli) -> None:
    result = run_cli("list")
    assert result.code == 2
    assert "no stickit store" in result.err


def test_new_list_show_search(run_cli: RunCli) -> None:
    init(run_cli)
    lesson_id = new(run_cli, "Am I about to change config?", "--tags", "Infra, workflow")
    assert lesson_id == "am-i-about-to-change-config"
    assert new(run_cli, "Am I about to change config?") == "am-i-about-to-change-config-2"
    listed = run_cli("list")
    assert lesson_id in listed.out
    data = json.loads(run_cli("list", "--json", "--tag", "infra").out)
    assert [x["id"] for x in data] == [lesson_id]
    assert json.loads(run_cli("list", "--json", "--scope", "host").out) == []
    shown = run_cli("show", lesson_id)
    assert shown.out.startswith("---\nschema: 1\n")
    assert json.loads(run_cli("show", lesson_id, "--json").out)[0]["body"].startswith("Measure")
    assert lesson_id in run_cli("search", "APPROVAL").out
    assert json.loads(run_cli("search", "nothing-like-this", "--json").out) == []


def test_new_commits_each_change(run_cli: RunCli, store_root: Path) -> None:
    init(run_cli)
    lesson_id = new(run_cli)
    assert f"stickit: add {lesson_id}" in git("log", "--oneline", cwd=store_root)
    assert git("status", "--porcelain", cwd=store_root) == ""


def test_new_refuses_secrets_and_personal_details(run_cli: RunCli, tmp_path: Path) -> None:
    init(run_cli)
    secret = run_cli("new", "--trigger", "Key?", "--body-file", "-", stdin="use sk-ant-" + "x" * 30)
    assert secret.code == 1 and "secret" in secret.err
    home = str(Path.home())
    local = run_cli("new", "--trigger", "Path?", "--body-file", "-", stdin=f"see {home}/x")
    assert local.code == 1 and "personal details" in local.err
    allowed = run_cli(
        "new", "--trigger", "Path?", "--body-file", "-", "--allow-personal", stdin=f"see {home}/x"
    )
    assert allowed.code == 0
    scoped = run_cli(
        "new",
        "--trigger",
        "Path two?",
        "--scope",
        "project:x",
        "--body-file",
        "-",
        stdin=f"see {home}/x",
    )
    assert scoped.code == 1, "scoped lessons must be shareable too"
    email = run_cli(
        "new", "--trigger", "Mail?", "--body-file", "-", stdin="ask bob@corp.example.com"
    )
    assert email.code == 1 and "email" in email.err


def test_new_validation_errors(run_cli: RunCli, tmp_path: Path) -> None:
    init(run_cli)
    assert run_cli("new", "--trigger", "No question", "--body-file", "-", stdin="x").code == 1
    assert run_cli("new", "--trigger", "Q?").code == 1
    body = tmp_path / "body.md"
    body.write_text("from a file")
    assert run_cli("new", "--trigger", "Q?", "--id", "q", "--body-file", str(body)).code == 0
    assert run_cli("new", "--trigger", "Q?", "--id", "q", "--body-file", str(body)).code == 2
    assert run_cli("new", "--trigger", "Q?", "--scope", "planet:x", "--body-file", "-").code == 1


def test_add_from_file(run_cli: RunCli, make_lesson: LessonFactory, tmp_path: Path) -> None:
    init(run_cli)
    file = tmp_path / "x.md"
    file.write_text(make_lesson(id="from-file").to_text())
    assert run_cli("add", str(file)).code == 0
    again = run_cli("add", str(file))
    assert again.code == 2


def test_update_and_deprecate(run_cli: RunCli, store_root: Path) -> None:
    init(run_cli)
    first = new(run_cli, "First trigger?")
    second = new(run_cli, "Second trigger?")
    assert run_cli("update", first).code == 1
    result = run_cli(
        "update",
        first,
        "--trigger",
        "Changed trigger?",
        "--tags",
        "a,b",
        "--related",
        second,
        "--scope",
        "host:boxone",
        "--review-after",
        "2027-01-01",
        "--body-file",
        "-",
        stdin="new body",
    )
    assert result.code == 0, result.err
    lesson = Store(store_root).get(first)
    assert (lesson.trigger, lesson.tags, lesson.body) == (
        "Changed trigger?",
        ("a", "b"),
        "new body",
    )
    assert str(lesson.review_after) == "2027-01-01"
    assert run_cli("update", first, "--review-after", "").code == 0
    assert Store(store_root).get(first).review_after is None
    assert run_cli("deprecate", second).code == 0
    assert Store(store_root).get(second).status.value == "deprecated"
    assert run_cli("deprecate", first, "--by", second).code == 0
    assert Store(store_root).get(first).superseded_by == second
    assert run_cli("deprecate", first, "--by", "missing").code == 2
    assert "deprecated" in run_cli("list", "--status", "all").out
    assert run_cli("list").out == "No lessons.\n"


def test_doctor(run_cli: RunCli, store_root: Path, make_lesson: LessonFactory) -> None:
    init(run_cli)
    store = Store(store_root)
    assert run_cli("doctor").code == 0
    store.save(make_lesson(id="a", trigger="Am I about to deploy on friday?", related=("ghost",)))
    store.save(make_lesson(id="b", trigger="Am I about to deploy on a friday?"))
    store.save(make_lesson(id="d", review_after=dt.date(2026, 1, 2)))
    store.save(make_lesson(id="e", body=f"in {Path.home()}/x"))
    store.save(make_lesson(id="f"), Area.INBOX)
    clean = run_cli("doctor")
    assert clean.code == 0
    for expected in ("ghost", "near-identical", "review was due", "home-path", "inbox"):
        assert expected in clean.out
    dup = make_lesson(id="g")
    store.save(dup)
    store.save(dup.with_changes(id="h", updated=dup.updated))
    store.save(make_lesson(id="i", body="token: abcdefghijkl"))
    store.save(make_lesson(id="j", superseded_by="nobody"))
    (store.area_dir(Area.LESSONS) / "junk.md").write_text("junk")
    store.config_path.write_text("bad = = toml")
    broken = run_cli("doctor")
    assert broken.code == 1
    for expected in ("is used by", "possible secret", "superseded_by", "junk.md", "config"):
        assert expected in broken.out


def test_export_import_round_trip(run_cli: RunCli, tmp_path: Path, store_root: Path) -> None:
    init(run_cli)
    home = Path.home()
    a = new(run_cli, "Universal one?")
    run_cli("update", a, "--body-file", "-", "--allow-personal", stdin=f"Check {home}/logs first.")
    b = new(run_cli, "Universal two?")
    new(run_cli, "Scoped one?", "--scope", "host:boxone")
    out = tmp_path / "share.md"
    dry = run_cli("export", "--out", str(out), "--dry-run")
    assert dry.code == 0 and not out.exists()
    assert "redacted home-path" in dry.err
    result = run_cli("export", "--out", str(out))
    assert result.code == 0, result.err
    text = out.read_text()
    assert text.startswith(bundle.HEADER)
    assert str(home) not in text
    assert "~/logs" in text
    assert "Scoped one" not in text
    assert run_cli("export", "--out", str(out)).code == 1, "no overwrite without --force"
    assert run_cli("export", "--out", str(out), "--force").code == 0

    friend = tmp_path / "friend"
    assert run_cli("--store", str(friend), "init").code == 0
    imported = run_cli("--store", str(friend), "import", str(out), "--label", "alice")
    assert imported.code == 0, imported.err
    assert imported.out.count("added") == 2
    assert "in inbox" in imported.out
    again = run_cli("--store", str(friend), "import", str(out), "--label", "alice")
    assert again.out.count("duplicate") == 2
    friend_store = Store(friend)
    assert len(friend_store.load_all(Area.INBOX).lessons) == 2
    assert friend_store.load_all().lessons == []
    review = run_cli("--store", str(friend), "review")
    assert "imported:alice" in review.out
    assert run_cli("--store", str(friend), "promote", a).code == 0
    assert run_cli("--store", str(friend), "drop", b).code == 0
    assert run_cli("--store", str(friend), "review").out == "Inbox is empty.\n"
    promoted = friend_store.get(a)
    assert promoted.origin == "imported:alice"
    assert (
        run_cli("--store", str(friend), "import", str(out), "--label", "alice").out.count(
            "duplicate"
        )
        == 1
    )


def test_import_update_flow(run_cli: RunCli, tmp_path: Path, make_lesson: LessonFactory) -> None:
    init(run_cli)
    original = make_lesson(id="shared")
    mine = tmp_path / "mine.md"
    mine.write_text(original.to_text())
    assert run_cli("import", str(mine), "--label", "bob").code == 0
    assert run_cli("promote", "shared").code == 0
    changed = tmp_path / "changed.md"
    changed.write_text(original.with_changes(body="Improved advice.").to_text())
    first = run_cli("import", str(changed), "--label", "bob")
    assert "update" in first.out and "changes shared" in first.out
    changed.write_text(original.with_changes(body="Improved again.").to_text())
    second = run_cli("import", str(changed), "--label", "bob")
    assert "replaced inbox copy" in second.out
    review = run_cli("review")
    assert "updates your lesson shared" in review.out
    assert "+Improved again." in review.out
    assert run_cli("promote", "shared-2").code == 0
    store = Store(tmp_path / "store")
    assert store.get("shared").body == "Improved again."
    assert not store.exists("shared-2", Area.INBOX)


def test_import_rejects_bad_input(
    run_cli: RunCli, tmp_path: Path, make_lesson: LessonFactory
) -> None:
    init(run_cli)
    assert run_cli("import", str(tmp_path / "missing.md"), "--label", "x").code == 1
    assert run_cli("import", str(tmp_path), "--label", "bad label").code == 1
    junk = tmp_path / "junk.md"
    junk.write_text("hello")
    assert run_cli("import", str(junk), "--label", "x").code == 1
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "a.md").write_text(make_lesson(id="one").to_text())
    secret = make_lesson(id="two", body="ghp_" + "a" * 36)
    (folder / "b.md").write_text("\x1b[31m" + secret.to_text())
    result = run_cli("import", str(folder), "--label", "x")
    assert result.code == 0
    assert "added" in result.out and "skipped" in result.out


def test_export_refusals(
    run_cli: RunCli, tmp_path: Path, store_root: Path, make_lesson: LessonFactory
) -> None:
    init(run_cli)
    out = str(tmp_path / "o.md")
    assert run_cli("export", "--out", out).code == 1, "nothing to export"
    scoped = new(run_cli, "Scoped?", "--scope", "project:x")
    assert run_cli("export", scoped, "--out", out).code == 1
    assert run_cli("export", scoped, "--out", out, "--include-scoped").code == 0
    assert Path(out).read_text().startswith("---\n"), "single lesson is a plain lesson file"
    assert run_cli("export", "missing", "--out", out).code == 2
    Store(store_root).save(make_lesson(id="leaky", body="key sk-ant-" + "q" * 30))
    refused = run_cli("export", "leaky", "--out", str(tmp_path / "x.md"))
    assert refused.code == 3 and "secret" in refused.err


def test_init_clone_and_sync(run_cli: RunCli, tmp_path: Path, store_root: Path) -> None:
    remote = tmp_path / "remote.git"
    git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    assert run_cli("init", "--remote", str(remote)).code == 0
    lesson_id = new(run_cli, "Synced lesson?")
    first = run_cli("sync")
    assert first.code == 0, first.err
    assert "pushed main" in first.out

    laptop = tmp_path / "laptop"
    cloned = run_cli("--store", str(laptop), "init", "--clone", str(remote))
    assert cloned.code == 0, cloned.err
    assert "1 lesson(s)" in cloned.out
    assert Store(laptop).get(lesson_id).trigger == "Synced lesson?"
    assert run_cli("--store", str(laptop), "init", "--clone", str(remote)).code == 2

    run_cli(
        "--store", str(laptop), "new", "--trigger", "From laptop?", "--body-file", "-", stdin="x"
    )
    assert run_cli("--store", str(laptop), "sync").code == 0
    assert "pulled" in run_cli("sync").out
    assert Store(store_root).exists("from-laptop")


def test_clone_of_non_store_is_reported(run_cli: RunCli, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    git("init", "-q", "-b", "main", cwd=plain)
    (plain / "README.md").write_text("hi")
    git("add", ".", cwd=plain)
    git("commit", "-q", "-m", "x", cwd=plain)
    result = run_cli("init", "--clone", str(plain))
    assert result.code == 2 and "not a stickit store" in result.err
    assert run_cli("--store", str(tmp_path / "s2"), "init", "--clone=--upload-pack=x").code == 2


def test_sync_without_remote_or_repo(run_cli: RunCli, tmp_path: Path) -> None:
    init(run_cli)
    assert "no git remote" in run_cli("sync").err
    other = tmp_path / "nogit"
    run_cli("--store", str(other), "init", "--no-git")
    assert "not a git repository" in run_cli("--store", str(other), "sync").err


def test_commit_skipped_without_identity(
    run_cli: RunCli, store_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n")
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    result = run_cli("init")
    assert result.code == 0
    assert "not committed" in result.err


def test_migrate_mark_harvested_and_hook(run_cli: RunCli, store_root: Path) -> None:
    init(run_cli)
    assert "nothing to migrate" in run_cli("migrate").out
    assert "No active session" in run_cli("mark-harvested").out
    run_cli("hook", "user-prompt", stdin='{"session_id": "s1", "prompt": "hi"}')
    assert run_cli("mark-harvested").code == 0
    state = json.loads((store_root / ".state" / "sessions" / "s1.json").read_text())
    assert state["harvested"] is True
    assert run_cli("mark-harvested", "--session", "s2").code == 0


def test_new_and_update_from_json(run_cli: RunCli, store_root: Path) -> None:
    init(run_cli)
    data = {
        "id": "quote-safe",
        "trigger": 'Does the user\'s "$HOME" path `need` quoting?',
        "body": "Use JSON input; it never touches a shell.\n**Why:** quoting bugs.",
        "scope": "project:webapp",
        "tags": ["Shell", "shell", "json"],
        "related": [],
        "review_after": "2027-02-03",
    }
    result = run_cli("new", "--json", "-", stdin=json.dumps(data))
    assert result.code == 0, result.err
    lesson = Store(store_root).get("quote-safe")
    assert lesson.trigger == data["trigger"]
    assert lesson.tags == ("shell", "json")
    assert lesson.review_after == dt.date(2027, 2, 3)
    update = {"body": "Changed via JSON.", "review_after": None, "tags": []}
    assert run_cli("update", "quote-safe", "--json", "-", stdin=json.dumps(update)).code == 0
    lesson = Store(store_root).get("quote-safe")
    assert (lesson.body, lesson.review_after, lesson.tags) == ("Changed via JSON.", None, ())


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("not json", "invalid JSON"),
        ("[1]", "expected an object"),
        ('{"trigger": "Q?", "body": "b", "colour": "x"}', "unknown field"),
        ('{"trigger": "Q?", "body": "b", "tags": "a"}', "list of strings"),
        ('{"trigger": 5, "body": "b"}', "must be a string"),
        ('{"body": "b"}', "trigger is required"),
        ('{"trigger": "Q?"}', "body is required"),
        ('{"trigger": "Q?", "body": "b", "review_after": "soon"}', "YYYY-MM-DD"),
    ],
)
def test_json_input_errors(run_cli: RunCli, payload: str, message: str) -> None:
    init(run_cli)
    result = run_cli("new", "--json", "-", stdin=payload)
    assert result.code == 1
    assert message in result.err


def test_context_command(run_cli: RunCli, tmp_path: Path, store_root: Path) -> None:
    project = tmp_path / "Webapp"
    (project / ".git").mkdir(parents=True)
    info = json.loads(run_cli("context", cwd=project).out)
    assert info["project"] == "webapp"
    assert info["project_scope"] == "project:webapp"
    assert info["store_exists"] is False
    assert info["store"] == str(store_root)
    assert info["host_scope"].startswith("host:")


def test_remove(run_cli: RunCli, store_root: Path) -> None:
    init(run_cli)
    first = new(run_cli, "First trigger?")
    second = new(run_cli, "Second trigger?")
    run_cli("update", second, "--related", first)
    result = run_cli("remove", first)
    assert result.code == 0
    assert "still referenced by: " + second in result.err
    assert not Store(store_root).exists(first)
    assert f"stickit: remove {first}" in git("log", "--oneline", cwd=store_root)
    assert run_cli("remove", first).code == 2
