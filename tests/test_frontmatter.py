from __future__ import annotations

import datetime as dt

import pytest

from stickit import frontmatter
from stickit.errors import ValidationError


def test_split_returns_block_and_body() -> None:
    block, body = frontmatter.split("---\na: 1\n---\nhello\n---\nmore\n")
    assert block == "a: 1\n"
    assert body == "hello\n---\nmore\n"


@pytest.mark.parametrize("text", ["no fence\n", "", "---\na: 1\n"])
def test_split_rejects_missing_or_unclosed_fence(text: str) -> None:
    with pytest.raises(ValidationError):
        frontmatter.split(text)


def test_parse_all_supported_forms() -> None:
    block = (
        "plain: some text here\n"
        'dq: "a \\"quoted\\" \\\\ value"\n'
        "sq: 'it''s'\n"
        "empty:\n"
        "flow: [a, \"b, c\", 'd']\n"
        "block:\n"
        "  - one\n"
        "  - 'two'\n"
        "comment: value # trailing\n"
        "# whole-line comment\n"
        "\n"
        "emptyflow: []\n"
    )
    assert frontmatter.parse(block) == {
        "plain": "some text here",
        "dq": 'a "quoted" \\ value',
        "sq": "it's",
        "empty": None,
        "flow": ["a", "b, c", "d"],
        "block": ["one", "two"],
        "comment": "value",
        "emptyflow": [],
    }


def test_hash_inside_quotes_is_not_a_comment() -> None:
    assert frontmatter.parse('a: "x # y"\n') == {"a": "x # y"}


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ("a: 1\na: 2\n", "duplicate key"),
        ("  - orphan\n", "list item without a key"),
        ("a:\n  b: 1\n", "nested"),
        ("just text\n", "expected 'key: value'"),
        ('a: "open\n', "unterminated double"),
        ("a: 'open\n", "unterminated single"),
        ('a: "bad \\q"\n', "unsupported escape"),
        ('a: "x"y"\n', "unescaped"),
        ("a: &anchor x\n", "unsupported YAML"),
        ("a: [x, [y]]\n", "nested collections"),
        ("a: [x, 'y]\n", "unterminated quote"),
        ("a: [x, ]\n", "empty list item"),
        ("a: [x\n", "must end with"),
    ],
)
def test_parse_rejects_unsupported_yaml(block: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        frontmatter.parse(block, source="f.md")


def test_error_carries_source_and_line() -> None:
    with pytest.raises(ValidationError, match=r"f\.md:3"):
        frontmatter.parse("a: 1\nbad line\n", source="f.md")


@pytest.mark.parametrize(
    "value",
    [
        "simple",
        "Has spaces and? question",
        "yes",
        "null",
        "123",
        "1.5e3",
        "key: value",
        "ends with colon:",
        "trailing space ",
        "has # hash",
        'quote " inside',
        "back\\slash",
        "-leading dash",
        "[not a list]",
        "{not a map}",
        "tab\there",
        "new\nline",
        "émoji ✓",
        "",
    ],
)
def test_quote_round_trips(value: str) -> None:
    dumped = frontmatter.dump({"k": value})
    assert frontmatter.parse(dumped) == {"k": value}


def test_dump_lists_and_none_round_trip() -> None:
    fields: dict[str, frontmatter.Value] = {"a": ["x", "y, z", "true"], "b": None, "c": []}
    assert frontmatter.parse(frontmatter.dump(fields)) == fields


def test_dump_rejects_bad_key() -> None:
    with pytest.raises(ValueError, match="invalid key"):
        frontmatter.dump({"bad key": "x"})


def test_dump_writes_ints_and_dates_bare() -> None:
    text = frontmatter.dump({"n": 1, "d": dt.date(2026, 1, 31), "s": "1"})
    assert text == 'n: 1\nd: 2026-01-31\ns: "1"\n'
    assert frontmatter.parse(text) == {"n": "1", "d": "2026-01-31", "s": "1"}
    with pytest.raises(TypeError):
        frontmatter.dump({"b": True})
