"""Foundations (ADR-0019): promotion puts memory into them, and every read of them says so."""

from __future__ import annotations

from typing import Any

from tests.support import Session, Team, added_context

SERVICES = {
    "title": "Billing runs as three services",
    "summary": "Billing is an API, a ledger worker and a webhook relay.",
    "type": "architecture",
    "body": "Billing is three services: the API takes requests, the ledger worker writes entries, and the relay "
    "delivers webhooks.",
}
POSTGRES = {
    "title": "Postgres is the only database",
    "summary": "We chose Postgres over Mongo for every service.",
    "type": "decision",
    "body": "Every service stores its data in Postgres. We chose it over Mongo because ledgers need transactions.",
}
CENTS = {
    "title": "Money amounts",
    "summary": "Money is integer cents.",
    "type": "convention",
    "body": "All money amounts are stored as integer cents, never floats.",
}
INVOICE = {
    "title": "Invoice",
    "summary": "An invoice is a request for payment sent to a customer.",
    "type": "convention",
    "body": "An invoice is the document asking a customer to pay for what they bought.",
}
BUG = {
    "title": "Refunds hang",
    "summary": "Refunds over 10k hang in the ledger worker.",
    "body": "Refunds above 10000 cents hang in the ledger worker.\n\nWorkaround: split the refund in two.",
}


def remember(session: Session, memory: dict[str, str]) -> str:
    path: str = session.call("remember", **memory)["path"]
    return path


def promote(session: Session, memory: dict[str, str], level: str = "project", **extra: Any) -> dict[str, Any]:
    """Promote a memory, keeping both of any similar memory it is shown, so a test of where it lands isn't one of
    contradictions."""
    personal = remember(session, memory)
    result: dict[str, Any] = session.call("promote", path=personal, level=level, **extra)
    if result["status"] == "similar_memories":
        keep_both = {similar["path"]: "keep_both" for similar in result["similar"]}
        result = session.call(
            "promote", path=personal, level=level, reference=result["reference"], resolutions=keep_both, **extra
        )
    return {**result, "personal": personal}


def test_an_architecture_memory_promoted_to_project_memory_lands_in_its_foundation(owner: Session, project: str) -> None:
    result = promote(owner, SERVICES)

    assert result["status"] == "promoted"
    assert result["path"].startswith(f"projects/{project}/shared/foundations/architecture/")
    memory = owner.call("read", path=result["path"])
    assert (memory["level"], memory["type"], memory["foundation"]) == ("project", "architecture", "architecture")


def test_a_decision_memory_lands_in_decisions_with_or_without_naming_it(owner: Session, project: str) -> None:
    unnamed = promote(owner, POSTGRES)
    named = promote(owner, {**POSTGRES, "title": "Redis is only a cache", "body": "Redis holds nothing durable."}, foundation="decisions")

    for result in (unnamed, named):
        assert result["path"].startswith(f"projects/{project}/shared/foundations/decisions/")


def test_a_foundation_is_a_topic_folder_of_project_memory(owner: Session, project: str) -> None:
    promote(owner, SERVICES)

    folders = owner.call("tree", level="project")["folders"]

    assert [(folder["folder"], folder["memories"][0]["foundation"]) for folder in folders] == [
        (f"projects/{project}/shared/foundations/architecture", "architecture")
    ]


def test_any_other_type_goes_into_product_or_glossary_when_it_names_the_foundation(owner: Session, project: str) -> None:
    product = promote(owner, CENTS, foundation="product")
    glossary = promote(owner, INVOICE, foundation="glossary")

    assert product["path"].startswith(f"projects/{project}/shared/foundations/product/")
    assert glossary["path"].startswith(f"projects/{project}/shared/foundations/glossary/")
    assert owner.call("read", path=product["path"])["type"] == "convention"


def test_a_type_without_a_foundation_is_promoted_as_before(owner: Session, project: str) -> None:
    result = promote(owner, CENTS)

    assert result["path"].startswith(f"projects/{project}/shared/conventions/")
    assert owner.call("read", path=result["path"])["foundation"] is None


