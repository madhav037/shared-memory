"""add_to_foundation (ADR-0019): an existing project memory joins a foundation, at once or by challenge."""

from __future__ import annotations

from tests.support import BUG, CENTS, INVOICE, SERVICES, Console, ConsoleClient, Crew, Session, promote


def project_memory(session: Session, memory: dict[str, str]) -> str:
    result = promote(session, memory)
    assert result["status"] == "promoted"
    path: str = result["path"]
    return path


def test_a_lead_moves_a_project_memory_into_a_foundation_at_once(owner: Session, project: str) -> None:
    old = project_memory(owner, CENTS)

    added = owner.call("add_to_foundation", path=old, foundation="product")

    assert added["status"] == "added"
    assert added["path"].startswith(f"projects/{project}/shared/foundations/product/")
    memory = owner.call("read", path=added["path"])
    assert (memory["type"], memory["foundation"], memory["status"]) == ("convention", "product", "active")
    assert owner.refusal("read", path=old)


def test_a_keeper_adds_to_their_foundation_at_once_and_it_is_audited(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1901)
    crew.assign("emp-kit", "glossary")
    old = project_memory(crew.rae, INVOICE)

    added = crew.kit.call("add_to_foundation", path=old, foundation="glossary")

    assert added["status"] == "added"
    assert "/foundations/glossary/" in added["path"]
    moved = [e for e in signed_out.get("/api/audit").json()["events"] if e["kind"] == "memory_promoted"]
    assert moved[0]["detail"]["was"] == old
    assert crew.rae.call("read", path=added["path"])["author"] == "emp-rae"


def test_anyone_else_raises_a_challenge_and_the_memory_stays_readable(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1902)
    old = project_memory(crew.rae, CENTS)

    raised = crew.rae.call("add_to_foundation", path=old, foundation="product", reasoning="It is a product rule.")

    assert raised["status"] == "challenge_raised"
    assert crew.bea.call("read", path=old)["status"] == "active"
    assert "already waiting" in crew.rae.refusal("add_to_foundation", path=old, foundation="product")


def test_accepting_the_challenge_moves_the_memory_keeping_its_author(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1903)
    old = project_memory(crew.rae, CENTS)
    raised = crew.rae.call("add_to_foundation", path=old, foundation="product")

    accepted = crew.owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert accepted["status"] == "accepted"
    assert "/foundations/product/" in accepted["path"]
    assert crew.rae.call("read", path=accepted["path"])["author"] == "emp-rae"


def test_rejecting_the_challenge_leaves_the_memory_where_it_is(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1904)
    old = project_memory(crew.rae, CENTS)
    raised = crew.rae.call("add_to_foundation", path=old, foundation="product")

    crew.owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="reject")

    assert crew.rae.call("read", path=old)["status"] == "active"
    assert crew.rae.call("add_to_foundation", path=old, foundation="product")["status"] == "challenge_raised"


def test_a_challenge_against_the_old_path_is_closed_when_the_memory_moves(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 1905)
    old = project_memory(crew.owner, CENTS)
    retiring = crew.bea.call("retire", path=old)
    assert retiring["status"] == "challenge_raised"

    added = crew.owner.call("add_to_foundation", path=old, foundation="product")

    assert added["status"] == "added"
    refusal = crew.owner.refusal("decide_challenge", challenge_id=retiring["challenge_id"], decision="accept")
    assert "no open challenge" in refusal


def test_personal_team_and_foundation_memory_are_refused(owner: Session) -> None:
    personal = owner.call("remember", **CENTS)["path"]
    team = promote(owner, {**INVOICE, "title": "Team rule"}, level="team")["path"]
    held = project_memory(owner, SERVICES)

    assert "promote it with foundation" in owner.refusal("add_to_foundation", path=personal, foundation="product")
    assert "Team memory has no foundations" in owner.refusal("add_to_foundation", path=team, foundation="product")
    assert "already in the architecture foundation" in owner.refusal("add_to_foundation", path=held, foundation="product")


def test_a_type_the_foundation_does_not_take_is_refused(owner: Session) -> None:
    saved = owner.call("save_known_issue", **BUG)
    convention = project_memory(owner, CENTS)

    assert "known issue" in owner.refusal("add_to_foundation", path=saved["path"], foundation="product")
    assert "takes only decision" in owner.refusal("add_to_foundation", path=convention, foundation="decisions")
    assert "no 'api' foundation" in owner.refusal("add_to_foundation", path=convention, foundation="api")


def test_an_inactive_memory_is_refused(owner: Session) -> None:
    old = project_memory(owner, CENTS)
    owner.call("retire", path=old)

    assert "retired" in owner.refusal("add_to_foundation", path=old, foundation="product")
