"""Challenges and retiring from the console: deciding what the team no longer believes."""

from __future__ import annotations

from typing import Any

from tests.support import Console, ConsoleClient, Session, add, ask, signed_in_owner


def a_team(console: Console, client: ConsoleClient, github: str, account: int) -> tuple[Session, str, Session]:
    owner = signed_in_owner(console, client, github, account)
    project = owner.call("create_project", name="Billing")["project_id"]
    return owner, project, owner.in_project(project, "billing-api")


def remember(session: Session, title: str, body: str) -> str:
    path: str = session.call("remember", title=title, summary=f"{title}.", type="convention", body=body)["path"]
    return path


def promoted(session: Session, path: str) -> str:
    answer: str = session.call("promote", path=path, level="project")["path"]
    return answer


def a_supersede_challenge(challenger: Session, path: str) -> int:
    """Offer a memory in place of whatever it is similar to, which challenges that memory's author."""
    similar = challenger.call("promote", path=path, level="project")
    raised = challenger.call(
        "promote",
        path=path,
        level="project",
        reference=similar["reference"],
        resolutions={one["path"]: "supersede" for one in similar["similar"]},
    )
    challenge_id: int = raised["challenge_id"]
    return challenge_id


def challenges(client: ConsoleClient) -> dict[str, Any]:
    return ask(client, "/api/challenges")


def decide(client: ConsoleClient, challenge_id: int, decision: str) -> Any:
    return client.post_json(f"/api/challenges/{challenge_id}/decide", {"decision": decision})


def a_member(console: Console, owner_client: ConsoleClient, employee_id: str, github: str, account: int) -> ConsoleClient:
    add(owner_client, employee_id, f"Dana {employee_id}", github)
    client = console.client()
    console.github.as_(account, github)
    client.sign_in()
    return client


def test_the_console_shows_the_challenges_waiting_for_my_decision(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-one", 1101)
    mine = promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    theirs = remember(dana, "Use npm, not pnpm", "We use npm for every package.")
    challenge_id = a_supersede_challenge(dana, theirs)

    waiting = challenges(signed_out)["waiting"]

    assert [one["challenge_id"] for one in waiting] == [challenge_id]
    assert waiting[0]["kind"] == "supersede"
    assert waiting[0]["raised_by"] == "emp-2"
    assert waiting[0]["yours"] is True
    assert waiting[0]["project_id"] == project
    assert waiting[0]["target"]["path"] == mine
    assert waiting[0]["target"]["body"] == "We use pnpm for every package."
    assert waiting[0]["challenger"]["path"] == theirs
    assert waiting[0]["challenger"]["body"] == "We use npm for every package."


def test_accepting_a_challenge_supersedes_the_memory(console: Console, signed_out: ConsoleClient) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-two", 1102)
    mine = promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    challenge_id = a_supersede_challenge(dana, remember(dana, "Use npm, not pnpm", "We use npm for every package."))

    accepted = decide(signed_out, challenge_id, "accept")

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["waiting"] == []
    superseded = ask(signed_out, "/api/memory", path=mine)
    assert superseded["status"] == "superseded"
    assert superseded["superseded_by"] is not None
    assert ask(signed_out, "/api/memory", path=superseded["superseded_by"])["level"] == "project"


def test_rejecting_a_challenge_leaves_the_memory_alone(console: Console, signed_out: ConsoleClient) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-three", 1103)
    mine = promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    challenge_id = a_supersede_challenge(dana, remember(dana, "Use npm, not pnpm", "We use npm for every package."))

    rejected = decide(signed_out, challenge_id, "reject")

    assert rejected.status_code == 200, rejected.text
    assert ask(signed_out, "/api/memory", path=mine)["status"] == "active"


def test_several_challenges_against_one_memory_are_shown_together_and_accepting_one_closes_the_others(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-four", 1104)
    mine = promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    ash = Session(console.server, add(signed_out, "emp-3", "Ash Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    first = a_supersede_challenge(dana, remember(dana, "Use npm, not pnpm", "We use npm for every package."))
    second = a_supersede_challenge(ash, remember(ash, "Use yarn, not pnpm", "We use yarn for every package."))

    both = challenges(signed_out)["waiting"]
    left = decide(signed_out, first, "accept").json()["waiting"]

    assert sorted(one["challenge_id"] for one in both) == sorted([first, second])
    assert {one["target"]["path"] for one in both} == {mine}
    assert left == []
    assert "was accepted instead" in str(ash.prompt("what is happening"))


def test_a_member_sees_the_challenges_they_raised_and_how_each_ended(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-five", 1105)
    promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))
    dana_console = a_member(console, signed_out, "emp-2", "dana-disputes-five", 1106)
    dana = Session(console.server, signed_out.post("/api/members/emp-2/token").json()["personal_token"]).in_project(
        project, "billing-api"
    )
    challenge_id = a_supersede_challenge(dana, remember(dana, "Use npm, not pnpm", "We use npm for every package."))

    open_now = challenges(dana_console)["raised"]
    decide(signed_out, challenge_id, "reject")
    after = challenges(dana_console)["raised"]

    assert [(one["challenge_id"], one["state"]) for one in open_now] == [(challenge_id, "open")]
    assert [(one["challenge_id"], one["state"]) for one in after] == [(challenge_id, "rejected")]
    assert after[0]["decided_by"] == "E1001"
    assert challenges(dana_console)["waiting"] == []
    dana_console.close()


def test_anyone_can_decide_once_the_fallback_has_passed(console: Console, signed_out: ConsoleClient) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-six", 1107)
    promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))
    ash_console = a_member(console, signed_out, "emp-3", "ash-disputes-six", 1108)
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    a_supersede_challenge(dana, remember(dana, "Use npm, not pnpm", "We use npm for every package."))

    before = challenges(ash_console)["waiting"]
    console.clock.advance(days=4)
    ash_console.close()
    later = console.client()  # the clock has moved past the session's idle limit too, so Ash signs in again
    console.github.as_(1108, "ash-disputes-six")
    later.sign_in()
    after = challenges(later)["waiting"]

    assert before == []
    assert len(after) == 1
    assert after[0]["yours"] is False
    later.close()


def test_a_member_retires_their_own_memory_from_the_console(console: Console, signed_out: ConsoleClient) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-seven", 1109)
    mine = promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))

    retired = signed_out.post_json("/api/memory/retire", {"path": mine})

    assert retired.status_code == 200, retired.text
    assert retired.json() == {"status": "retired", "path": mine, "challenge_id": None}
    assert ask(signed_out, "/api/memory", path=mine)["status"] == "retired"


