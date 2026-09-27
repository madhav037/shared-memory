"""ADR-0009: the console governs memory but never writes or promotes it.

From the console a member pins, unpins, decides challenges and retires. Writing, editing and promoting belong to a
member's own coding agent, because promotion depends on that agent judging whether memories contradict each other
(ADR-0004) and a web page has no model to do it.

The distinction is finer than "the console never changes a file". Accepting a supersede challenge *does* move memory
files: `Lifecycle.decide_challenge` reaches `_accept_supersede`, which reaches the same `_move` that `promote` uses.
What the console must never do is *decide* to promote. So these tests watch the four operations the ADR names rather
than watching the filesystem.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any

import pytest

from shared_memory.lifecycle import Lifecycle
from shared_memory.service import MemoryService
from tests.support import NPM, PNPM, Console, ConsoleClient, Session, add, ask, challenge, promote_now, signed_in_owner

# Unrelated to the npm/pnpm memories, so promoting it finds nothing similar to resolve.
MIGRATIONS = {
    "title": "Migrations run before the deploy",
    "summary": "Database migrations run in their own step before the new version is deployed.",
    "type": "convention",
    "body": "Every database migration runs in its own step before the new version is deployed, never from "
    "application startup.",
}

#: Writing, editing and promoting: the three things ADR-0009 keeps out of the console, as they are spelled in code.
FORBIDDEN: tuple[tuple[type, str], ...] = (
    (MemoryService, "remember"),
    (MemoryService, "edit_memory"),
    (MemoryService, "delete_memory"),
    (Lifecycle, "promote"),
)


def watch_for_writes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every attempt to write, edit or promote memory, without preventing it.

    Recording rather than raising keeps the failure legible: a console route that promotes would otherwise surface
    as whatever status the handler turns an exception into, rather than as the name of the rule it broke.
    """
    reached: list[str] = []

    for holder, name in FORBIDDEN:
        original = getattr(holder, name)

        def watcher(*args: Any, _name: str = name, _original: Any = original, **kwargs: Any) -> Any:
            reached.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(holder, name, watcher)
    return reached


def test_doing_everything_the_console_may_do_to_memory_never_writes_edits_or_promotes(
    console: Console, signed_out: ConsoleClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-governs", 1501)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")
    target = promote_now(in_project, NPM)
    retiring = promote_now(in_project, MIGRATIONS)

    added = add(signed_out, "emp-governs", "Dana Dev", "dana-governs")
    dana = Session(console.server, added["personal_token"], project, "billing-api")
    raised = challenge(dana, PNPM, target)

    reached = watch_for_writes(monkeypatch)

    # Everything ADR-0009 lets the console do to memory, including the two that change it.
    assert signed_out.post_json("/api/memory/pin", {"path": target}).status_code == 200
    assert signed_out.post_json("/api/memory/unpin", {"path": target}).status_code == 200
    assert signed_out.post_json("/api/memory/retire", {"path": retiring}).status_code == 200
    decided = signed_out.post_json(f"/api/challenges/{raised['challenge_id']}/decide", {"decision": "accept"})
    assert decided.status_code == 200, decided.text

    # And the reading it does all day.
    ask(signed_out, "/api/files")
    ask(signed_out, "/api/memory", path=target)
    ask(signed_out, "/api/search", query="packages")
    ask(signed_out, "/api/challenges")

    assert reached == [], f"the console reached {sorted(set(reached))}, which ADR-0009 keeps out of it"


def test_accepting_a_supersede_challenge_moves_memory_without_promoting_it(
    console: Console, signed_out: ConsoleClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case that makes the rule subtle: the console changed memory, and was still allowed to."""
    owner = signed_in_owner(console, signed_out, "olive-supersedes", 1502)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")
    target = promote_now(in_project, NPM)

    added = add(signed_out, "emp-supersedes", "Dana Dev", "dana-supersedes")
    dana = Session(console.server, added["personal_token"], project, "billing-api")
    raised = challenge(dana, PNPM, target)

    reached = watch_for_writes(monkeypatch)
    accepted = signed_out.post_json(f"/api/challenges/{raised['challenge_id']}/decide", {"decision": "accept"})

    assert accepted.status_code == 200, accepted.text
    assert reached == []
    # The memory really did change: what the owner wrote is no longer what the project's memory says.
    assert owner.in_project(project).call("read", path=target)["status"] != "active"


def test_the_watch_catches_a_session_writing_memory(
    console: Console, signed_out: ConsoleClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves the two tests above are not passing because the watch is looking at nothing."""
    owner = signed_in_owner(console, signed_out, "olive-watched", 1503)
    project = owner.call("create_project", name="Billing")["project_id"]
    in_project = owner.in_project(project, "billing-api")

    reached = watch_for_writes(monkeypatch)
    promote_now(in_project, NPM)

    assert reached == ["remember", "promote"]


CONSOLE_API = pathlib.Path(__file__).resolve().parent.parent / "src" / "shared_memory" / "console_api.py"

#: Everything `console_api.py` may ask of the two collaborators that can write memory. Adding to this list is a
#: decision about ADR-0009, which is why it is written out rather than derived.
MAY_ASK: dict[str, set[str]] = {
    "_service": {
        "connection_files",
        "history",
        "read",
        "search_everywhere",
        "source",
        "version",
    },
    "_lifecycle": {"decide_challenge", "retire"},
}


def _asked_of(collaborator: str) -> set[str]:
    """Every method `console_api.py` calls on one of its collaborators."""
    tree = ast.parse(CONSOLE_API.read_text(encoding="utf-8"))
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "self"
        and node.value.attr == collaborator
    }


@pytest.mark.parametrize("collaborator", sorted(MAY_ASK))
def test_the_console_api_asks_nothing_of_memory_that_adr_0009_forbids(collaborator: str) -> None:
    asked = _asked_of(collaborator)

    assert asked <= MAY_ASK[collaborator], (
        f"console_api.py now calls self.{collaborator}.{sorted(asked - MAY_ASK[collaborator])}. "
        "ADR-0009 lets the console pin, unpin, decide challenges and retire, and nothing else that changes memory. "
        "If the new call only reads, add it to MAY_ASK; if it writes, edits or promotes, it belongs in a session."
    )
    assert MAY_ASK[collaborator] <= asked, (
        f"MAY_ASK still allows self.{collaborator}.{sorted(MAY_ASK[collaborator] - asked)}, which the console no "
        "longer calls. A permission nothing uses reads as one the console still has; take it out."
    )
