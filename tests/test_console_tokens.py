"""Personal tokens from the console: a member sets their own Claude Code up."""

from __future__ import annotations

from typing import Any

from tests.support import Console, ConsoleClient, Session, ToolRefused


def issue(client: ConsoleClient, path: str = "/api/my-token") -> dict[str, Any]:
    response = client.post(path)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_member_issues_their_own_token_and_the_old_one_stops_working(
    console: Console, signed_out: ConsoleClient
) -> None:
    _, owner_token = console.a_team("olive-token-one")
    console.github.as_(401, "olive-token-one")
    signed_out.sign_in()

    issued = issue(signed_out)

    assert issued["member_id"] == "E1001"
    assert issued["personal_token"].startswith("smt_")
    assert issued["server_url"].startswith("http")
    Session(console.server, issued["personal_token"]).call("create_project", name="Check")  # it works
    try:
        Session(console.server, owner_token).call("create_project", name="With the old token")
        raise AssertionError("the old token still works")
    except ToolRefused as refused:
        assert "revoked" in str(refused)


def test_the_token_is_not_shown_again_afterwards(console: Console, signed_out: ConsoleClient) -> None:
    console.a_team("olive-token-two")
    console.github.as_(402, "olive-token-two")
    signed_out.sign_in()
    issued = issue(signed_out)

    seen_again = signed_out.status()

    assert issued["personal_token"] not in str(seen_again)


def test_the_owner_issues_a_token_for_another_member(console: Console, signed_out: ConsoleClient) -> None:
    _, owner_token = console.a_team("olive-token-three")
    dana = Session(console.server, owner_token).call("add_member", member_id="emp-2", name="Dana Dev")
    console.github.as_(403, "olive-token-three")
    signed_out.sign_in()

    issued = issue(signed_out, "/api/members/emp-2/token")

    assert issued["member_id"] == "emp-2"
    Session(console.server, issued["personal_token"]).call("create_project", name="Dana's check")
    try:
        Session(console.server, dana["personal_token"]).call("create_project", name="With Dana's old token")
        raise AssertionError("Dana's old token still works")
    except ToolRefused as refused:
        assert "revoked" in str(refused)


def test_a_member_cannot_issue_a_token_for_someone_else(console: Console, signed_out: ConsoleClient) -> None:
    team, owner_token = console.a_team("olive-token-four")
    Session(console.server, owner_token).call("add_member", member_id="emp-2", name="Dana Dev")
    console.server.run_cli("link-github", "--team", team, "--member-id", "emp-2", "--github", "dana-token-four")
    console.github.as_(404, "dana-token-four")
    signed_out.sign_in()

    refused = signed_out.post("/api/members/E1001/token")

    assert refused.status_code == 403
    assert "owner" in refused.json()["message"]


def test_issuing_a_token_is_recorded_in_the_audit_log(console: Console, signed_out: ConsoleClient) -> None:
    console.a_team("olive-token-five")
    console.github.as_(405, "olive-token-five")
    signed_out.sign_in()

    issue(signed_out)
    log = signed_out.get("/api/audit?kind=token_issued").json()

    assert [(event["actor"], event["target"]) for event in log["events"]] == [("E1001", "E1001")]
    assert "smt_" not in str(log)


def test_issuing_a_token_needs_the_consoles_own_header(console: Console, signed_out: ConsoleClient) -> None:
    console.a_team("olive-token-six")
    console.github.as_(406, "olive-token-six")
    signed_out.sign_in()

    refused = signed_out.post("/api/my-token", with_header=False)

    assert refused.status_code == 403
