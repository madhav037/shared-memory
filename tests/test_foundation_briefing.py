"""The briefing names a project's foundations, and tells its leads and keepers what is missing (ADR-0019)."""

from __future__ import annotations

from tests.support import Console, ConsoleClient, RunningServer, Session, added_context
from tests.test_foundation_keepers import Crew
from tests.test_foundations import CENTS, INVOICE, POSTGRES, SERVICES, promote

LINE = "Foundations: architecture, product, glossary, decisions. Read the one covering your change first, and follow it."


def leave_outside(server: RunningServer, project: str, path: str, folder: str) -> None:
    """Copy a foundation memory to where project memory of its type sat before foundations: a memory outside."""
    (source,) = server.settings.memory_root.glob(f"*/{path}")
    target = source.parents[5] / "projects" / project / "shared" / folder / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())


def test_every_session_is_told_the_foundations_and_extras_are_named(owner: Session, project: str) -> None:
    owner.call("add_foundation", name="Security model")

    assert "Foundations: architecture, product, glossary, decisions, security-model. Read the one" in added_context(owner.start())


def test_a_lead_is_told_which_foundations_are_missing(owner: Session, project: str) -> None:
    briefing = added_context(owner.start())

    assert LINE in briefing
    assert "No active memory yet in: architecture, product, glossary, decisions." in briefing
    promote(owner, SERVICES, foundation="architecture")
    assert "No active memory yet in: product, glossary, decisions." in added_context(owner.start())


def test_an_open_add_challenge_means_the_foundation_is_not_missing(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 2001)
    old = promote(crew.rae, CENTS)["path"]
    crew.rae.call("add_to_foundation", path=old, foundation="product", reasoning="A product rule.")

    briefing = added_context(crew.owner.start())

    assert "No active memory yet in: architecture, glossary, decisions." in briefing


def test_a_lead_is_told_how_many_memories_sit_outside_their_foundation(server: RunningServer, owner: Session, project: str) -> None:
    for memory, folder in ((SERVICES, "architecture"), (POSTGRES, "decisions")):
        leave_outside(server, project, promote(owner, memory)["path"], folder)

    briefing = added_context(owner.start())

    assert "2 architecture and decision memories sit outside their foundation: add_to_foundation" in briefing


def test_nothing_to_report_adds_nothing_and_a_member_is_told_only_the_foundations(
    console: Console, signed_out: ConsoleClient
) -> None:
    crew = Crew(console, signed_out, 2002)
    for memory, slug in ((SERVICES, "architecture"), (CENTS, "product"), (INVOICE, "glossary"), (POSTGRES, "decisions")):
        promote(crew.owner, memory, foundation=slug)
    crew.assign("emp-kit", "glossary")
    assert "[foundations outside]" not in added_context(crew.owner.start())
    left = promote(crew.owner, {**SERVICES, "title": "Billing has a relay", "body": "The relay delivers webhooks."})
    leave_outside(console.server, crew.project, left["path"], "architecture")

    assert "[foundations missing]" not in added_context(crew.owner.start())
    assert "[foundations outside]" in added_context(crew.owner.start())
    assert "[foundations outside]" in added_context(crew.kit.start())
    member = added_context(crew.bea.start())
    assert LINE in member
    assert "[foundations missing]" not in member and "[foundations outside]" not in member
