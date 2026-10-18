"""The audit log the console shows: who did what, and who may read it."""

from __future__ import annotations

from typing import Any

from tests.support import Console, ConsoleClient, Session


def read_log(client: ConsoleClient, **filters: Any) -> dict[str, Any]:
    query = "&".join(f"{name}={value}" for name, value in filters.items() if value is not None)
    response = client.get(f"/api/audit?{query}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_sign_in_is_recorded_with_who_signed_in(console: Console, signed_out: ConsoleClient) -> None:
    console.a_team("olive-audit-one")
    console.github.as_(201, "olive-audit-one")
    signed_out.sign_in()

    log = read_log(signed_out)

    assert [(event["kind"], event["actor"]) for event in log["events"]] == [("signed_in", "E1001")]
    assert log["events"][0]["detail"] == {"github": "olive-audit-one"}


def test_a_refused_sign_in_is_recorded_with_the_account_that_tried(console: Console, signed_out: ConsoleClient) -> None:
    console.a_team("olive-audit-two")
    console.github.as_(202, "a-stranger-audit")
    signed_out.sign_in()

    console.github.as_(203, "olive-audit-two")
    signed_out.sign_in()
    log = read_log(signed_out, kind="sign_in_refused")

    assert [(event["kind"], event["actor"]) for event in log["events"]] == [("sign_in_refused", "@a-stranger-audit")]
    assert "isn't linked to a member" in log["events"][0]["detail"]["reason"]


def test_a_member_who_is_not_the_owner_cannot_read_the_log(console: Console, signed_out: ConsoleClient) -> None:
    team, owner_token = console.a_team("olive-audit-three")
    Session(console.server, owner_token).call("add_member", member_id="emp-2", name="Dana Dev")
    console.server.run_cli("link-github", "--team", team, "--member-id", "emp-2", "--github", "dana-audit")
    console.github.as_(204, "dana-audit")
    signed_out.sign_in()

    refused = signed_out.get("/api/audit")

    assert refused.status_code == 403
    assert "Only the team's owner" in refused.json()["message"]


def test_the_log_cannot_be_read_without_signing_in(console: Console, signed_out: ConsoleClient) -> None:
    refused = signed_out.get("/api/audit")

    assert refused.status_code == 401
    assert "Sign in" in refused.json()["message"]


def test_the_log_is_newest_first_and_comes_a_page_at_a_time(console: Console, signed_out: ConsoleClient) -> None:
    console.a_team("olive-audit-four")
    console.github.as_(205, "olive-audit-four")
    for _ in range(3):
        signed_out.sign_in()
        signed_out.sign_out()
    signed_out.sign_in()

    first = read_log(signed_out, limit=2)
    second = read_log(signed_out, limit=2, before=first["next"])

    assert [event["id"] for event in first["events"]] == sorted((e["id"] for e in first["events"]), reverse=True)
    assert first["next"] is not None
    assert min(e["id"] for e in first["events"]) > max(e["id"] for e in second["events"])


def test_the_log_can_be_filtered_by_member_kind_and_day(console: Console, signed_out: ConsoleClient) -> None:
    team, owner_token = console.a_team("olive-audit-five")
    Session(console.server, owner_token).call("add_member", member_id="emp-2", name="Dana Dev")
    console.server.run_cli("link-github", "--team", team, "--member-id", "emp-2", "--github", "dana-audit-five")
    console.github.as_(206, "dana-audit-five")
    signed_out.sign_in()
    signed_out.sign_out()
    console.github.as_(207, "olive-audit-five")
    signed_out.sign_in()

    by_dana = read_log(signed_out, member="emp-2")
    by_kind = read_log(signed_out, kind="signed_in")
    on_the_day = read_log(signed_out, since=console.clock.now.date().isoformat())
    another_day = read_log(signed_out, until="2020-01-01")

    assert {event["actor"] for event in by_dana["events"]} == {"emp-2"}
    assert {event["kind"] for event in by_kind["events"]} == {"signed_in"}
    assert len(on_the_day["events"]) >= 2
    assert another_day["events"] == []


def test_the_log_holds_no_memory_content(console: Console, signed_out: ConsoleClient) -> None:
    team, owner_token = console.a_team("olive-audit-six")
    owner = Session(console.server, owner_token)
    project = owner.call("create_project", name="Billing")["project_id"]
    owner.in_project(project, "billing-api").call(
        "remember",
        title="Use pnpm, not npm",
        summary="Billing uses pnpm.",
        type="convention",
        body="A body that must never be copied into the audit log.",
    )
    console.github.as_(208, "olive-audit-six")
    signed_out.sign_in()

    log = read_log(signed_out)

    assert "must never be copied" not in str(log)


def test_the_log_names_each_memory_by_its_title_now_and_keeps_the_path(console: Console, signed_out: ConsoleClient) -> None:
    team, owner_token = console.a_team("olive-audit-seven")
    owner = Session(console.server, owner_token)
    project = owner.call("create_project", name="Billing")["project_id"]
    remembered = owner.in_project(project, "billing-api").call(
        "remember", title="Use pnpm, not npm", summary="Billing uses pnpm.", type="convention", body="pnpm."
    )
    console.github.as_(209, "olive-audit-seven")
    signed_out.sign_in()

    events = read_log(signed_out)["events"]

    saved = next(event for event in events if event["target"] == remembered["path"])
    assert saved["title"] == "Use pnpm, not npm"
    created = next(event for event in events if event["kind"] == "project_created")
    assert created["title"] is None

