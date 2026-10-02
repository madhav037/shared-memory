"""The synonyms CONTEXT.md's glossary keeps out stay out of the code.

Every glossary entry ends with an `_Avoid_:` line. This test reads those lines from CONTEXT.md itself, so editing the
glossary changes the check, and looks for the avoided words in three places:

- **Python names** in `src/`: functions, classes, parameters, attributes and variables. The fields of
  `console_contract.py` and the names and parameters of the MCP tools in `app.py` are among them, so this covers the
  console's JSON API fields and the tools' arguments.
- **Route paths**: every string in `src/` that is a path, such as `/api/console/members`.
- **Console strings**: the text between tags and the quoted strings of `console/src`.

A name is split into its words (`member_api_key` and `memberApiKey` are both member, api, key) and an avoided word must
match a whole word, so "repo" is not found in "report". Plurals and verb endings of an avoided word count as that word.

A text search cannot tell which concept a word is used for. "Holder" is the glossary's own term for the session
holding a lock and is avoided only for a card's assignee. Those uses are listed in `ALLOWED`, each with its reason.
"""

from __future__ import annotations

import ast
import pathlib
import re
from collections.abc import Iterator
from typing import NamedTuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
GLOSSARY = ROOT / "CONTEXT.md"
PYTHON = ROOT / "src"
CONSOLE = ROOT / "console" / "src"

#: Generated from the API contract, whose names are checked where they are written.
GENERATED = ("api/schema.d.ts",)

EXISTING = "existing, see #211"


class Allow(NamedTuple):
    """One legitimate use of an avoided word: the word as the glossary spells it, why it is allowed, and where.

    `paths` are files relative to the repository root, or folders ending in `/`; none means anywhere. `text` is words
    the name or string must contain, in order: "issued" allows `TOKEN_ISSUED` and "Issued on" but not "Open issue".
    Give whichever keeps the exemption as narrow as the use.
    """

    word: str
    reason: str
    paths: tuple[str, ...] = ()
    text: str = ""


SERVER = "src/shared_memory/"
PAGES = "console/src/pages/"
BOARD = (
    SERVER + "app.py",
    SERVER + "board.py",
    SERVER + "console_api.py",
    SERVER + "console_contract.py",
    "console/src/api/client.ts",
    "console/src/lib/board.ts",
    PAGES + "BoardPage.tsx",
)

