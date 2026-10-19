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
    return result


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
    existing = promote(dana, SERVICES)["path"]

    result = owner.call(
        "promote",
        path=remember(owner, {**SERVICES, "title": "Billing is two services", "body": SERVICES["body"] + " Two."}),
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
