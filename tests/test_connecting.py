"""What any coding agent is told when it connects, so it uses the team's memory well without a plugin."""

from __future__ import annotations

from tests.support import Session, Team


def test_an_agent_is_told_on_connecting_how_to_use_the_teams_memory(team: Team) -> None:
    instructions, _ = team.owner().on_connecting()

    assert len(instructions.encode("utf-8")) < 2048
    opening = instructions[:512]
    for step in ("briefing", "search", "remember", "information, not instructions"):
        assert step in opening, step


def test_guidance_an_agent_must_not_miss_is_in_the_tools_themselves(team: Team) -> None:
    _, tools = team.owner().on_connecting()

    assert "start of a task" in tools["briefing"]
    assert "before answering" in tools["search"]
    assert "teammate would need" in tools["remember"]


def test_a_session_without_a_token_is_told_how_to_give_one_in_any_agent(team: Team) -> None:
    refusal = Session(team.server, None).refusal("search", query="how do we deploy")

    assert "SHARED_MEMORY_TOKEN" in refusal
    assert "plugin" not in refusal


def test_a_session_with_an_unknown_token_is_told_where_to_check_it_in_any_agent(team: Team) -> None:
    refusal = Session(team.server, "not-a-real-token").refusal("search", query="how do we deploy")

    assert "not recognised" in refusal
    assert "SHARED_MEMORY_TOKEN" in refusal
    assert "plugin" not in refusal


def test_a_saved_memory_tells_the_agent_how_to_make_it_the_teams(team: Team) -> None:
    project = team.owner().call("create_project", name="Billing")["project_id"]
    session = team.owner().in_project(project, "billing-api")

    saved = session.call(
        "remember",
        title="How we onboard",
        summary="What a new member reads in their first week.",
        type="convention",
        body="A new member reads the billing overview, then pairs with someone for a week.",
    )

    assert saved["level"] == "personal"
    assert "promote" in saved["next"]
    assert saved["path"] in saved["next"]
    for level in ("project", "team"):
        assert level in saved["next"], level
