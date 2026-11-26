# Lesson format (schema 1)

This is the contract between stickit-notes versions, other tools and people
editing lessons by hand. The reference implementation is
`src/stickit/model.py` and `src/stickit/frontmatter.py`.

## File

One lesson per UTF-8 file, `lessons/<id>.md` (or `inbox/<id>.md`), LF line
endings. The file starts with a front matter block between two `---` lines,
followed by the Markdown body.

## Fields

| Field | Required | Type | Rules |
|---|---|---|---|
| `schema` | yes | int | `1` |
| `id` | yes | slug | `^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$`; equals the file name |
| `uid` | yes | ULID | 26 chars, Crockford base32; never changes; identifies the lesson across renames, machines and people |
| `trigger` | yes | string | one line, ≤ 200 chars, ends with `?` |
| `scope` | yes | string | `universal`, `host:<name>` or `project:<name>`; names match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` and are compared lowercase |
| `tags` | no | list | ≤ 12 slugs `^[a-z0-9][a-z0-9_-]{0,31}$`, unique |
| `status` | no | string | `active` (default), `deprecated`, `superseded`, `graduated` (now a standing instruction in CLAUDE.md/AGENTS.md: not injected, still exported) |
| `superseded_by` | if superseded | id | the lesson that replaces this one; not itself |
| `related` | no | list | ≤ 20 lesson ids |
| `created` | yes | date | `YYYY-MM-DD` |
| `updated` | yes | date | `YYYY-MM-DD`, not before `created` |
| `review_after` | no | date | `stickit doctor` warns once it has passed |
| `origin` | no | string | `own` (default) or `imported:<label>` |

The body must not be empty, is at most 8,000 characters, and may contain any
Markdown. Control characters other than tab and newline are rejected. By
convention it states the rule, then `**Why:**` and `**How to apply:**`.

Unknown fields are rejected, so typos are caught instead of silently ignored.

## Scope semantics

A session sees a lesson when it is `active` and its scope matches:

- `universal`: always;
- `host:<name>`: the short host name (`hostname` up to the first dot,
  lowercase) equals `<name>`;
- `project:<name>`: the name of the git work tree containing the session's
  folder equals `<name>`. Outside a git work tree it is the folder's own name.
  The home folder and `/` are never projects.

## Front matter subset

stickit reads and writes a strict subset of YAML so files stay compatible with
GitHub, Obsidian and any YAML parser, without depending on one:

- one `key: value` per line, no nesting, no anchors, tags or multi-line scalars;
- plain scalars, `"double"` quoted (escapes `\" \\ \n \t \/`), `'single'` quoted (`''` for `'`);
- lists as `[a, "b, c"]` or as block items (`  - a`);
- an empty value (`key:`) means "not set";
- `#` starts a comment when preceded by whitespace outside quotes.

When writing, stickit puts ints and dates bare, and quotes any string a YAML
parser would read as something else (`yes`, `null`, `1.0`, `a: b`, ...).

## Graduated lessons in instructions files

`stickit graduate` writes one line per lesson into a block it owns, leaving
the rest of the file untouched:

```markdown
<!-- stickit:begin -->
## Lessons learned (managed by stickit-notes)

- **Trigger question?** The rule. How to apply: the steps. <!-- stickit:<id> -->
<!-- stickit:end -->
```

Entries are matched by id, so graduating again refreshes the entry, and
`--undo` removes it (and the block once empty). Damaged markers are refused,
never guessed at.

## Bundle (version 1)

Several lessons in one file, for sharing. The HTML comments are invisible when
the file is rendered:

```markdown
<!-- stickit-bundle v1 -->
# stickit-notes bundle

2 lesson(s), exported 2026-11-26. Import with `/stickit import <this file>` ...

<!-- stickit:lesson -->
---
(front matter)
---
(body)

<!-- stickit:lesson -->
---
...
```

A plain single lesson file is also a valid import. Imports are capped at 2 MiB
per file and 500 files per folder; terminal escape sequences and control
characters are stripped before parsing.

## Store

```text
stickit.toml        store_version = 1 and settings (marks the folder as a store)
lessons/            accepted lessons
inbox/              imported lessons awaiting review
.state/             private, gitignored: sessions, lock, log
```

## Versioning

- A file with a higher `schema`, a bundle with a higher version, or a store
  with a higher `store_version` is refused with an "upgrade the plugin" message.
- Format changes bump the number and ship with `stickit migrate`.