def test_a_known_issue_is_refused_by_every_foundation(owner: Session) -> None:
    saved = owner.call("save_known_issue", **BUG)

    # A known issue is never personal memory, so there is nothing of it to promote into a foundation.
    assert "/known-issues/" in saved["path"]
    assert "already project memory" in owner.refusal(
        "promote", path=saved["path"], level="project", foundation="product"
    )


def test_a_foundation_that_does_not_exist_is_refused(owner: Session) -> None:
    refused = owner.refusal("promote", path=remember(owner, CENTS), level="project", foundation="security")

    assert "architecture, product, glossary, decisions" in refused


def test_a_foundation_refuses_a_type_it_does_not_take(owner: Session) -> None:
    assert "takes only architecture" in owner.refusal(
        "promote", path=remember(owner, CENTS), level="project", foundation="architecture"
    )
    assert "takes only decision" in owner.refusal(
        "promote", path=remember(owner, CENTS), level="project", foundation="decisions"
    )


def test_an_architecture_or_decision_memory_is_refused_any_other_foundation(owner: Session) -> None:
    assert "architecture foundation" in owner.refusal(
        "promote", path=remember(owner, SERVICES), level="project", foundation="product"
    )
    assert "decisions foundation" in owner.refusal(
        "promote", path=remember(owner, POSTGRES), level="project", foundation="architecture"
    )


def test_team_memory_has_no_foundations(owner: Session) -> None:
    refused = owner.refusal("promote", path=remember(owner, CENTS), level="team", foundation="product")

    assert "no foundations" in refused
    assert owner.refusal("promote", path=remember(owner, SERVICES), level="team", foundation="architecture")


def test_an_architecture_memory_promoted_to_team_memory_is_unchanged(owner: Session) -> None:
    result = promote(owner, SERVICES, level="team")

    assert result["path"].startswith("team/architecture/")


def test_similar_memories_report_the_foundation_they_sit_in(owner: Session, dana: Session) -> None:
    existing = promote(owner, SERVICES)["path"]

    result = dana.call(
        "promote",
        path=remember(dana, {**SERVICES, "title": "Billing is two services", "body": SERVICES["body"] + " Two."}),
        level="project",
    )

    assert result["status"] == "similar_memories"
    assert [(similar["path"], similar["foundation"]) for similar in result["similar"]] == [(existing, "architecture")]


def test_search_and_the_folder_tree_mark_a_foundation_memory(owner: Session) -> None:
    path = promote(owner, SERVICES)["path"]
    promote(owner, CENTS)

    found = owner.call("search", query="how many services is billing split into")["results"]
    tree = owner.call("tree", level="project")["folders"]

    assert {hit["path"]: hit["foundation"] for hit in found}[path] == "architecture"
    marked = {memory["path"]: memory["foundation"] for folder in tree for memory in folder["memories"]}
    assert sorted(marked.values(), key=str) == [None, "architecture"]


def test_recall_marks_a_foundation_memory(team: Team, owner: Session) -> None:
    promote(owner, SERVICES)

    context = added_context(owner.prompt("how is billing split into services, api and ledger worker?"))

    assert "[project memory, foundation: architecture] Billing runs as three services" in context


# Foundation challenges: a foundation changes at once only by a lead of its project, and otherwise by a challenge one
# of them decides.

FOUNDATION_HEADING = "[foundation challenges waiting for your decision]"
SERVICES_TWO = {**SERVICES, "title": "Billing is two services", "body": SERVICES["body"] + " Two."}
NEWS = "write a haiku about cats"


def supersede(session: Session, memory: dict[str, str], target: str, **extra: Any) -> dict[str, Any]:
    """Promote a memory that is similar to a foundation memory, resolving that one as supersede."""
    personal = remember(session, memory)
    first = session.call("promote", path=personal, level="project")
    assert first["status"] == "similar_memories", first
    resolutions = {one["path"]: ("supersede" if one["path"] == target else "keep_both") for one in first["similar"]}
    result: dict[str, Any] = session.call(
        "promote", path=personal, level="project", reference=first["reference"], resolutions=resolutions, **extra
    )
    return {**result, "personal": personal}


