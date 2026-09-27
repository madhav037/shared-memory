"""Restricted projects: the access list holds in the console and in every Claude session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tests.support import Console, ConsoleClient, Session, add, added_context, ask, create, fetch_project, signed_in, signed_in_owner


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
    browsing = dana.get(f"/api/files?folder=projects/{it.billing}")
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
    assert fetch_project(dana, it.billing)["you_may_change"] is False
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


def a_secret_in(it: ARestrictedProject) -> str:
    """A project memory inside the restricted project."""
    in_billing = it.owner.in_project(it.billing, "billing-api")
    saved = remembered(in_billing, "Salary bands", "SECRET-BODY lives here.")
    path: str = in_billing.call("promote", path=saved["path"], level="project")["path"]
    return path


def test_a_restricted_projects_memory_cant_be_reached_by_path_from_another_project(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-twelve", 815)
    payments = create(signed_out, "Payments")["project_id"]
    secret = a_secret_in(it)
    from_payments = it.dana.in_project(payments, "payments-api")
    remembered(from_payments, "Refunds are asynchronous", "Refunds settle within five days.")

    refusals = {
        "read": from_payments.refusal("read", path=secret),
        "list": from_payments.refusal("list", folder=f"projects/{it.billing}/shared"),
        "retire": from_payments.refusal("retire", path=secret),
        "pin": from_payments.refusal("pin", path=secret),
    }
    everything = from_payments.call("list", folder="projects")

    assert all("is restricted" in refusal for refusal in refusals.values()), refusals
    assert f"projects/{it.billing}" not in everything["folders"]
    assert f"projects/{payments}" in everything["folders"]


def test_the_console_cannot_reach_a_restricted_projects_memory_by_its_path(
    console: Console, signed_out: ConsoleClient
) -> None:
    """Every console read takes a path and works out the project from it, so each one has to refuse on its own."""
    it = restricted(console, signed_out, "olive-closed-thirteen", 816)
    secret = a_secret_in(it)
    dana = signed_in(console, "dana-olive-closed-thirteen", 817)

    answers = [
        dana.get(f"/api/memory?path={secret}"),
        dana.get(f"/api/memory/history?path={secret}"),
        dana.get(f"/api/memory/version?path={secret}&commit=abc1234"),
        dana.get(f"/api/memory/difference?path={secret}&before=abc1234&after=def5678"),
        dana.post_json("/api/memory/pin", {"path": secret}),
        dana.post_json("/api/memory/unpin", {"path": secret}),
        dana.post_json("/api/memory/retire", {"path": secret}),
    ]

    assert [answer.status_code for answer in answers] == [403] * len(answers)
    assert all("is restricted" in answer.json()["message"] for answer in answers)
    assert not any("SECRET-BODY" in answer.text for answer in answers)
    dana.close()


def test_a_challenge_in_a_restricted_project_cant_be_decided_from_outside_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-fourteen", 818)
    payments = create(signed_out, "Payments")["project_id"]
    in_billing = it.owner.in_project(it.billing, "billing-api")
    mine = in_billing.call(
        "promote",
        path=remembered(in_billing, "Staging resets nightly", "The staging database is wiped every night.")["path"],
        level="project",
    )["path"]
    ash = Session(console.server, add(signed_out, "emp-3", "Ash Dev", "ash-closed-fourteen")["personal_token"])
    signed_out.post_json(f"/api/projects/{it.billing}/access", {"employee_id": "emp-3"})
    ash_in_billing = ash.in_project(it.billing, "billing-api")
    offered = remembered(ash_in_billing, "Staging resets at 02:17 UTC", "The staging database is wiped at 02:17 UTC.")
    similar = ash_in_billing.call("promote", path=offered["path"], level="project")
    raised = ash_in_billing.call(
        "promote",
        path=offered["path"],
        level="project",
        reference=similar["reference"],
        resolutions={one["path"]: ("supersede" if one["path"] == mine else "keep_both") for one in similar["similar"]},
    )
    console.clock.advance(days=4)  # past the fallback, when anyone who can reach it may decide

    refused = it.dana.in_project(payments, "payments-api").refusal(
        "decide_challenge", challenge_id=raised["challenge_id"], decision="accept"
    )

    assert "is restricted" in refused


def test_someone_allowed_in_still_reaches_it_by_path_from_another_project(
    console: Console, signed_out: ConsoleClient
) -> None:
    it = restricted(console, signed_out, "olive-closed-fifteen", 819)
    payments = create(signed_out, "Payments")["project_id"]
    secret = a_secret_in(it)
    signed_out.post_json(f"/api/projects/{it.billing}/access", {"employee_id": "emp-2"})

    read = it.dana.in_project(payments, "payments-api").call("read", path=secret)

    assert "SECRET-BODY" in read["body"]
