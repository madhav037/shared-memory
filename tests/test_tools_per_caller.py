"""Each caller is listed only the tools they can use (#306): the member tools reach everyone, the admin tools only
the team's admins and owner. Hiding is presentation; a tool still refuses a caller it isn't for."""

from __future__ import annotations

from pathlib import Path

import httpx
import psycopg

from tests.support import RunningServer, Session, Team

MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
ADMIN_TOOLS = {"add_member", "remove_member", "reissue_token"}


def made_admin(team: Team, dana: Session) -> Session:
    with psycopg.connect(team.server.settings.database_url, autocommit=True) as conn:
        conn.execute("UPDATE members SET is_admin = TRUE WHERE member_id = 'emp-2' AND team_id = (SELECT id FROM teams WHERE code = %s)", (team.code,))
    return dana


def listed(session: Session) -> dict[str, str]:
    return session.on_connecting()[1]


def test_a_member_who_is_not_an_admin_is_not_listed_the_admin_tools(dana: Session) -> None:
    tools = listed(dana)

    assert ADMIN_TOOLS.isdisjoint(tools)
    assert {"briefing", "search", "remember", "create_project"} <= set(tools)


def test_an_admin_and_the_owner_are_listed_the_admin_tools(team: Team, dana: Session) -> None:
    assert ADMIN_TOOLS <= set(listed(team.owner()))
    assert ADMIN_TOOLS <= set(listed(made_admin(team, dana)))


def test_a_tool_the_caller_is_not_listed_still_refuses_them_as_before(dana: Session) -> None:
    refused = dana.refusal("add_member", member_id="emp-9", name="Eve")

    assert "Only the team's owner and its admins can manage members and personal tokens." in refused


def test_a_tool_listed_to_everyone_is_described_the_same_to_a_member_and_the_owner(team: Team, dana: Session) -> None:
    shown_to_dana = listed(dana)
    shown_to_owner = listed(team.owner())

    assert shown_to_dana == {name: text for name, text in shown_to_owner.items() if name not in ADMIN_TOOLS}


def test_a_listing_without_a_personal_token_is_answered_as_it_always_was(server: RunningServer) -> None:
    answered = httpx.post(
        f"{server.url}/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )

    names = {tool["name"] for tool in answered.json()["result"]["tools"]}
    assert ADMIN_TOOLS <= names


# The tools that follow the project's state (#307)

CARD_TOOLS = {"update_card", "claim_card", "comment_card", "delete_card"}
CENTS = {"title": "Money amounts", "summary": "Money is integer cents.", "type": "convention", "body": "Integer cents."}


def prompts_of(session: Session) -> set[str]:
    return session.server.portal.call(_prompts_of, session)


async def _prompts_of(session: Session) -> set[str]:
    async with session._connected() as client:
        return {prompt.name for prompt in (await client.list_prompts()).prompts}


def imported_from(session: Session, repository: str) -> None:
    path = session.call("remember", **CENTS)["path"]
    session.call("promote", path=path, level="project", author="emp-2", imported_from=f"{repository}:CLAUDE.md")


def test_a_project_with_no_card_is_listed_only_the_tools_that_start_its_board(owner: Session) -> None:
    tools = set(listed(owner))

    assert {"board", "add_card"} <= tools
    assert CARD_TOOLS.isdisjoint(tools)


def test_the_tools_that_change_a_card_are_listed_once_the_project_has_one(owner: Session, dana: Session) -> None:
    owner.call("add_card", title="Tidy up")

    assert (CARD_TOOLS | {"board", "add_card"}) <= set(listed(owner))
    assert CARD_TOOLS <= set(listed(dana))


def test_a_card_in_one_project_lists_no_card_tool_in_another(team: Team, owner: Session) -> None:
    owner.call("add_card", title="Tidy up")
    payments = team.owner().call("create_project", name="Payments")["project_id"]

    assert CARD_TOOLS.isdisjoint(listed(team.owner().in_project(payments, "payments-api")))


def test_an_unlisted_card_tool_refuses_as_it_always_did(owner: Session) -> None:
    assert "board has no card 1" in owner.refusal("update_card", number=1, title="Nope")


def test_a_member_who_has_not_imported_from_the_repository_is_listed_onboard(owner: Session) -> None:
    assert "onboard" in listed(owner)
    assert "onboard" in prompts_of(owner)


def test_onboard_is_not_listed_once_the_member_has_imported_from_the_repository(owner: Session, dana: Session) -> None:
    imported_from(owner, "billing-api")

    assert "onboard" not in listed(owner)
    assert "onboard" not in prompts_of(owner)
    assert "onboard" in listed(dana)  # another member has still to import


def test_onboard_is_listed_again_in_another_repository_of_the_project(owner: Session, dana: Session, project: str) -> None:
    imported_from(owner, "billing-api")

    elsewhere = owner.in_project(project, "billing-web")
    assert "onboard" in listed(elsewhere)
    assert "onboard" in prompts_of(elsewhere)


def test_a_prompt_listing_without_a_personal_token_is_answered_as_it_always_was(server: RunningServer) -> None:
    answered = httpx.post(
        f"{server.url}/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "prompts/list"}
    )

    assert "onboard" in {prompt["name"] for prompt in answered.json()["result"]["prompts"]}


# The guide, for the coding agents without our skill (#308)

SKILL = (Path(__file__).parent.parent / "src" / "shared_memory" / "skill.md").read_text(encoding="utf-8")


def skill_section(heading: str) -> str:
    body = SKILL.split(f"\n## {heading}\n")[1].split("\n## ")[0]
    return f"## {heading}\n{body}".rstrip()


def test_guide_is_listed_to_codex_and_not_to_claude_code(owner: Session) -> None:
    assert "guide" in listed(owner.as_agent("codex-mcp-client"))
    assert "guide" not in listed(owner.as_agent("claude-code"))


def test_guide_is_listed_to_an_agent_that_reports_no_name(owner: Session) -> None:
    assert "guide" in listed(owner)


def test_guide_gives_a_topic_of_the_skill_word_for_word(owner: Session) -> None:
    codex = owner.as_agent("codex-mcp-client")

    assert codex.call("guide", topic="sessions-and-locks") == skill_section("Sessions and locks")
    assert codex.call("guide", topic="the-board") == skill_section("The board")


def test_guide_refuses_an_unknown_topic_naming_the_topics(owner: Session) -> None:
    refused = owner.as_agent("codex-mcp-client").refusal("guide", topic="cooking")

    for topic in ("promoting-a-memory", "sessions-and-locks", "the-board"):
        assert topic in refused


def test_guide_names_its_topics_in_its_description(owner: Session) -> None:
    description = listed(owner.as_agent("codex-mcp-client"))["guide"]

    assert "promoting-a-memory" in description and "sessions-and-locks" in description