def dana_has_one(owner: Session, dana: Session) -> str:
    """Dana's memory in the architecture foundation, through a challenge its lead accepted."""
    raised = promote(dana, SERVICES)
    accepted = owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")
    path: str = accepted["path"]
    return path


def test_a_non_leads_promotion_into_a_foundation_is_a_challenge_the_personal_memory_waits_on(
    owner: Session, dana: Session, project: str
) -> None:
    raised = promote(dana, SERVICES, reasoning="Billing belongs in architecture.")

    folder = f"projects/{project}/shared/foundations/architecture"
    waiting = dana.call("read", path=raised["personal"])
    assert raised["status"] == "challenge_raised"
    assert raised["challenges"] == folder
    assert waiting["level"] == "personal"
    assert waiting["pending"] == [{"challenge_id": raised["challenge_id"], "kind": "add", "replaces": folder}]
    assert owner.call("tree", level="project")["folders"] == []
    assert "waiting on challenge" in dana.refusal("promote", path=raised["personal"], level="project")


def test_a_leads_promotion_into_a_foundation_lands_at_once(owner: Session) -> None:
    assert promote(owner, SERVICES)["status"] == "promoted"


def test_the_briefing_shows_a_foundation_challenge_apart_from_ordinary_ones(owner: Session, dana: Session) -> None:
    raised = promote(dana, SERVICES, reasoning="Billing belongs in architecture.")

    briefing = added_context(owner.start())

    assert FOUNDATION_HEADING in briefing
    assert "[challenges waiting for your decision]" not in briefing
    assert "The architecture foundation" in briefing
    assert f"Challenge {raised['challenge_id']} by emp-2, yours to decide as a project lead: add " in briefing
    assert "Billing runs as three services" in briefing
    assert "to the architecture foundation" in briefing
    assert "Billing belongs in architecture." in briefing


def test_the_raiser_is_not_told_of_their_own_add_as_a_challenge_against_their_memory(
    owner: Session, dana: Session
) -> None:
    promote(dana, SERVICES)

    assert "decide_challenge" not in added_context(dana.prompt(NEWS))
    assert FOUNDATION_HEADING not in added_context(dana.start())


def test_accepting_an_add_moves_the_memory_into_the_foundation_and_tells_its_raiser(
    owner: Session, dana: Session, project: str
) -> None:
    raised = promote(dana, SERVICES)

    accepted = owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert accepted["status"] == "accepted"
    assert accepted["path"].startswith(f"projects/{project}/shared/foundations/architecture/")
    memory = owner.call("read", path=accepted["path"])
    assert (memory["foundation"], memory["author"]) == ("architecture", "emp-2")
    assert "accepted" in added_context(dana.prompt(NEWS))


def test_rejecting_an_add_leaves_the_memory_personal(owner: Session, dana: Session) -> None:
    raised = promote(dana, SERVICES)

    owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="reject")

    assert dana.call("read", path=raised["personal"])["level"] == "personal"
    assert "rejected" in added_context(dana.prompt(NEWS))
    assert owner.call("tree", level="project")["folders"] == []


def test_only_a_lead_decides_a_foundation_challenge(owner: Session, dana: Session, cole: Session) -> None:
    raised = promote(dana, SERVICES)

    for member in (dana, cole):
        refusal = member.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")
        assert "lead of the project" in refusal
    assert "You raised" in dana.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")
    assert FOUNDATION_HEADING not in added_context(cole.start())


def test_the_author_of_a_foundation_memory_cant_decide_a_challenge_to_it(
    owner: Session, dana: Session, cole: Session
) -> None:
    held = dana_has_one(owner, dana)
    raised = supersede(cole, SERVICES_TWO, held)

    refusal = dana.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert raised["status"] == "challenge_raised"
    assert "lead of the project" in refusal
    assert FOUNDATION_HEADING not in added_context(dana.start())
    assert FOUNDATION_HEADING in added_context(owner.start())