def test_retiring_another_members_memory_raises_a_challenge_for_its_author(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-eight", 1110)
    theirs = promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))
    dana_console = a_member(console, signed_out, "emp-2", "dana-disputes-eight", 1111)

    asked = dana_console.post_json("/api/memory/retire", {"path": theirs})

    assert asked.status_code == 200, asked.text
    assert asked.json()["status"] == "challenge_raised"
    assert asked.json()["challenge_id"] is not None
    assert ask(signed_out, "/api/memory", path=theirs)["status"] == "active"
    waiting = challenges(signed_out)["waiting"]
    assert [(one["kind"], one["raised_by"], one["challenger"]) for one in waiting] == [("retire", "emp-2", None)]
    dana_console.close()


def test_a_member_who_may_not_decide_yet_is_refused(console: Console, signed_out: ConsoleClient) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-nine", 1112)
    promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))
    ash_console = a_member(console, signed_out, "emp-3", "ash-disputes-nine", 1113)
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    challenge_id = a_supersede_challenge(dana, remember(dana, "Use npm, not pnpm", "We use npm for every package."))

    refused = decide(ash_console, challenge_id, "accept")

    assert refused.status_code == 403
    assert "the author of the challenged memory" in refused.json()["message"]
    ash_console.close()


def test_a_decision_from_the_console_is_in_the_audit_log(console: Console, signed_out: ConsoleClient) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-ten", 1114)
    promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    challenge_id = a_supersede_challenge(dana, remember(dana, "Use npm, not pnpm", "We use npm for every package."))

    decide(signed_out, challenge_id, "accept")

    log = signed_out.get(f"/api/audit?project={project}&kind=challenge_decided").json()["events"]
    assert [event["actor"] for event in log] == ["E1001"]
    assert log[0]["detail"]["decision"] == "accepted"
    assert log[0]["detail"]["challenge_id"] == challenge_id


def test_a_challenged_memory_says_whether_this_member_is_the_one_to_decide(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-decider", 1130)
    mine = promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))
    ash = a_member(console, signed_out, "emp-3", "ash-disputes-decider", 1131)
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    a_supersede_challenge(dana, remember(dana, "Use npm, not pnpm", "We use npm for every package."))

    for_the_author = ask(signed_out, "/api/memory", path=mine)["open_challenges"]
    for_a_bystander = ask(ash, "/api/memory", path=mine)["open_challenges"]

    assert [one["may_decide"] for one in for_the_author] == [True]
    assert [one["may_decide"] for one in for_a_bystander] == [False]
    ash.close()