ALLOWED: tuple[Allow, ...] = (
    # Words the glossary avoids for one concept and uses itself for another.
    Allow("agent", "the glossary's short form of coding agent; avoided only as a name for a session"),
    Allow("history", "a memory's git history, as the Audit log entry calls it; avoided only for the audit log"),
    Allow("archive", "the board's Archive of done cards; avoided only for retiring a memory", BOARD),
    Allow(
        "setup",
        "setting a new server's first team up; avoided only for onboarding",
        (SERVER + "app.py", SERVER + "cli.py", SERVER + "identity.py"),
    ),
    Allow("input", "what a tool call is given; avoided only for an import's source", (SERVER + "app.py",), "tool input"),
    Allow(
        "owner",
        "the team's Owner; avoided only for an author, an assignee or a lock's holder",
        (
            SERVER + "identity.py",
            "console/src/App.tsx",
            PAGES + "AuditLog.tsx",
            PAGES + "ProjectSettings.tsx",
            PAGES + "Team.tsx",
        ),
    ),
    Allow("shared memory", "the product's name; avoided only for project memory and team memory"),
    Allow("share", "the product's name; avoided only for promoting", text="shared memory"),
    Allow("share", "the shared folders of the memory repository, not promoting", (SERVER + "store.py",)),
    Allow(
        "activity",
        "a session's Activity, the glossary's own term; avoided only for the audit log",
        (SERVER + "activity.py", SERVER + "app.py"),
    ),
    # Words with another technical meaning.
    Allow("status", "an HTTP status, the server's status or a memory's status; avoided only for a session's activity"),
    Allow("root", "the root of a folder tree or of the page; avoided only for the team's owner"),
    Allow(
        "lock", "a lock between threads; avoided only for claiming a card", (SERVER + "index.py", SERVER + "store.py")
    ),
    Allow(
        "lock",
        "a session's lock on a file, the glossary's Lock; avoided only for claiming a card",
        (SERVER + "app.py", SERVER + "locks.py"),
    ),
    Allow(
        "lock",
        "the locks a project's active sessions hold, shown on the console's Sessions page; the glossary's Lock",
        (SERVER + "console_api.py", SERVER + "console_contract.py", PAGES + "SessionsPage.tsx"),
    ),
    Allow(
        "activity",
        "a session's Activity, shown on the console's Sessions page; avoided only for the audit log",
        (SERVER + "console_api.py", SERVER + "console_contract.py", PAGES + "SessionsPage.tsx"),
    ),
    Allow("take", "taking a lock on a file, not claiming a card", (SERVER + "locks.py",)),
    Allow("take", "taking a lock on a file, not claiming a card", (SERVER + "app.py",), "take lock"),
    Allow("holder", "the session holding a lock, the glossary's Holder", (SERVER + "locks.py",)),
    Allow(
        "activity",
        "the activity of a lock's holder, the glossary's Activity; avoided only for the audit log",
        (SERVER + "locks.py",),
    ),
    Allow(
        "collision",
        "two sessions on the same work, the glossary's Collision; avoided only for a contradiction between memories",
        (SERVER + "app.py", SERVER + "collisions.py", SERVER + "config.py"),
    ),
    Allow(
        "activity",
        "the activities two sessions collide over, the glossary's Activity; avoided only for the audit log",
        (SERVER + "collisions.py",),
    ),
    Allow("scope", "an ASGI scope and a cancel scope; avoided only for a level or an area", (SERVER + "app.py",)),
    Allow(
        "context",
        "MCP's request context and the context a hook adds to a prompt",
        (SERVER + "app.py", SERVER + "hooks.py"),
    ),
    Allow("callback", "GitHub's OAuth callback address, not a hook", text="callback"),
    Allow(
        "client", "GitHub's OAuth client ID and secret, not a coding agent", (SERVER + "config.py",), "github client"
    ),
    Allow("user", "GitHub's /user address, which is theirs to name", (SERVER + "console_sessions.py",), "/user"),
    Allow("trail", "the folders leading to a memory, or its versions in order; not the audit log"),
    Allow("item", "one element of a list being sorted; not a card", (SERVER + "index.py", SERVER + "store.py")),
    # Ordinary English.
    Allow("delete", "cards, pins and files are deleted; avoided only for retiring a memory"),
    Allow("update", "cards and indexes are updated; avoided only for superseding a memory"),
    Allow("issue", "to issue a personal token, the verb", text="issued"),
    Allow(
        "issue",
        "to issue a personal token, the verb",
        (SERVER + "identity.py", PAGES + "ConnectAgent.tsx", PAGES + "Team.tsx"),
    ),
    Allow("take", "saves take turns", (SERVER + "store.py",), "take turns"),
    Allow(
        "take",
        "taking access or a role away from a member, not claiming a card",
        (PAGES + "ProjectSettings.tsx", PAGES + "Team.tsx"),
    ),
    Allow("take", "what a change takes out of a memory's text", (PAGES + "Challenges.tsx",), "takes out"),
    Allow("take", "what the pinned memories take up of a briefing", (PAGES + "FolderPage.tsx",)),
    Allow(
        "task",
        "what a session is asked to do, not a card",
        (PAGES + "ConnectAgent.tsx",),
        "every task starts with the briefing",
    ),
    Allow("manager", "an example search about a package manager", (PAGES + "SearchPage.tsx",), "package manager"),
    Allow("dev", "a made-up member's name in a placeholder", (PAGES + "Team.tsx",), "dana dev"),
    Allow("note", "the lines a briefing adds after its sections, not memories", (SERVER + "briefing.py",)),
    Allow("notes", "the lines a briefing adds after its sections, not memories", (SERVER + "briefing.py",)),
    Allow(
        "proposal",
        "what promote offers when it finds a similar memory; no challenge is raised",
        (SERVER + "app.py", SERVER + "known_issues.py", SERVER + "lifecycle.py"),
    ),
    # Breaches already on main when this test arrived, left for their own pull requests.
    Allow("replace", EXISTING),
    Allow("creator", EXISTING, (SERVER + "console_contract.py",)),
)


class Avoided(NamedTuple):
    words: tuple[str, ...]  # "API key" is ("api", "key")
    spelled: str  # as the glossary spells it
    term: str  # the term to use instead; "Author, Assignee or Holder" when several entries avoid the word


class Found(NamedTuple):
    path: str  # relative to the repository root, with forward slashes
    line: int
    kind: str
    text: str  # the name or string the word was found in
    avoided: Avoided


ENTRY = re.compile(r"^\*\*(?P<term>[^*]+)\*\*:\s*$")
AVOID = re.compile(r"^_Avoid_:\s*(?P<list>.+)$")
WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")


def words_of(text: str) -> list[str]:
    """`member_api_key`, `memberAPIKey` and "Member API key" are all member, api, key."""
    return [word.lower() for word in WORD.findall(text)]


class Glossary(NamedTuple):
    avoided: list[Avoided]
    terms: list[tuple[str, ...]]  # each term's words


