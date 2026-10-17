"""Each caller is listed only the tools they can use (#306): the member tools reach everyone, the admin tools only
the team's admins and owner. Hiding is presentation; a tool still refuses a caller it isn't for."""

from __future__ import annotations

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
