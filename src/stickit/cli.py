"""Command-line interface. One handler per subcommand; handlers return an exit code.

Exit codes: 0 ok · 1 usage or validation error · 2 store or git error · 3 export refused.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from stickit import __version__, bundle, gitops, graduate, hooks, redact, render
from stickit import config as config_mod
from stickit import context as context_mod
from stickit.doctor import run as run_doctor
from stickit.errors import RedactionError, StickitError, StoreError, ValidationError
from stickit.importer import import_path
from stickit.model import Lesson, Scope, ScopeKind, Status, new_uid, slugify, today
from stickit.session import SessionStore
from stickit.store import Area, Store, atomic_write


@dataclass
class App:
    """Everything a handler needs from the outside world (injectable for tests)."""

    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    cwd: Path = field(default_factory=Path.cwd)
    out: TextIO = field(default_factory=lambda: sys.stdout)
    err: TextIO = field(default_factory=lambda: sys.stderr)
    stdin: TextIO = field(default_factory=lambda: sys.stdin)
    store_override: Path | None = None

    @property
    def root(self) -> Path:
        return self.store_override or config_mod.resolve_store_root(self.env)

    def store(self) -> Store:
        return Store.open(self.root)

    def context(self) -> context_mod.Context:
        return context_mod.detect(self.cwd)

    def say(self, text: str = "") -> None:
        self.out.write(text if text.endswith("\n") else text + "\n")

    def warn(self, text: str) -> None:
        self.err.write(f"warning: {text}\n")


Handler = Callable[[App, argparse.Namespace], int]


# ---- helpers ---------------------------------------------------------------
def _commit(app: App, store: Store, paths: Sequence[Path], message: str) -> None:
    """Commit to the store repo when possible; never fails the command."""
    if not (gitops.available() and gitops.is_repo(store.root)):
        return
    if not gitops.has_identity(store.root):
        app.warn("git user.name/user.email not set; change saved but not committed")
        return
    try:
        gitops.commit(store.root, paths, message)
    except StoreError as exc:
        app.warn(f"saved but not committed: {exc}")


def _read_body(app: App, source: str | None) -> str:
    if source is None:
        raise ValidationError("--body-file is required (use '-' for stdin)")
    if source == "-":
        return app.stdin.read()
    return Path(source).expanduser().read_text(encoding="utf-8")


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(dict.fromkeys(v.strip().lower() for v in value.split(",") if v.strip()))


def _check_new_content(app: App, store: Store, lesson: Lesson, *, allow_personal: bool) -> None:
    """Lessons are meant to be shareable: no secrets, ever; no personal details by default."""
    found = redact.find_secrets(f"{lesson.trigger}\n{lesson.body}")
    if found:
        raise ValidationError(
            f"lesson looks like it contains a secret ({', '.join(found)}); remove it first",
            source=lesson.id,
        )
    cfg = store.config()
    personal = redact.personal_details(lesson, app.context(), cfg.redact_extra, cfg.redact_allow)
    if personal and not allow_personal:
        raise ValidationError(
            f"lesson contains personal details ({', '.join(personal)}); lessons are meant to "
            "be shareable, so write paths as ~/... and leave out names, hosts, emails and "
            "IPs (or pass --allow-personal)",
            source=lesson.id,
        )


_JSON_FIELDS = {"id", "trigger", "body", "scope", "tags", "related", "review_after"}


def _fields(app: App, args: argparse.Namespace) -> dict[str, object]:
    """Lesson fields from ``--json`` (stdin or file) or from individual options.

    JSON input exists so callers such as the /harvest skill never have to
    shell-quote free text.
    """
    if getattr(args, "json_input", None):
        return _fields_from_json(app, args.json_input)
    fields: dict[str, object] = {}
    for key in ("id", "trigger", "scope", "review_after"):
        value = getattr(args, key, None)
        if value is not None:
            fields[key] = value
    for key in ("tags", "related"):
        value = getattr(args, key, None)
        if value is not None:
            fields[key] = _csv(value)
    if args.body_file:
        fields["body"] = _read_body(app, args.body_file)
    return fields


def _fields_from_json(app: App, source: str) -> dict[str, object]:
    raw = app.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"--json: invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ValidationError("--json: expected an object")
    unknown = set(data) - _JSON_FIELDS
    if unknown:
        raise ValidationError(f"--json: unknown field(s) {', '.join(sorted(unknown))}")
    fields: dict[str, object] = {}
    for key, value in data.items():
        if key in ("tags", "related"):
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValidationError(f"--json: {key} must be a list of strings")
            fields[key] = tuple(dict.fromkeys(v.strip().lower() for v in value if v.strip()))
        elif value is None and key == "review_after":
            fields[key] = ""
        elif not isinstance(value, str):
            raise ValidationError(f"--json: {key} must be a string")
        else:
            fields[key] = value
    return fields


def _opt_date(value: object) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        raise ValidationError(f"review_after must be YYYY-MM-DD, got {value!r}") from None


def _all_lessons(store: Store) -> list[Lesson]:
    return store.load_all(Area.LESSONS).lessons


# ---- commands ----------------------------------------------------------------
def cmd_init(app: App, args: argparse.Namespace) -> int:
    root = app.root
    if args.clone:
        if root.exists() and any(root.iterdir()):
            raise StoreError(f"{root} already exists and is not empty")
        gitops.clone(args.clone, root)
        if not Store.is_store(root):
            raise StoreError(
                f"cloned into {root}, but it is not a stickit store (no {config_mod.CONFIG_NAME})"
            )
        store = Store(root)
        loaded = store.load_all()
        store.config()  # validates
        app.say(f"Cloned store to {root}: {len(loaded.lessons)} lesson(s).")
        if loaded.errors:
            app.warn(f"{len(loaded.errors)} invalid lesson file(s); run `stickit doctor`")
        return 0
    store = Store.create(root)
    created_repo = False
    if not args.no_git and gitops.available():
        if not gitops.is_repo(root):
            gitops.init(root)
            created_repo = True
        if args.remote:
            gitops.add_remote(root, args.remote)
        paths = [store.config_path, root / ".gitignore"]
        paths += [store.area_dir(a) / ".gitkeep" for a in Area]
        _commit(app, store, paths, "stickit: create store")
    app.say(f"Created store at {root}{' (new git repo)' if created_repo else ''}.")
    if args.remote:
        app.say("Remote set. Push with `stickit sync`.")
    return 0


def cmd_new(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    fields = _fields(app, args)
    trigger, body = str(fields.get("trigger", "")).strip(), str(fields.get("body", "")).strip()
    if not trigger:
        raise ValidationError("a trigger is required (--trigger or the JSON 'trigger' field)")
    if not body:
        raise ValidationError("a body is required (--body-file or the JSON 'body' field)")
    explicit_id = fields.get("id")
    lesson = Lesson(
        id=str(explicit_id) if explicit_id else store.unique_id(slugify(trigger)),
        uid=new_uid(),
        trigger=trigger,
        body=body,
        scope=Scope.parse(str(fields.get("scope") or "universal")),
        tags=tuple(fields.get("tags", ())),  # type: ignore[arg-type]
        related=tuple(fields.get("related", ())),  # type: ignore[arg-type]
        review_after=_opt_date(fields.get("review_after")),
        created=today(),
        updated=today(),
    )
    _check_new_content(app, store, lesson, allow_personal=args.allow_personal)
    path = store.save(lesson)
    _commit(app, store, [path], f"stickit: add {lesson.id}")
    app.say(f"Added {lesson.id} ({lesson.scope}) -> {path}")
    return 0


def cmd_add(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    source = Path(args.file).expanduser()
    lesson = Lesson.from_text(
        bundle.sanitize(source.read_text(encoding="utf-8")), source=str(source)
    )
    _check_new_content(app, store, lesson, allow_personal=args.allow_personal)
    if store.find_uid(lesson.uid):
        raise StoreError(f"a lesson with uid {lesson.uid} already exists; use `stickit update`")
    path = store.save(lesson)
    _commit(app, store, [path], f"stickit: add {lesson.id}")
    app.say(f"Added {lesson.id} -> {path}")
    return 0


def cmd_update(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    lesson = store.get(args.id)
    fields = _fields(app, args)
    fields.pop("id", None)
    changes: dict[str, object] = {}
    for key in ("trigger", "body"):
        if key in fields:
            changes[key] = str(fields[key]).strip()
    if fields.get("scope"):
        changes["scope"] = Scope.parse(str(fields["scope"]))
    for key in ("tags", "related"):
        if key in fields:
            changes[key] = fields[key]
    if "review_after" in fields:
        changes["review_after"] = _opt_date(fields["review_after"])
    if not changes:
        raise ValidationError("nothing to update; pass at least one field option")
    changes["updated"] = today()
    updated = lesson.with_changes(**changes)
    _check_new_content(app, store, updated, allow_personal=args.allow_personal)
    path = store.save(updated, overwrite=True)
    _commit(app, store, [path], f"stickit: update {lesson.id}")
    app.say(f"Updated {lesson.id}")
    return 0


def cmd_deprecate(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    lesson = store.get(args.id)
    if args.by:
        store.get(args.by)  # must exist
        updated = lesson.with_changes(
            status=Status.SUPERSEDED, superseded_by=args.by, updated=today()
        )
    else:
        updated = lesson.with_changes(status=Status.DEPRECATED, updated=today())
    path = store.save(updated, overwrite=True)
    _commit(app, store, [path], f"stickit: {updated.status.value} {lesson.id}")
    app.say(f"{lesson.id} is now {updated.status.value}")
    return 0


def cmd_remove(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    referrers = [
        x.id
        for x in _all_lessons(store)
        if x.id != args.id and (args.id in x.related or x.superseded_by == args.id)
    ]
    path = store.delete(args.id)
    _commit(app, store, [path], f"stickit: remove {args.id}")
    app.say(f"Removed {args.id} (still in the store's git history)")
    if referrers:
        app.warn(f"still referenced by: {', '.join(referrers)}")
    return 0


def _instructions_file(app: App, lesson: Lesson, args: argparse.Namespace) -> Path:
    """Where a graduated lesson goes: user CLAUDE.md for shared lessons, else the project."""
    if args.file:
        return Path(args.file).expanduser()
    target = args.to or ("project" if lesson.scope.kind is ScopeKind.PROJECT else "user")
    if target == "user":
        if args.agents:
            raise ValidationError(
                "there is no single user-level AGENTS.md; use --to project or --file PATH"
            )
        config_dir = app.env.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
        return Path(config_dir).expanduser() / "CLAUDE.md"
    root = context_mod.project_root(app.cwd, Path.home())
    if root is None:
        raise ValidationError("not inside a project folder; cd into it or pass --file PATH")
    return root / ("AGENTS.md" if args.agents else "CLAUDE.md")


def cmd_graduate(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    lesson = store.get(args.id)
    path = _instructions_file(app, lesson, args)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if args.undo:
        document = graduate.remove(current, lesson.id)
        changed = (
            lesson.with_changes(status=Status.ACTIVE, updated=today())
            if lesson.status is Status.GRADUATED
            else None
        )
    else:
        if not lesson.is_current:
            raise ValidationError(f"{lesson.id} is {lesson.status.value}; it cannot graduate")
        document = graduate.upsert(current, lesson)
        changed = (
            lesson.with_changes(status=Status.GRADUATED, updated=today())
            if lesson.is_active
            else None
        )
    app.out.write(
        "".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                document.splitlines(keepends=True),
                f"{path} (now)",
                f"{path} (after)",
            )
        )
    )
    if args.dry_run:
        app.say("Dry run: nothing written.")
        return 0
    if document != current:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, document)
    if changed is not None:
        saved = store.save(changed, overwrite=True)
        _commit(app, store, [saved], f"stickit: {changed.status.value} {lesson.id}")
    verb = "Removed from" if args.undo else "Written to"
    app.say(f"{verb} {path}; {lesson.id} is {(changed or lesson).status.value}.")
    return 0


def cmd_list(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    area = Area.INBOX if args.inbox else Area.LESSONS
    lessons = store.load_all(area).lessons
    if args.status != "all":
        lessons = [x for x in lessons if x.status.value == args.status]
    if args.scope:
        lessons = [x for x in lessons if str(x.scope) == args.scope or x.scope.kind == args.scope]
    if args.tag:
        lessons = [x for x in lessons if args.tag in x.tags]
    app.out.write(render.as_json(lessons) if args.json else render.table(lessons))
    return 0


def cmd_show(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    lesson = store.get(args.id, Area.INBOX if args.inbox else Area.LESSONS)
    if args.json:
        app.out.write(render.as_json([lesson], with_body=True))
    else:
        app.out.write(lesson.to_text())
    return 0


def cmd_search(app: App, args: argparse.Namespace) -> int:
    needle = args.text.lower()
    hits = [
        x
        for x in _all_lessons(app.store())
        if needle in x.trigger.lower()
        or needle in x.body.lower()
        or needle in x.id
        or needle in x.tags
    ]
    app.out.write(render.as_json(hits) if args.json else render.table(hits))
    return 0


def cmd_doctor(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    report = run_doctor(store, app.context(), today=today())
    for line in report.lines():
        app.say(line)
    return 1 if report.errors else 0


def cmd_export(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    cfg = store.config()
    lessons = _all_lessons(store)
    if args.ids:
        by_id = {x.id: x for x in lessons}
        missing = [i for i in args.ids if i not in by_id]
        if missing:
            raise StoreError(f"no such lesson(s): {', '.join(missing)}")
        chosen = [by_id[i] for i in args.ids]
    else:
        chosen = [x for x in lessons if x.is_current and x.scope == Scope.parse("universal")]
        chosen = [x for x in chosen if not x.is_imported or args.include_imported]
    if not chosen:
        raise ValidationError("nothing to export")
    scoped = [x.id for x in chosen if str(x.scope) != "universal"]
    if scoped and not args.include_scoped:
        raise ValidationError(
            f"not universal: {', '.join(scoped)} (machine/project specific); "
            "pass --include-scoped to export them anyway"
        )
    secrets = {x.id: redact.find_secrets(f"{x.trigger}\n{x.body}") for x in chosen}
    secrets = {k: v for k, v in secrets.items() if v}
    if secrets:
        detail = "; ".join(f"{k}: {', '.join(v)}" for k, v in secrets.items())
        raise RedactionError(f"refusing to export, possible secrets found ({detail})")
    rules = redact.personal_rules(app.context(), cfg.redact_extra)
    texts: list[str] = []
    for lesson in chosen:
        result = redact.redact_lesson(lesson, rules, cfg.redact_allow)
        original = lesson.to_text()
        if result.hits:
            hits = ", ".join(f"{k} x{v}" for k, v in sorted(result.hits.items()))
            app.err.write(f"{lesson.id}: redacted {hits}\n")
            diff = difflib.unified_diff(
                original.splitlines(keepends=True),
                result.text.splitlines(keepends=True),
                f"{lesson.id} (yours)",
                f"{lesson.id} (export)",
            )
            app.err.write("".join(diff))
        if redact.find_secrets(result.text):  # defense in depth
            raise RedactionError(f"refusing to export {lesson.id}: secret survived redaction")
        texts.append(result.text)
    if args.dry_run:
        app.say(f"Dry run: {len(texts)} lesson(s) would be exported; nothing written.")
        return 0
    out = Path(args.out).expanduser()
    if out.exists() and not args.force:
        raise ValidationError(f"{out} exists; pass --force to overwrite")
    payload = texts[0] if len(texts) == 1 else bundle.dump(texts, exported=today())
    out.write_text(payload, encoding="utf-8")
    app.say(f"Exported {len(texts)} lesson(s) to {out}. Review it before sharing.")
    return 0


def cmd_import(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    results = import_path(store, Path(args.path).expanduser(), label=args.label)
    for result in results:
        app.say(f"{result.status:<10} {result.lesson_id}  {result.detail}".rstrip())
    staged = [r for r in results if r.path is not None]
    if staged:
        _commit(
            app, store, [r.path for r in staged if r.path], f"stickit: import from {args.label}"
        )
        app.say(f"{len(staged)} lesson(s) in inbox. Review with `stickit review`.")
    return 0


def cmd_review(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    inbox = store.load_all(Area.INBOX)
    if not inbox.lessons and not inbox.errors:
        app.say("Inbox is empty.")
        return 0
    for lesson in inbox.lessons:
        existing = store.find_uid(lesson.uid)
        app.say(f"=== {lesson.id}  ({lesson.origin}, {lesson.scope})")
        if existing:
            app.say(f"updates your lesson {existing.id}:")
            diff = difflib.unified_diff(
                existing.to_text().splitlines(keepends=True),
                lesson.to_text().splitlines(keepends=True),
                f"{existing.id} (yours)",
                f"{lesson.id} (incoming)",
            )
            app.out.write("".join(diff))
        else:
            app.out.write(lesson.to_text())
        app.say()
    for error in inbox.errors:
        app.warn(str(error))
    app.say("Accept with `stickit promote <id>`, reject with `stickit drop <id>`.")
    return 0


def cmd_promote(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    incoming = store.get(args.id, Area.INBOX)
    existing = store.find_uid(incoming.uid)
    if existing:
        lesson = incoming.with_changes(id=existing.id, created=existing.created, updated=today())
        path = store.save(lesson, overwrite=True)
        action = f"updated {existing.id}"
    else:
        free_id, n = incoming.id, 1
        while store.exists(free_id, Area.LESSONS):
            n += 1
            free_id = f"{incoming.id[:60].rstrip('-')}-{n}"
        lesson = incoming.with_changes(id=free_id, updated=incoming.updated)
        path = store.save(lesson)
        action = f"added {lesson.id}"
    inbox_path = store.delete(args.id, Area.INBOX)
    _commit(app, store, [path, inbox_path], f"stickit: promote {args.id}")
    app.say(f"Promoted: {action}")
    return 0


def cmd_drop(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    path = store.delete(args.id, Area.INBOX)
    _commit(app, store, [path], f"stickit: drop {args.id} from inbox")
    app.say(f"Dropped {args.id} from inbox")
    return 0


def cmd_sync(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    if not gitops.is_repo(store.root):
        raise StoreError("the store is not a git repository")
    for step in gitops.sync(store.root):
        app.say(step)
    return 0


def cmd_migrate(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    cfg = store.config()
    app.say(f"Store is at store_version {cfg.store_version}; nothing to migrate.")
    return 0


def cmd_mark_harvested(app: App, args: argparse.Namespace) -> int:
    store = app.store()
    sessions = SessionStore(store.state_dir)
    session_id = args.session or _latest_session(sessions)
    if session_id is None:
        app.say("No active session found.")
        return 0
    state = sessions.load(session_id)
    state.harvested = True
    sessions.save(session_id, state)
    return 0


def _latest_session(sessions: SessionStore) -> str | None:
    if not sessions.dir.is_dir():
        return None
    files = sorted(sessions.dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0].stem if files else None


def cmd_context(app: App, args: argparse.Namespace) -> int:
    ctx = app.context()
    root = app.root
    info = {
        "host": ctx.host,
        "project": ctx.project,
        "store": str(root),
        "store_exists": Store.is_store(root),
        "lessons_dir": str(root / Area.LESSONS.value),
        "host_scope": f"host:{ctx.host}",
        "project_scope": f"project:{ctx.project}" if ctx.project else None,
    }
    app.out.write(json.dumps(info, indent=2) + "\n")
    return 0


def cmd_hook(app: App, args: argparse.Namespace) -> int:
    return hooks.main(args.event, stdin=app.stdin, stdout=app.out, env=app.env)


# ---- parser --------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:  # noqa: PLR0915 - flat, declarative
    parser = argparse.ArgumentParser(
        prog="stickit",
        description="Portable lessons-learned notes for Claude Code.",
        epilog="Store: $STICKIT_DIR or ~/stickit-notes-data. Docs: "
        "https://github.com/whyzgeek/stickit-notes",
    )
    parser.add_argument("--version", action="version", version=f"stickit-notes {__version__}")
    parser.add_argument("--store", type=Path, help="store folder (overrides $STICKIT_DIR)")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add(name: str, handler: Handler, help_text: str) -> argparse.ArgumentParser:
        command = sub.add_parser(name, help=help_text, description=help_text)
        command.set_defaults(handler=handler)
        return command

    p = add("init", cmd_init, "create a store, or clone your existing one")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--clone", metavar="URL", help="clone an existing notes repo")
    p.add_argument("--remote", metavar="URL", help="git remote for `stickit sync`")
    p.add_argument("--no-git", action="store_true", help="do not create a git repo")

    def lesson_fields(command: argparse.ArgumentParser) -> None:
        command.add_argument("--trigger", help="question that should fire, ending in '?'")
        command.add_argument("--scope", help="universal (default) | host:<name> | project:<name>")
        command.add_argument("--tags", help="comma-separated tags")
        command.add_argument("--related", help="comma-separated related lesson ids")
        command.add_argument("--body-file", metavar="PATH", help="lesson body file, '-' = stdin")
        command.add_argument(
            "--json",
            dest="json_input",
            metavar="PATH",
            help="all fields as a JSON object from a file, '-' = stdin",
        )
        command.add_argument(
            "--allow-personal",
            action="store_true",
            help="allow paths, names, hosts, emails or IPs in the lesson text",
        )

    p = add("new", cmd_new, "create a lesson from options")
    lesson_fields(p)
    p.add_argument("--id", help="lesson id (default: from the trigger)")

    p = add("add", cmd_add, "add a lesson from a lesson file")
    p.add_argument("file")
    p.add_argument("--allow-personal", action="store_true")

    p = add("update", cmd_update, "change fields of a lesson")
    p.add_argument("id")
    lesson_fields(p)
    p.add_argument("--review-after", metavar="YYYY-MM-DD", help="'' clears it")

    p = add("deprecate", cmd_deprecate, "retire a lesson (optionally superseded by another)")
    p.add_argument("id")
    p.add_argument("--by", metavar="ID", help="the lesson that replaces it")

    p = add(
        "graduate",
        cmd_graduate,
        "turn a lesson into a standing instruction in CLAUDE.md or AGENTS.md",
    )
    p.add_argument("id")
    p.add_argument(
        "--to",
        choices=["user", "project"],
        help="user: ~/.claude/CLAUDE.md (default for universal and host lessons); "
        "project: CLAUDE.md at the git root (default for project lessons)",
    )
    p.add_argument("--agents", action="store_true", help="write the project's AGENTS.md")
    p.add_argument("--file", metavar="PATH", help="any other Markdown file")
    p.add_argument("--undo", action="store_true", help="remove it again and reactivate")
    p.add_argument("--dry-run", action="store_true", help="show the diff only")

    p = add("remove", cmd_remove, "delete a lesson (git history keeps it)")
    p.add_argument("id")

    p = add("list", cmd_list, "list lessons")
    p.add_argument("--scope", help="universal, host, project, or an exact scope")
    p.add_argument("--tag")
    p.add_argument("--status", default="active", choices=[*(s.value for s in Status), "all"])
    p.add_argument("--inbox", action="store_true", help="list imported lessons awaiting review")
    p.add_argument("--json", action="store_true")

    p = add("show", cmd_show, "print one lesson")
    p.add_argument("id")
    p.add_argument("--inbox", action="store_true")
    p.add_argument("--json", action="store_true")

    p = add("search", cmd_search, "find lessons by text")
    p.add_argument("text")
    p.add_argument("--json", action="store_true")

    add("doctor", cmd_doctor, "check the store for problems")
    add("context", cmd_context, "show host, project and store paths as JSON")

    p = add("export", cmd_export, "write lessons to a shareable file, with redaction")
    p.add_argument("ids", nargs="*", help="lesson ids (default: all active universal lessons)")
    p.add_argument("--out", required=True, help="output .md file")
    p.add_argument("--include-scoped", action="store_true")
    p.add_argument("--include-imported", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="overwrite --out")

    p = add("import", cmd_import, "import a lesson file, bundle or folder into the inbox")
    p.add_argument("path")
    p.add_argument("--label", required=True, help="who or where it came from, e.g. alice")

    add("review", cmd_review, "show imported lessons awaiting review")
    p = add("promote", cmd_promote, "accept an inbox lesson")
    p.add_argument("id")
    p = add("drop", cmd_drop, "reject an inbox lesson")
    p.add_argument("id")
    add("sync", cmd_sync, "git pull --rebase and push the store")
    add("migrate", cmd_migrate, "upgrade the store format")
    p = add("mark-harvested", cmd_mark_harvested, argparse.SUPPRESS)
    p.add_argument("--session")
    p = add("hook", cmd_hook, argparse.SUPPRESS)
    p.add_argument("event", choices=sorted(hooks.HANDLERS))
    return parser


def main(argv: Sequence[str] | None = None, app: App | None = None) -> int:
    app = app or App()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.store:
        app.store_override = args.store.expanduser()
    handler: Handler = args.handler
    try:
        return handler(app, args)
    except StickitError as exc:
        app.err.write(f"stickit: {exc}\n")
        return exc.exit_code
    except (OSError, ValueError) as exc:
        app.err.write(f"stickit: {exc}\n")
        return 1