def read_glossary(text: str) -> Glossary:
    spelled_as: dict[tuple[str, ...], str] = {}
    avoided_by: dict[tuple[str, ...], list[str]] = {}
    terms: list[tuple[str, ...]] = []
    term = ""
    for line in text.splitlines():
        if entry := ENTRY.match(line):
            term = entry["term"]
            terms.append(tuple(words_of(term)))
        elif (avoid := AVOID.match(line)) and term:
            for spelled in avoid["list"].split(","):
                # "L1/L2/L3" is three words to avoid, not one phrase.
                for part in spelled.split("/"):
                    if words := tuple(words_of(part)):
                        spelled_as.setdefault(words, part.strip())
                        avoided_by.setdefault(words, []).append(term)
    return Glossary(
        [
            Avoided(words, spelled_as[words], ", ".join(by[:-1]) + " or " + by[-1] if len(by) > 1 else by[0])
            for words, by in avoided_by.items()
        ],
        terms,
    )


def forms(word: str) -> set[str]:
    """The word with its plural and verb endings: archive, archives, archived, archiving."""
    stem = word[:-1] if word.endswith("e") else word
    return {word, word + "s", word + "es", stem + "ed", stem + "ing"}


def places(words: list[str], phrase: tuple[str, ...]) -> Iterator[range]:
    """Where the phrase's words appear in order, the last of them in any of its forms."""
    size = len(phrase)
    for start in range(len(words) - size + 1):
        window = words[start : start + size]
        if window[:-1] == list(phrase[:-1]) and window[-1] in forms(phrase[-1]):
            yield range(start, start + size)


def breaches(text: str, glossary: Glossary) -> Iterator[Avoided]:
    words = words_of(text)
    # "Issue" is avoided for a card, but a "known issue" is a term of its own: a word inside a longer term is that term.
    spoken_for = {at for term in glossary.terms if len(term) > 1 for place in places(words, term) for at in place}
    for entry in glossary.avoided:
        if any(not spoken_for.issuperset(place) for place in places(words, entry.words)):
            yield entry


