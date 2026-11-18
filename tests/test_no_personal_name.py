"""No member, visitor or buyer sees the developer's personal name: the business is Raven (#496).

The only places the GitHub owner may still appear are the install paths, owners and URLs that
move to the raven-memory organisation once it exists (#496, Part 2). Each is listed below by
file and by the exact text allowed there; Part 2 shrinks ALLOWED to nothing. The personal email addresses and the
numeric GitHub account ID are allowed nowhere; they are kept here only as SHA-256 digests.
"""

from __future__ import annotations

import codecs
import hashlib
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
OWNER = "madhav"
# The surname, kept out of this file's own text.
SURNAME = codecs.decode("yrueh", "rot13")

# The personal email address and the numeric GitHub account ID (also inside the GitHub noreply address), by digest.
FORBIDDEN_DIGESTS = frozenset(
    {
        "d29e6a2d4598662372c9c1c41efaf6fc5832966710e3d2065f86aa9a06d1654e",
        "aecb74f899dedd69c4c81803ad7de2fec63887c959a613ef5e72a8a30f29bce7",
    }
)
EMAIL_OR_NUMBER = re.compile(r"[\w.%+-]+@[\w.-]+|\d+")

REPOSITORY = f"{OWNER}037/shared-memory"
ALLOWED: dict[str, tuple[str, ...]] = {
    ".claude-plugin/marketplace.json": (f'"{OWNER}037"', f"github.com/{OWNER}037"),
    "CLAUDE.md": (REPOSITORY,),
    "README.md": (REPOSITORY,),
    "deploy/.env.example": (REPOSITORY,),
    "deploy/compose.yaml": (REPOSITORY,),
    "docs/architecture.html": (f"{REPOSITORY}-platform", REPOSITORY),
    "docs/listing.md": (REPOSITORY, f"`{OWNER}037`"),
    "docs/setup.md": (REPOSITORY,),
    "plugin/.claude-plugin/plugin.json": (REPOSITORY, f'"{OWNER}037"', f"github.com/{OWNER}037"),
    "server.json": (REPOSITORY,),
    "src/shared_memory/config.py": (REPOSITORY,),
    "tests/test_listing.py": (REPOSITORY,),
    "tests/test_settings.py": (REPOSITORY,),
}


def _tracked_files() -> list[str]:
    return subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()


def _text(name: str) -> str | None:
    path = ROOT / name
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def test_the_personal_name_appears_only_in_the_allowed_locations() -> None:
    offenders = []
    for name in _tracked_files():
        if name == "tests/test_no_personal_name.py":
            continue
        text = _text(name)
        if text is None:
            continue
        lowered = text.lower()
        for allowed in sorted(ALLOWED.get(name, ()), key=len, reverse=True):
            lowered = lowered.replace(allowed.lower(), "")
        for word in (OWNER, SURNAME):
            if word in lowered:
                offenders.append(name)
                break
    assert offenders == []


def test_every_allowed_location_still_needs_its_allowance() -> None:
    for name, allowed in ALLOWED.items():
        text = _text(name) or ""
        for entry in allowed:
            assert entry.lower() in text.lower(), f"{name} no longer holds {entry}; drop it"


def test_no_personal_email_or_account_id_appears_anywhere() -> None:
    offenders = []
    for name in _tracked_files():
        text = _text(name)
        if text is None:
            continue
        tokens = {token for match in EMAIL_OR_NUMBER.findall(text) for token in (match, *re.findall(r"\d+", match))}
        if any(hashlib.sha256(token.lower().encode()).hexdigest() in FORBIDDEN_DIGESTS for token in tokens):
            offenders.append(name)
    assert offenders == []
