"""A strict, dependency-free subset of YAML front matter.

Supported value forms (one ``key: value`` per line, no nesting):

* empty            ``key:``                -> None
* plain scalar     ``key: some text``      -> str
* quoted scalar    ``key: "a \\"b\\""`` or ``key: 'it''s'`` -> str
* flow list        ``key: [a, "b, c"]``    -> list[str]
* block list       ``key:`` followed by ``  - item`` lines -> list[str]

Everything else (maps, anchors, multi-line scalars, tags) is rejected with a
line-numbered error instead of being guessed at. All scalars stay strings;
typing is the model layer's job. The serializer emits only forms the parser
reads back, and quotes any string a full YAML parser would read as something
other than that string, so files stay compatible with Obsidian and GitHub.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping, Sequence

from stickit.errors import ValidationError

Value = str | list[str] | None
# What dump() accepts: ints and dates are written bare so YAML tools type them.
DumpValue = str | int | dt.date | Sequence[str] | None

FENCE = "---"
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?:\s+(.*))?$")
_BLOCK_ITEM_RE = re.compile(r"^\s+-\s+(.*)$")
_YAML_SPECIAL = re.compile(
    r"^(?:true|false|yes|no|on|off|null|~|[-+]?\d[\d_.:eE+-]*|\.inf|\.nan)$", re.IGNORECASE
)
_PLAIN_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _./:@+()?,'-]*$")


def split(text: str, *, source: str | None = None) -> tuple[str, str]:
    """Return ``(frontmatter, body)``; raise if the text has no front matter block."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != FENCE:
        raise ValidationError("must start with a '---' front matter line", source=source)
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == FENCE:
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    raise ValidationError("front matter is not closed with '---'", source=source)


def parse(block: str, *, source: str | None = None) -> dict[str, Value]:
    """Parse a front matter block (without fences) into a flat dict."""
    result: dict[str, Value] = {}
    pending_list: str | None = None
    for number, raw in enumerate(block.splitlines(), start=1):
        where = f"{source}:{number + 1}" if source else f"line {number + 1}"
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        item = _BLOCK_ITEM_RE.match(raw)
        if item:
            if pending_list is None:
                raise ValidationError("list item without a key", source=where)
            target = result[pending_list]
            if target is None:
                target = result[pending_list] = []
            if not isinstance(target, list):  # pragma: no cover - guarded by pending_list
                raise ValidationError("list item after a scalar value", source=where)
            target.append(_scalar(item.group(1), where))
            continue
        if raw[0].isspace():
            raise ValidationError("nested values are not supported", source=where)
        match = _KEY_RE.match(_strip_comment(raw))
        if not match:
            raise ValidationError(f"expected 'key: value', got {raw.strip()!r}", source=where)
        key, rest = match.group(1), (match.group(2) or "").strip()
        if key in result:
            raise ValidationError(f"duplicate key {key!r}", source=where)
        pending_list = None
        if not rest:
            result[key] = None  # becomes a list if block items follow
            pending_list = key
        elif rest.startswith("["):
            result[key] = _flow_list(rest, where)
        else:
            result[key] = _scalar(rest, where)
    return result


def _strip_comment(line: str) -> str:
    """Drop a trailing `` # comment`` that is outside quotes."""
    quote: str | None = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#" and index > 0 and line[index - 1].isspace():
            return line[:index].rstrip()
    return line.rstrip()


def _scalar(text: str, where: str) -> str:
    text = text.strip()
    if text.startswith('"'):
        if len(text) < 2 or not text.endswith('"'):
            raise ValidationError("unterminated double-quoted string", source=where)
        return _unescape_double(text[1:-1], where)
    if text.startswith("'"):
        if len(text) < 2 or not text.endswith("'"):
            raise ValidationError("unterminated single-quoted string", source=where)
        return text[1:-1].replace("''", "'")
    if text and text[0] in "&*!|>{%@`":
        raise ValidationError(f"unsupported YAML syntax {text[:1]!r}", source=where)
    return text


_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "/": "/"}


def _unescape_double(body: str, where: str) -> str:
    out: list[str] = []
    chars = iter(body)
    for char in chars:
        if char == '"':
            raise ValidationError("unescaped '\"' inside double-quoted string", source=where)
        if char != "\\":
            out.append(char)
            continue
        nxt = next(chars, "")
        if nxt not in _ESCAPES:
            raise ValidationError(f"unsupported escape '\\{nxt}'", source=where)
        out.append(_ESCAPES[nxt])
    return "".join(out)


def _flow_list(text: str, where: str) -> list[str]:
    if not text.endswith("]"):
        raise ValidationError("flow list must end with ']'", source=where)
    inner = text[1:-1].strip()
    if not inner:
        return []
    items: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in inner:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char == ",":
            items.append(_scalar("".join(current), where))
            current = []
        elif char in "[]{}":
            raise ValidationError("nested collections are not supported", source=where)
        else:
            current.append(char)
    if quote:
        raise ValidationError("unterminated quote in list", source=where)
    items.append(_scalar("".join(current), where))
    if any(item == "" for item in items):
        raise ValidationError("empty list item", source=where)
    return items


def quote(value: str) -> str:
    """Render a string so that YAML (and this parser) read back exactly ``value``."""
    if (
        _PLAIN_SAFE.match(value)
        and not _YAML_SPECIAL.match(value)
        and ": " not in value
        and " #" not in value
        and not value.endswith((" ", ":"))
    ):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\t", "\\t")
    return f'"{escaped}"'


def dump(fields: Mapping[str, DumpValue]) -> str:
    """Serialize fields in the given order. None values become ``key:``.

    Ints and dates are written bare (``schema: 1``, ``created: 2026-01-31``) so
    YAML readers type them; :func:`parse` still returns them as strings.
    """
    lines: list[str] = []
    for key, value in fields.items():
        if not _KEY_RE.match(f"{key}:"):
            raise ValueError(f"invalid key {key!r}")
        if value is None:
            lines.append(f"{key}:")
        elif isinstance(value, bool):
            raise TypeError(f"{key}: booleans are not part of the format")
        elif isinstance(value, int | dt.date):
            lines.append(f"{key}: {value}")
        elif isinstance(value, str):
            lines.append(f"{key}: {quote(value)}")
        else:
            lines.append(f"{key}: [{', '.join(_list_item(v) for v in value)}]")
    return "\n".join(lines) + "\n"


def _list_item(value: str) -> str:
    rendered = quote(value)
    if "," in value and not rendered.startswith('"'):
        rendered = f'"{value}"'
    return rendered