def test_superseding_your_own_foundation_memory_is_a_challenge_unless_you_lead(owner: Session, dana: Session) -> None:
    held = dana_has_one(owner, dana)

    raised = supersede(dana, SERVICES_TWO, held)

    assert raised["status"] == "challenge_raised"
    assert owner.call("read", path=held)["status"] == "active"
    assert [c["decides_as"] for c in owner.call("read", path=held)["open_challenges"]] == ["lead"]
    assert "decide_challenge" not in added_context(dana.prompt(NEWS))


def test_accepting_a_supersede_puts_the_new_memory_in_the_foundation(owner: Session, dana: Session, project: str) -> None:
    held = dana_has_one(owner, dana)
    raised = supersede(dana, SERVICES_TWO, held)

    accepted = owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert accepted["path"].startswith(f"projects/{project}/shared/foundations/architecture/")
    assert owner.call("read", path=held)["status"] == "superseded"
    assert FOUNDATION_HEADING not in added_context(owner.start())


def test_a_lead_supersedes_a_foundation_memory_at_once_even_another_members(owner: Session, dana: Session) -> None:
    held = dana_has_one(owner, dana)

    result = supersede(owner, SERVICES_TWO, held)

    assert result["status"] == "promoted"
    assert "/foundations/architecture/" in result["path"]
    assert owner.call("read", path=held)["status"] == "superseded"


def test_retiring_a_foundation_memory_is_a_challenge_even_for_its_author(owner: Session, dana: Session) -> None:
    held = dana_has_one(owner, dana)

    raised = dana.call("retire", path=held, reasoning="No longer true.")

    assert raised["status"] == "challenge_raised"
    assert owner.call("read", path=held)["status"] == "active"
    briefing = added_context(owner.start())
    assert FOUNDATION_HEADING in briefing
    assert "retire it — reasoning: No longer true." in briefing


def test_accepting_a_retire_challenge_retires_the_foundation_memory(owner: Session, dana: Session) -> None:
    held = dana_has_one(owner, dana)
    raised = dana.call("retire", path=held)

    owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert owner.call("read", path=held)["status"] == "retired"


def test_a_lead_retires_a_foundation_memory_at_once_even_another_members(owner: Session, dana: Session) -> None:
    held = dana_has_one(owner, dana)

    assert owner.call("retire", path=held)["status"] == "retired"


def test_retiring_an_ordinary_project_memory_is_unchanged(owner: Session, dana: Session) -> None:
    path = promote(dana, CENTS)["path"]

    assert dana.call("retire", path=path)["status"] == "retired"


def test_a_supersede_the_foundation_cannot_hold_is_refused_when_asked_for(owner: Session, dana: Session) -> None:
    held = dana_has_one(owner, dana)
    wrong_type = {**SERVICES_TWO, "type": "convention"}

    by_lead = owner.refusal("promote", **_supersede_call(owner, wrong_type, held))
    by_member = dana.refusal("promote", **_supersede_call(dana, wrong_type, held))

    assert "architecture foundation, which takes only architecture" in by_lead
    assert "architecture foundation, which takes only architecture" in by_member
    assert owner.call("read", path=held)["status"] == "active"


def _supersede_call(session: Session, memory: dict[str, str], target: str) -> dict[str, Any]:
    """The arguments of the second promote call, resolving the foundation memory as supersede."""
    personal = remember(session, memory)
    first = session.call("promote", path=personal, level="project")
    assert first["status"] == "similar_memories", first
    resolutions = {one["path"]: ("supersede" if one["path"] == target else "keep_both") for one in first["similar"]}
    return {"path": personal, "level": "project", "reference": first["reference"], "resolutions": resolutions}


def test_a_foundation_challenge_says_a_keeper_or_a_lead_decides(owner: Session, dana: Session) -> None:
    raised = promote(dana, SERVICES)

    assert "keeper of that foundation or a lead of the project decides" in raised["next"]