def python_names(tree: ast.AST) -> Iterator[tuple[int, str, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node.lineno, "function", node.name
        elif isinstance(node, ast.ClassDef):
            yield node.lineno, "class", node.name
        elif isinstance(node, ast.arg):
            yield node.lineno, "parameter", node.arg
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            yield node.lineno, "name", node.id
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            yield node.lineno, "attribute", node.attr
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and ROUTE.match(node.value):
            yield node.lineno, "route", node.value


ROUTE = re.compile(r"^/[A-Za-z0-9_{}:./-]*$")

COMMENT = re.compile(r"/\*.*?\*/|(?<![:\\])//[^\n]*", re.S)
QUOTED = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'|`((?:[^`\\]|\\.)*)`')
#: Text between tags. Anything with `;`, `=`, `|`, `&` or a bracket in it is code that happens to sit between a `>`
#: and a `<`, such as the body of an arrow function.
JSX_TEXT = re.compile(r"(?<![=\s])\s*[>}]([^<>{};=|&()\[\]`\"]*[A-Za-z][^<>{};=|&()\[\]`\"]*)(?=</|<[A-Za-z]|\{)")
PLACEHOLDER = re.compile(r"\$\{[^{}]*\}")
#: A quoted string a member reads has a space in it or starts with a capital; `"owner"` and `"space-between"` are values.
SHOWN = re.compile(r"^[A-Z]|\S\s+\S")
#: Lines whose quoted strings are code even so.
NOT_SHOWN = re.compile(r"^\s*(import|export)\b|\bfrom\s+[\"']|className=")


def console_strings(source: str) -> Iterator[tuple[int, str, str]]:
    # Comments are blanked rather than removed so line numbers hold.
    source = COMMENT.sub(lambda match: re.sub(r"[^\n]", " ", match[0]), source)
    lines = source.splitlines()
    for match in QUOTED.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        text = PLACEHOLDER.sub(" ", next(group for group in match.groups() if group is not None))
        if SHOWN.search(text.strip()) and not NOT_SHOWN.search(lines[line - 1]):
            yield line, "string", " ".join(text.split())
    for match in JSX_TEXT.finditer(source):
        yield source.count("\n", 0, match.start(1)) + 1, "text", " ".join(match[1].split())


def search(glossary: Glossary) -> Iterator[Found]:
    for path in sorted(PYTHON.rglob("*.py")):
        where = path.relative_to(ROOT).as_posix()
        for line, kind, text in python_names(ast.parse(path.read_text(encoding="utf-8"))):
            for entry in breaches(text, glossary):
                yield Found(where, line, kind, text, entry)
    for path in sorted([*CONSOLE.rglob("*.ts"), *CONSOLE.rglob("*.tsx")]):
        where = path.relative_to(ROOT).as_posix()
        if where.endswith(GENERATED) or ".test." in path.name:
            continue
        for line, kind, text in console_strings(path.read_text(encoding="utf-8")):
            for entry in breaches(text, glossary):
                yield Found(where, line, kind, text, entry)


def allowed(found: Found) -> Allow | None:
    words = words_of(found.text)
    for allow in ALLOWED:
        here = not allow.paths or any(
            found.path == path or (path.endswith("/") and found.path.startswith(path)) for path in allow.paths
        )
        said = not allow.text or any(True for _ in places(words, tuple(words_of(allow.text))))
        if tuple(words_of(allow.word)) == found.avoided.words and here and said:
            return allow
    return None


def test_the_glossary_is_read() -> None:
    glossary = read_glossary(GLOSSARY.read_text(encoding="utf-8"))

    instead = {entry.spelled: entry.term for entry in glossary.avoided}
    assert instead["User"] == "Member"
    assert instead["API key"] == "Personal token"
    assert instead["holder"] == "Assignee"
    assert instead["Owner"] == "Author, Assignee or Holder"
    assert {"L1", "L2", "L3"} <= set(instead)
    assert ("personal", "token") in glossary.terms
    assert len(glossary.terms) > 40


def test_words_are_matched_whole() -> None:
    glossary = read_glossary(
        "**Repository**:\nA git repository.\n_Avoid_: Repo\n\n**Personal token**:\nA secret.\n_Avoid_: API key\n\n"
        "**Retire**:\nTo mark.\n_Avoid_: Delete, archive\n\n**Card**:\nWork.\n_Avoid_: Issue\n\n"
        "**Known issue**:\nBroken.\n_Avoid_: Bug\n"
    )

    def found(text: str) -> list[str]:
        return [entry.spelled for entry in breaches(text, glossary)]

    assert found("repo_name") == ["Repo"]
    assert found("listRepos") == ["Repo"]
    assert found("report_name") == []
    assert found("member_api_key") == ["API key"]
    assert found("memberAPIKeys") == ["API key"]
    assert found("key_of_api") == []
    assert found("Archived memories") == ["archive"]
    assert found("/api/console/memories/{id}/delete") == ["Delete"]
    assert found("open_issues") == ["Issue"]
    assert found("known_issues") == []
    assert found("issues_of_known_issues") == ["Issue"]


def test_console_strings_are_what_a_member_reads() -> None:
    source = (
        'import { user } from "./user";\n'
        "// take the next card\n"
        'const label = "Take this card";\n'
        'const role = "owner";\n'
        "const said = `Held by ${holder.name} now`;\n"
        "const pick = (cards: Card[]) => cards.filter((task) => task.open);\n"
        '<p className="holder">The holder is {name}, for now</p>\n'
    )

    assert list(console_strings(source)) == [
        (3, "string", "Take this card"),
        (5, "string", "Held by now"),
        (7, "text", "The holder is"),
        (7, "text", ", for now"),
    ]


def test_an_allowed_use_is_as_narrow_as_it_says() -> None:
    glossary = read_glossary("**Card**:\nWork.\n_Avoid_: Issue\n")
    (issue,) = glossary.avoided

    def reason(path: str, text: str) -> str | None:
        allow = allowed(Found(path, 1, "name", text, issue))
        return allow.reason if allow else None

    assert reason("src/shared_memory/audit.py", "TOKEN_ISSUED") == "to issue a personal token, the verb"
    assert reason("src/shared_memory/board.py", "open_issue") is None


def test_avoided_synonyms_stay_out_of_the_code() -> None:
    glossary = read_glossary(GLOSSARY.read_text(encoding="utf-8"))

    found = [each for each in search(glossary) if not allowed(each)]

    assert not found, (
        f"{len(found)} uses of a word CONTEXT.md's glossary avoids:\n\n"
        + "\n".join(
            f'  {each.path}:{each.line}  {each.kind} {each.text!r} says "{each.avoided.spelled}": '
            f"the glossary's term is {each.avoided.term}"
            for each in found
        )
        + "\n\nRename each to the glossary's term. Where the word means something else there (the glossary avoids "
        "it for one concept only, or it is ordinary English), add a line to ALLOWED in tests/test_glossary.py "
        "saying why:\n\n"
        '    Allow("holder", "the session holding a lock, the glossary\'s Holder", (SERVER + "locks.py",)),\n'
        '    Allow("take", "a quoted instruction, not the claim", (PAGES + "BoardPage.tsx",), "take the next card"),\n\n'
        "The paths (files, or folders ending in /) and the text (words the name or string contains) keep the "
        "exemption as narrow as the use."
    )
