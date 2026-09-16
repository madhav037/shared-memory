"""Rules every memory must pass before it is saved."""

from __future__ import annotations

import math
import re
from collections import Counter

from shared_memory.errors import Refused
from shared_memory.identity import NAME_PATTERN
from shared_memory.memory import Memory, type_folder

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("an AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("a GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("an API key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("a connection string with a password", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s@/]{3,}@")),
]
_ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*['\"]?([^\s'\"]{8,})"
)
_PLACEHOLDER = re.compile(r"^(?:\$\{.*\}|<.*>|\*+|x+|\.\.\.+|changeme|example|placeholder|redacted)$", re.IGNORECASE)
_CANDIDATE = re.compile(r"[A-Za-z0-9+/=_-]{32,}")


def _entropy(text: str) -> float:
    counts = Counter(text)
    return -sum(n / len(text) * math.log2(n / len(text)) for n in counts.values())


def _find_secret(text: str) -> str | None:
    for name, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return name
    for match in _ASSIGNMENT.finditer(text):
        if not _PLACEHOLDER.match(match.group(1)):
            return "a password"
    for match in _CANDIDATE.finditer(text):
        token = match.group(0)
        if any(c.isdigit() for c in token) and any(c.isalpha() for c in token) and _entropy(token) >= 4.3:
            return "a high-entropy string that looks like a key or token"
    return None


def _single_line(field: str, value: str, limit: int) -> None:
    if not value.strip():
        raise Refused(f"A memory needs a {field}.")
    if "\n" in value.strip():
        raise Refused(f"The {field} must be one line.")
    if len(value) > limit:
        raise Refused(f"The {field} must be at most {limit} characters.")


def validate(memory: Memory, word_limit: int) -> None:
    _single_line("title", memory.title, 200)
    _single_line("summary", memory.summary, 300)
    type_folder(memory.type)
    for entry in memory.related_files:
        repository, _, path = entry.partition(":")
        if not NAME_PATTERN.match(repository) or not path.strip() or "\n" in entry:
            raise Refused(f"Related file {entry!r} must be written as repository:path, for example billing-api:package.json.")
    words = len(memory.body.split())
    if words > word_limit:
        raise Refused(
            f"This memory is {words} words; the limit is {word_limit} words. Split the subject into a topic: "
            "save several shorter memories under one topic name, each covering one part."
        )
    for text in (memory.title, memory.summary, memory.body, *memory.related_files):
        found = _find_secret(text)
        if found:
            raise Refused(
                f"This memory looks like it contains a secret ({found}). Secrets never go into memory: "
                "remove it and describe where the secret is kept instead."
            )
