"""Restricted projects: the access list holds in the console and in every Claude session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tests.support import Console, ConsoleClient, Session, added_context
from tests.test_console_browsing import ask, signed_in_owner
from tests.test_console_members import add
from tests.test_console_projects import create, project


@dataclass
class ARestrictedProject:
    """A team with one restricted project, its owner, and a member who is not on its access list."""

    owner: Session
    billing: str
    dana: Session
    dana_id: str = "emp-2"


def restricted(console: Console, client: ConsoleClient, github: str, account: int) -> ARestrictedProject:
    owner = signed_in_owner(console, client, github, account)
    billing = create(client, "Billing")["project_id"]
    dana = Session(console.server, add(client, "emp-2", "Dana Dev", f"dana-{github}")["personal_token"])
    closed = client.post_json(f"/api/projects/{billing}/restrict", {"restricted": True})
    assert closed.status_code == 200, closed.text
    assert closed.json()["restricted"] is True
    return ARestrictedProject(owner, billing, dana)


def signed_in(console: Console, github: str, account: int) -> ConsoleClient:
    client = console.client()
    console.github.as_(account, github)
    client.sign_in()
    return client


def remembered(session: Session, title: str, body: str) -> dict[str, Any]:
    saved: dict[str, Any] = session.call("remember", title=title, summary=f"{title}.", type="gotcha", body=body)
    return saved


def test_a_lead_restricts_a_project_and_the_allowed_still_reach_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-one", 801)

    for_the_owner = it.owner.in_project(it.billing, "billing-api").call("tree")
    signed_out.post_json(f"/api/projects/{it.billing}/access", {"employee_id": "emp-2"})
    for_dana = it.dana.in_project(it.billing, "billing-api").call("tree")

    assert for_the_owner == {"folders": []}
    assert for_dana == {"folders": []}


def test_a_member_without_access_does_not_see_it_listed_or_browse_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-two", 802)
    open_to_everyone = create(signed_out, "Payments")["project_id"]
    dana = signed_in(console, "dana-olive-closed-two", 803)

    listed = ask(dana, "/api/projects")["projects"]
    browsing = dana.get(f"/api/projects/{it.billing}/tree")
    reading = dana.get(f"/api/projects/{it.billing}")

    assert [one["project_id"] for one in listed] == [open_to_everyone]
    assert browsing.status_code == 403
    assert "is restricted" in browsing.json()["message"]
    assert reading.status_code == 403
    dana.close()


def test_a_members_memory_tools_refuse_with_the_same_wording(console: Console, signed_out: ConsoleClient) -> None:
    it = restricted(console, signed_out, "olive-closed-three", 804)
    in_billing = it.dana.in_project(it.billing, "billing-api")

    refusals = [
        in_billing.refusal("tree"),
        in_billing.refusal("search", query="anything"),
        in_billing.refusal("remember", title="A note", summary="A note.", type="gotcha", body="A note."),
    ]

    assert all("is restricted" in refusal for refusal in refusals)
    assert all("Ask one of its project leads" in refusal for refusal in refusals)


def test_a_session_gets_no_briefing_and_no_recall_and_is_told_why(console: Console, signed_out: ConsoleClient) -> None:
    it = restricted(console, signed_out, "olive-closed-four", 805)
    in_billing = it.owner.in_project(it.billing, "billing-api")
    saved = remembered(in_billing, "Staging resets nightly", "The staging database is wiped every night.")
    promoted = in_billing.call("promote", path=saved["path"], level="project")
    in_billing.call("pin", path=promoted["path"])

    started = it.dana.in_project(it.billing, "billing-api").start()
    prompted = it.dana.in_project(it.billing, "billing-api").prompt("what happens to staging overnight")

    assert "hookSpecificOutput" not in started
    assert "is restricted" in started["systemMessage"]
    assert prompted == {}


def test_losing_access_takes_effect_on_the_next_call(console: Console, signed_out: ConsoleClient) -> None:
    it = restricted(console, signed_out, "olive-closed-five", 806)
    signed_out.post_json(f"/api/projects/{it.billing}/access", {"employee_id": "emp-2"})
    while_allowed = it.dana.in_project(it.billing, "billing-api").call("tree")

    signed_out.post(f"/api/projects/{it.billing}/access/emp-2/remove")
    after = it.dana.in_project(it.billing, "billing-api").refusal("tree")

    assert while_allowed == {"folders": []}
    assert "is restricted" in after


def test_unrestricting_keeps_the_access_list_for_next_time(console: Console, signed_out: ConsoleClient) -> None:
    it = restricted(console, signed_out, "olive-closed-six", 807)
    signed_out.post_json(f"/api/projects/{it.billing}/access", {"employee_id": "emp-2"})

    opened = signed_out.post_json(f"/api/projects/{it.billing}/restrict", {"restricted": False})
    closed_again = signed_out.post_json(f"/api/projects/{it.billing}/restrict", {"restricted": True})

    assert opened.json()["restricted"] is False
    assert [one["employee_id"] for one in opened.json()["access"]] == ["emp-2"]
    assert [one["employee_id"] for one in closed_again.json()["access"]] == ["emp-2"]
    assert it.dana.in_project(it.billing, "billing-api").call("tree") == {"folders": []}


def test_team_memory_stays_readable_by_the_whole_team(console: Console, signed_out: ConsoleClient) -> None:
    it = restricted(console, signed_out, "olive-closed-seven", 808)
    payments = create(signed_out, "Payments")["project_id"]
    in_billing = it.owner.in_project(it.billing, "billing-api")
    saved = remembered(in_billing, "Every service logs as JSON", "Every service logs a single JSON object per line.")
    in_billing.call("promote", path=saved["path"], level="team")

    found = it.dana.in_project(payments, "payments-api").call("search", query="how do our services log")

    assert [hit["title"] for hit in found["results"]] == ["Every service logs as JSON"]
    assert found["results"][0]["label"] == "team memory"


def test_a_member_who_does_not_lead_the_project_cannot_restrict_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-eight", 809)
    signed_out.post_json(f"/api/projects/{it.billing}/access", {"employee_id": "emp-2"})
    dana = signed_in(console, "dana-olive-closed-eight", 810)

    opening_it = dana.post_json(f"/api/projects/{it.billing}/restrict", {"restricted": False})
    letting_someone_in = dana.post_json(f"/api/projects/{it.billing}/access", {"employee_id": "E1001"})

    assert opening_it.status_code == 403
    assert "leads and the team's admins" in opening_it.json()["message"]
    assert letting_someone_in.status_code == 403
    assert project(dana, it.billing)["you_may_change"] is False
    dana.close()


def test_a_project_lead_manages_the_access_list_of_their_own_project(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-nine", 811)
    signed_out.post_json(f"/api/projects/{it.billing}/leads", {"employee_id": "emp-2"})
    dana = signed_in(console, "dana-olive-closed-nine", 812)
    add(signed_out, "emp-3", "Ash Dev", "ash-closed-nine")

    let_in = dana.post_json(f"/api/projects/{it.billing}/access", {"employee_id": "emp-3"})
    opened = dana.post_json(f"/api/projects/{it.billing}/restrict", {"restricted": False})

    assert [one["employee_id"] for one in let_in.json()["access"]] == ["emp-3"]
    assert opened.json()["restricted"] is False
    dana.close()


def test_every_change_to_a_projects_access_is_in_the_audit_log(console: Console, signed_out: ConsoleClient) -> None:
    it = restricted(console, signed_out, "olive-closed-ten", 813)

    signed_out.post_json(f"/api/projects/{it.billing}/access", {"employee_id": "emp-2"})
    signed_out.post(f"/api/projects/{it.billing}/access/emp-2/remove")
    signed_out.post_json(f"/api/projects/{it.billing}/restrict", {"restricted": False})

    log = [event for event in signed_out.get("/api/audit").json()["events"] if event["project_id"] == it.billing]
    assert [event["kind"] for event in log] == [
        "project_opened",
        "access_revoked",
        "access_granted",
        "project_restricted",
        "project_created",
    ]
    assert [event["target"] for event in log][1:3] == ["emp-2", "emp-2"]


def test_a_briefing_still_reaches_a_member_who_is_allowed_in(console: Console, signed_out: ConsoleClient) -> None:
    it = restricted(console, signed_out, "olive-closed-eleven", 814)
    signed_out.post_json(f"/api/projects/{it.billing}/access", {"employee_id": "emp-2"})
    in_billing = it.owner.in_project(it.billing, "billing-api")
    saved = remembered(in_billing, "Staging resets nightly", "The staging database is wiped every night.")
    promoted = in_billing.call("promote", path=saved["path"], level="project")
    in_billing.call("pin", path=promoted["path"])

    started = it.dana.in_project(it.billing, "billing-api").start()

    assert "Staging resets nightly" in added_context(started)
