"""Keep personal details and secrets out of shared lessons.

Two kinds of rules:

* **personal** rules (home path, user, host, email, IP addresses, your own
  ``redact.extra`` patterns) rewrite text to neutral placeholders;
* **secret** rules (API keys, tokens, private keys) never rewrite: a secret in
  a lesson is a problem to fix at the source, so export is refused instead.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from stickit.context import Context
from stickit.model import Lesson


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    replacement: str


SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(rx))
    for name, rx in (
        ("anthropic-key", r"sk-ant-[A-Za-z0-9_-]{20,}"),
        ("openai-style-key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
        ("github-token", r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
        ("huggingface-token", r"\bhf_[A-Za-z0-9]{30,}"),
        ("aws-access-key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        ("google-api-key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
        ("slack-token", r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
        ("private-key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        ("jwt", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        ("bearer-token", r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{24,}=*"),
        ("assigned-secret", r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S{8,}"),
    )
)

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IPV4 = re.compile(r"\b(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b")
_IPV6 = re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){4,7}[0-9A-Fa-f]{1,4}\b")
_PUBLIC_SAFE_IPS = frozenset({"127.0.0.1", "0.0.0.0"})  # noqa: S104 - a literal, not a bind
_MIN_NAME = 3


def find_secrets(text: str) -> list[str]:
    """Names of secret rules that match ``text`` (empty list means clean)."""
    return [name for name, pattern in SECRET_PATTERNS if pattern.search(text)]


def personal_rules(ctx: Context, extra: Sequence[re.Pattern[str]] = ()) -> list[Rule]:
    rules: list[Rule] = []
    homes = {str(ctx.home), f"/home/{ctx.user}", f"/Users/{ctx.user}"}
    for home in sorted(homes, key=len, reverse=True):
        rules.append(Rule("home-path", re.compile(re.escape(home) + r"(?=/|\b|$)"), "~"))
    rules.append(Rule("email", _EMAIL, "<email>"))
    rules.append(Rule("ipv6", _IPV6, "<ip>"))
    rules.append(Rule("ipv4", _IPV4, "<ip>"))
    if len(ctx.host) >= _MIN_NAME:
        rules.append(Rule("hostname", _word(ctx.host), "<host>"))
    if len(ctx.user) >= _MIN_NAME:
        rules.append(Rule("username", _word(ctx.user), "<user>"))
    rules += [Rule("custom", pattern, "<redacted>") for pattern in extra]
    return rules


def _word(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Redaction:
    text: str
    hits: dict[str, int]


def redact(text: str, rules: Iterable[Rule], allow: Sequence[str] = ()) -> Redaction:
    """Apply rules in order; ``allow`` strings are protected from every rule."""
    protected: dict[str, str] = {}
    for index, value in enumerate(sorted(set(allow), key=len, reverse=True)):
        token = f"\x00ALLOW{index}\x00"
        protected[token] = value
        text = text.replace(value, token)
    hits: dict[str, int] = {}
    for rule in rules:

        def _sub(match: re.Match[str], rule: Rule = rule) -> str:
            if rule.name == "ipv4" and match.group(0) in _PUBLIC_SAFE_IPS:
                return match.group(0)
            hits[rule.name] = hits.get(rule.name, 0) + 1
            return rule.replacement

        text = rule.pattern.sub(_sub, text)
    for token, value in protected.items():
        text = text.replace(token, value)
    return Redaction(text=text, hits={k: v for k, v in hits.items() if v})


def redact_lesson(lesson: Lesson, rules: Sequence[Rule], allow: Sequence[str] = ()) -> Redaction:
    """Redacted copy as text, plus hit counts for trigger and body together."""
    trigger = redact(lesson.trigger, rules, allow)
    body = redact(lesson.body, rules, allow)
    hits = dict(trigger.hits)
    for key, count in body.hits.items():
        hits[key] = hits.get(key, 0) + count
    clean = lesson.with_changes(trigger=trigger.text, body=body.text, updated=lesson.updated)
    return Redaction(text=clean.to_text(), hits=hits)


def personal_details(
    lesson: Lesson,
    ctx: Context,
    extra: Sequence[re.Pattern[str]] = (),
    allow: Sequence[str] = (),
) -> list[str]:
    """Kinds of personal detail in a lesson's text (empty when it is shareable as is).

    Lessons are meant to be shareable, so this applies to every scope: the
    store itself may be a public repository.
    """
    return sorted(redact_lesson(lesson, personal_rules(ctx, extra), allow).hits)
