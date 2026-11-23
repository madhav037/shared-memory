"""Rules every memory must pass before it is saved."""

from __future__ import annotations

import math
import re
from collections import Counter

from shared_memory.errors import Refused
from shared_memory.memory import KNOWN_ISSUE, Memory, type_folder
from shared_memory.identity import NAME_LIMIT
from shared_memory.locks import PATTERN_LIMIT
from shared_memory.tied import tie_of

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("an AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("a GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("an API key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    # A scheme is bounded, so a run of dotted words is not rescanned to its end from every word.
    ("a connection string with a password", re.compile(r"\b[a-z][a-z0-9+.-]{0,31}://[^\s:/@]+:[^\s@/]{3,}@")),
]
_ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*['\"]?([^\s'\"]{8,})"
)
_PLACEHOLDER = re.compile(r"^(?:\$\{.*\}|<.*>|\*+|x+|\.\.\.+|changeme|example|placeholder|redacted)$", re.IGNORECASE)
_CANDIDATE = re.compile(r"[A-Za-z0-9+/=_-]{32,}")
# Tag characters, bidi controls and zero-width characters. ZWNJ and ZWJ (U+200C, U+200D) stay: emoji and Persian and
# Indic text need them.
_HIDDEN = re.compile("[\U000e0000-\U000e007f\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c\u200b\u2060\ufeff]")

# The word limit bounds what a memory says; this bounds what it weighs, so a few enormous "words" can't slip past it.
# At twenty characters a word, a memory at the word limit still fits, paths and identifiers included.
CHARACTER_LIMIT = 12_000
# A workaround line ("Workaround: ...", as a list item or in bold too) or a "Workaround" heading over its own section.
_WORKAROUND = re.compile(
    r"^\s*(?:(?P<heading>#{1,6})\s+|[-*>]\s+)?[*_]*workarounds?[*_]*\s*(?P<colon>:)?[*_]*\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_HEADING = re.compile(r"^\s*#{1,6}\s")
_SPLIT_IT = "Split the subject into a topic: save several shorter memories under one topic name, each covering one part."


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


def refuse_secret(text: str, what: str = "This memory", where: str = "into memory") -> None:
    """Refuse text that looks like it holds a secret, or that holds a character hiding or reordering what a reader
    sees: memory by default, or whatever else is named, such as a card's title on the board."""
    hidden = _HIDDEN.search(text)
    if hidden:
        raise Refused(
            f"{what} holds a hidden character, U+{ord(hidden.group()):04X}, which carries text no reader sees, "
            "reorders what is shown, or makes different text look the same. Remove it."
        )
    found = _find_secret(text)
    if found:
        raise Refused(
            f"{what} looks like it contains a secret ({found}). Secrets never go {where}: "
            "remove it and describe where the secret is kept instead."
        )


def _single_line(field: str, value: str, limit: int) -> None:
    if not value.strip():
        raise Refused(f"A memory needs a {field}.")
    if "\n" in value.strip():
        raise Refused(f"The {field} must be one line.")
    if len(value) > limit:
        raise Refused(f"The {field} must be at most {limit} characters.")


def _has_workaround(body: str) -> bool:
    lines = body.splitlines()
    for number, line in enumerate(lines):
        # Trailing space is taken off first: a lazy capture before `\s*$` would rescan it from every character.
        match = _WORKAROUND.match(line.rstrip())
        if match is None or not (match.group("heading") or match.group("colon")):
            continue
        if match.group("rest").strip("*_ "):
            return True
        following = next((later for later in lines[number + 1 :] if later.strip()), None)
        if following is not None and not _HEADING.match(following):
            return True
    return False


# How many files one memory ties, and how long one is as written: a repository's name, a colon and a pattern.
TIED_FILE_LIMIT = 20
TIED_FILE_LENGTH = NAME_LIMIT + 1 + PATTERN_LIMIT


def validate_tied_files(tied_files: list[str]) -> None:
    """Refuse more tied files than a memory carries, or one that is too long, can't be one, or holds a secret."""
    if len(tied_files) > TIED_FILE_LIMIT:
        raise Refused(f"A memory ties at most {TIED_FILE_LIMIT} files; tie the folder they share instead, as a glob.")
    for entry in tied_files:
        if len(entry) > TIED_FILE_LENGTH:
            raise Refused(f"Tied file {entry[:80]!r}... is too long: at most {TIED_FILE_LENGTH} characters.")
        tie_of(entry)
        refuse_secret(entry)


def validate(memory: Memory, word_limit: int) -> None:
    _single_line("title", memory.title, 200)
    _single_line("summary", memory.summary, 300)
    type_folder(memory.type)
    validate_tied_files(memory.tied_files)
    if memory.type == KNOWN_ISSUE and not _has_workaround(memory.body):
        raise Refused(
            "A known issue must say how to work around it: add a line 'Workaround: ...', or 'Workaround: none known' "
            "if there isn't one yet."
        )
    words = len(memory.body.split())
    if words > word_limit:
        raise Refused(f"This memory is {words} words; the limit is {word_limit} words. {_SPLIT_IT}")
    if len(memory.body) > CHARACTER_LIMIT:
        raise Refused(
            f"This memory is {len(memory.body)} characters; the limit is {CHARACTER_LIMIT} characters. {_SPLIT_IT}"
        )
    # Each tied file was checked for a secret with the rest of it, above.
    for text in (memory.title, memory.summary, memory.body):
        refuse_secret(text)
