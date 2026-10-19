"""Challenges and retiring from the console: deciding what the team no longer believes."""

from __future__ import annotations

from typing import Any

from tests.support import Console, ConsoleClient, Session, add, ask, signed_in_owner
from tests.test_foundation_keepers import Crew
from tests.test_foundations import INVOICE, SERVICES, SERVICES_TWO, promote, supersede


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


def a_supersede_challenge(challenger: Session, path: str, reasoning: str | None = None) -> int:
    """Offer a memory in place of whatever it is similar to, which challenges that memory's author."""
    similar = challenger.call("promote", path=path, level="project")
    raised = challenger.call(
        "promote",
        path=path,
        level="project",
        reference=similar["reference"],
        resolutions={one["path"]: "supersede" for one in similar["similar"]},
        reasoning=reasoning,
    )
    challenge_id: int = raised["challenge_id"]
    return challenge_id


def challenges(client: ConsoleClient) -> dict[str, Any]:
    return ask(client, "/api/challenges")


def decide(client: ConsoleClient, challenge_id: int, decision: str) -> Any:
    return client.post_json(f"/api/challenges/{challenge_id}/decide", {"decision": decision})


def a_member(console: Console, owner_client: ConsoleClient, member_id: str, github: str, account: int) -> ConsoleClient:
    add(owner_client, member_id, f"Dana {member_id}", github)
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
    assert accepted.json()["decided"] == {
        "challenge_id": challenge_id,
        "decision": "accepted",
        "in_force": superseded["superseded_by"],
    }


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
    assert rejected.json()["decided"] == {"challenge_id": challenge_id, "decision": "rejected", "in_force": mine}


def test_accepting_a_retire_challenge_leaves_no_memory_in_force_in_its_place(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-retired", 1170)
    theirs = promoted(in_project, remember(in_project, "Retry failed charges", "We retry failed charges twice."))
    dana_console = a_member(console, signed_out, "emp-2", "dana-disputes-retired", 1171)
    challenge_id = dana_console.post_json("/api/memory/retire", {"path": theirs}).json()["challenge_id"]

    accepted = decide(signed_out, challenge_id, "accept")

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["decided"] == {"challenge_id": challenge_id, "decision": "accepted", "in_force": None}
    assert ask(signed_out, "/api/memory", path=theirs)["status"] == "retired"
    dana_console.close()


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
    assert after[0]["decides_as"] == "fallback"
    later.close()


def test_a_member_retires_their_own_memory_from_the_console(console: Console, signed_out: ConsoleClient) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-seven", 1109)
    mine = promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))

    retired = signed_out.post_json("/api/memory/retire", {"path": mine})

    assert retired.status_code == 200, retired.text
    assert retired.json() == {"status": "retired", "path": mine, "challenge_id": None, "reason": None}
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


def test_a_console_raised_retire_challenge_carries_no_reasoning(console: Console, signed_out: ConsoleClient) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-disputes-reasoning", 1140)
    theirs = promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))
    dana_console = a_member(console, signed_out, "emp-2", "dana-disputes-reasoning", 1141)

    asked = dana_console.post_json("/api/memory/retire", {"path": theirs})

    assert asked.status_code == 200, asked.text
    assert asked.json()["status"] == "challenge_raised"
    assert [one["reasoning"] for one in challenges(signed_out)["waiting"]] == [None]
    assert [one["reasoning"] for one in challenges(dana_console)["raised"]] == [None]
    dana_console.close()


def a_challenger(
    console: Console, owner_client: ConsoleClient, project: str, github: str, account: int
) -> tuple[ConsoleClient, Session]:
    """A member signed in to the console who also works in Billing from a coding agent, to raise challenges."""
    dana_console = a_member(console, owner_client, "emp-2", github, account)
    token = owner_client.post("/api/members/emp-2/token").json()["personal_token"]
    return dana_console, Session(console.server, token).in_project(project, "billing-api")


def danas_challenge(
    console: Console, owner_client: ConsoleClient, github: str, account: int, reasoning: str | None = None
) -> tuple[ConsoleClient, int, str]:
    """Dana offers npm in place of the owner's pnpm memory in Billing, saying why when given reasoning."""
    owner, project, in_project = a_team(console, owner_client, f"olive-{github}", account)
    promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))
    dana_console, dana = a_challenger(console, owner_client, project, github, account + 1)
    challenge_id = a_supersede_challenge(
        dana, remember(dana, "Use npm, not pnpm", "We use npm for every package."), reasoning=reasoning
    )
    return dana_console, challenge_id, project


def test_a_challenges_reasoning_is_shown_to_whoever_decides_it(console: Console, signed_out: ConsoleClient) -> None:
    dana_console, challenge_id, _ = danas_challenge(
        console, signed_out, "dana-reasoning-waiting", 1150, reasoning="CI only has npm."
    )

    waiting = challenges(signed_out)["waiting"]

    assert [(one["challenge_id"], one["reasoning"]) for one in waiting] == [(challenge_id, "CI only has npm.")]
    dana_console.close()


def test_a_member_sees_their_own_reasoning_on_a_challenge_they_raised(
    console: Console, signed_out: ConsoleClient
) -> None:
    dana_console, challenge_id, _ = danas_challenge(
        console, signed_out, "dana-reasoning-raised", 1152, reasoning="CI only has npm."
    )

    raised = challenges(dana_console)["raised"]

    assert [(one["challenge_id"], one["reasoning"]) for one in raised] == [(challenge_id, "CI only has npm.")]
    dana_console.close()


def test_a_challenge_raised_without_reasoning_has_none(console: Console, signed_out: ConsoleClient) -> None:
    dana_console, _, _ = danas_challenge(console, signed_out, "dana-reasoning-none", 1154)

    assert [one["reasoning"] for one in challenges(signed_out)["waiting"]] == [None]
    assert [one["reasoning"] for one in challenges(dana_console)["raised"]] == [None]
    dana_console.close()


def test_a_challenges_reasoning_survives_being_accepted(console: Console, signed_out: ConsoleClient) -> None:
    dana_console, challenge_id, _ = danas_challenge(
        console, signed_out, "dana-reasoning-accepted", 1156, reasoning="CI only has npm."
    )

    decide(signed_out, challenge_id, "accept")

    raised = challenges(dana_console)["raised"]
    assert [(one["state"], one["reasoning"]) for one in raised] == [("accepted", "CI only has npm.")]
    dana_console.close()


def test_a_challenges_reasoning_survives_being_rejected(console: Console, signed_out: ConsoleClient) -> None:
    dana_console, challenge_id, _ = danas_challenge(
        console, signed_out, "dana-reasoning-rejected", 1158, reasoning="CI only has npm."
    )

    decide(signed_out, challenge_id, "reject")

    raised = challenges(dana_console)["raised"]
    assert [(one["state"], one["reasoning"]) for one in raised] == [("rejected", "CI only has npm.")]
    dana_console.close()


def test_a_challenges_reasoning_survives_being_closed_by_another_challenges_acceptance(
    console: Console, signed_out: ConsoleClient
) -> None:
    dana_console, _, project = danas_challenge(
        console, signed_out, "dana-reasoning-closed", 1160, reasoning="CI only has npm."
    )
    ash = Session(console.server, add(signed_out, "emp-3", "Ash Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    ashs = a_supersede_challenge(
        ash, remember(ash, "Use yarn, not pnpm", "We use yarn for every package."), reasoning="yarn is faster."
    )

    decide(signed_out, ashs, "accept")

    raised = challenges(dana_console)["raised"]
    assert [(one["state"], one["reasoning"]) for one in raised] == [("closed", "CI only has npm.")]
    dana_console.close()


def test_a_retire_challenges_reasoning_survives_being_decided(console: Console, signed_out: ConsoleClient) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-reasoning-retire", 1162)
    theirs = promoted(in_project, remember(in_project, "Retry failed charges", "We retry failed charges twice."))
    dana_console, dana = a_challenger(console, signed_out, project, "dana-reasoning-retire", 1163)
    raised = dana.call("retire", path=theirs, reasoning="It's no longer true.")

    decide(signed_out, raised["challenge_id"], "accept")

    mine = challenges(dana_console)["raised"]
    assert [(one["kind"], one["state"], one["reasoning"]) for one in mine] == [
        ("retire", "accepted", "It's no longer true.")
    ]
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
    assert log[0]["detail"]["decided_as"] == "author"


# Who else may decide: a lead of the challenged memory's project and the team's admins (ADR-0017)


def a_dispute_between_members(
    console: Console, owner_client: ConsoleClient, github: str, account: int, level: str = "project"
) -> tuple[str, str, int, Session]:
    """Billing, where Dana (emp-2) wrote a memory that Ash (emp-3) has challenged; the owner wrote neither.
    Returns the project, the challenged memory, the challenge and Ash's session."""
    owner, project, in_project = a_team(console, owner_client, github, account)
    dana = Session(console.server, add(owner_client, "emp-2", "Dana Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    ash = Session(console.server, add(owner_client, "emp-3", "Ash Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    personal = remember(dana, "Use pnpm, not npm", "We use pnpm for every package.")
    target: str = dana.call("promote", path=personal, level=level)["path"]
    offered = remember(ash, "Use npm, not pnpm", "We use npm for every package.")
    similar = ash.call("promote", path=offered, level=level)
    raised = ash.call(
        "promote",
        path=offered,
        level=level,
        reference=similar["reference"],
        resolutions={one["path"]: "supersede" for one in similar["similar"]},
    )
    return project, target, raised["challenge_id"], ash


def a_lead(console: Console, owner_client: ConsoleClient, project: str, github: str, account: int) -> ConsoleClient:
    """Lee (emp-4), signed in to the console and appointed a lead of the project."""
    lee = a_member(console, owner_client, "emp-4", github, account)
    appointed = owner_client.post_json(f"/api/projects/{project}/leads", {"member_id": "emp-4"})
    assert appointed.status_code == 200, appointed.text
    return lee


def decided_as(client: ConsoleClient, project: str) -> list[tuple[str, str]]:
    """Who decided the project's challenges and in what capacity, as the audit log records it."""
    log = client.get(f"/api/audit?project={project}&kind=challenge_decided").json()["events"]
    return [(event["actor"], event["detail"]["decided_as"]) for event in log]


def test_a_project_lead_is_shown_a_challenge_against_another_members_memory_and_decides_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, target, challenge_id, _ = a_dispute_between_members(console, signed_out, "olive-lead-decides", 7901)
    lee = a_lead(console, signed_out, project, "lee-lead-decides", 7902)

    waiting = challenges(lee)["waiting"]
    accepted = decide(lee, challenge_id, "accept")

    assert [(one["challenge_id"], one["yours"], one["decides_as"]) for one in waiting] == [(challenge_id, False, "lead")]
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["waiting"] == []
    assert ask(lee, "/api/memory", path=target)["status"] == "superseded"
    assert decided_as(signed_out, project) == [("emp-4", "lead")]
    lee.close()


def test_an_admin_is_shown_a_challenge_in_a_project_they_reach_and_decides_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, target, challenge_id, _ = a_dispute_between_members(console, signed_out, "olive-admin-decides", 7903)
    signed_out.post(f"/api/projects/{project}/leads/E1001/remove")

    waiting = challenges(signed_out)["waiting"]
    rejected = decide(signed_out, challenge_id, "reject")

    assert [(one["challenge_id"], one["yours"], one["decides_as"]) for one in waiting] == [(challenge_id, False, "admin")]
    assert rejected.status_code == 200, rejected.text
    assert ask(signed_out, "/api/memory", path=target)["status"] == "active"
    assert decided_as(signed_out, project) == [("E1001", "admin")]


def test_a_challenge_against_team_memory_waits_for_an_admin_and_not_for_a_project_lead(
    console: Console, signed_out: ConsoleClient
) -> None:
    project, target, challenge_id, _ = a_dispute_between_members(
        console, signed_out, "olive-team-memory", 7904, level="team"
    )
    lee = a_lead(console, signed_out, project, "lee-team-memory", 7905)

    for_the_lead = challenges(lee)["waiting"]
    refused = decide(lee, challenge_id, "accept")
    for_the_admin = challenges(signed_out)["waiting"]

    assert for_the_lead == []
    assert refused.status_code == 403
    assert "and the team's admins can decide this challenge" in refused.json()["message"]
    assert [(one["challenge_id"], one["decides_as"]) for one in for_the_admin] == [(challenge_id, "admin")]
    assert [one["decides_as"] for one in ask(lee, "/api/memory", path=target)["open_challenges"]] == [None]
    lee.close()


def test_a_lead_who_raised_the_challenge_is_not_shown_it_and_cant_decide_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-lead-raised", 7906)
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    promoted(dana, remember(dana, "Use pnpm, not npm", "We use pnpm for every package."))
    lee = a_lead(console, signed_out, project, "lee-lead-raised", 7907)
    lees = Session(console.server, signed_out.post("/api/members/emp-4/token").json()["personal_token"]).in_project(
        project, "billing-api"
    )
    challenge_id = a_supersede_challenge(lees, remember(lees, "Use npm, not pnpm", "We use npm for every package."))

    waiting = challenges(lee)["waiting"]
    refused = decide(lee, challenge_id, "accept")
    by_an_admin = decide(signed_out, challenge_id, "accept")

    assert waiting == []
    assert refused.status_code == 403
    assert f"You raised challenge {challenge_id}" in refused.json()["message"]
    assert by_an_admin.status_code == 200, by_an_admin.text
    lee.close()


def test_the_author_reads_in_the_console_who_decided_their_challenge_and_in_what_capacity(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-author-told", 7908)
    dana_console, dana = a_challenger(console, signed_out, project, "dana-author-told", 7909)
    target = promoted(dana, remember(dana, "Use pnpm, not npm", "We use pnpm for every package."))
    ash = Session(console.server, add(signed_out, "emp-3", "Ash Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    challenge_id = a_supersede_challenge(ash, remember(ash, "Use npm, not pnpm", "We use npm for every package."))

    decide(signed_out, challenge_id, "reject")

    told = [one["text"] for one in ask(dana_console, "/api/notices")["notices"]]
    assert told == [
        f"Challenge {challenge_id} by emp-3 against your memory {target} was rejected by E1001, "
        "deciding as a project lead: your memory stands as it is."
    ]
    dana_console.close()


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


def test_a_folder_counts_the_open_challenges_against_each_memory_in_it(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner, project, in_project = a_team(console, signed_out, "olive-counts", 1190)
    mine = promoted(in_project, remember(in_project, "Use pnpm, not npm", "We use pnpm for every package."))
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    ash = Session(console.server, add(signed_out, "emp-3", "Ash Dev")["personal_token"]).in_project(
        project, "billing-api"
    )
    danas = remember(dana, "Use npm, not pnpm", "We use npm for every package.")
    a_supersede_challenge(dana, danas)
    a_supersede_challenge(ash, remember(ash, "Use yarn, not pnpm", "We use yarn for every package."))

    def counted(path: str) -> int:
        folder = path.rsplit("/", 1)[0]
        listed = signed_out.get(f"/api/files?folder={folder}").json()["memories"]
        count: int = next(one["challenged"] for one in listed if one["path"] == path)
        return count

    assert counted(mine) == 2
    assert counted(danas) == 0


def test_a_foundation_challenge_is_marked_with_its_foundation_and_offers_the_memory_to_add(
    console: Console, signed_out: ConsoleClient
) -> None:
    crew = Crew(console, signed_out, 2950)
    raised = promote(crew.rae, SERVICES, reasoning="Billing belongs in architecture.")

    (waiting,) = challenges(signed_out)["waiting"]

    assert waiting["challenge_id"] == raised["challenge_id"]
    assert (waiting["kind"], waiting["foundation"], waiting["foundation_name"]) == ("add", "architecture", "Architecture")
    assert waiting["target"]["title"] == "Architecture"
    assert waiting["target"]["status"] != "gone"
    assert waiting["challenger"]["title"] == SERVICES["title"]
    assert waiting["reasoning"] == "Billing belongs in architecture."
    assert waiting["decides_as"] == "lead"


def test_a_foundation_challenge_to_a_memory_names_both_the_memory_and_its_foundation(
    console: Console, signed_out: ConsoleClient
) -> None:
    crew = Crew(console, signed_out, 2951)
    held = promote(crew.owner, SERVICES)["path"]
    supersede(crew.rae, SERVICES_TWO, held)

    (waiting,) = challenges(signed_out)["waiting"]

    assert (waiting["kind"], waiting["foundation"]) == ("supersede", "architecture")
    assert (waiting["target"]["path"], waiting["target"]["status"]) == (held, "active")


def test_an_ordinary_challenge_has_no_foundation(console: Console, signed_out: ConsoleClient) -> None:
    dana_console, _, _ = danas_challenge(console, signed_out, "dana-no-foundation", 2960)

    (waiting,) = challenges(signed_out)["waiting"]
    (raised,) = challenges(dana_console)["raised"]

    assert (waiting["foundation"], waiting["foundation_name"]) == (None, None)
    assert raised["foundation"] is None
    dana_console.close()


def in_the_console(console: Console, crew: Crew, member_id: str, name: str, github: str, account: int) -> ConsoleClient:
    """A member of the crew, who works from a coding agent, signed in to the console too."""
    crew.client.post_json(f"/api/members/{member_id}/change", {"name": name, "github": github})
    client = console.client()
    console.github.as_(account, github)
    client.sign_in()
    return client


def test_a_keeper_is_shown_only_their_foundations_challenges(console: Console, signed_out: ConsoleClient) -> None:
    crew = Crew(console, signed_out, 2954)
    crew.assign("emp-kit", "architecture")
    mine = promote(crew.rae, SERVICES)["challenge_id"]
    promote(crew.rae, INVOICE, foundation="glossary")
    kit = in_the_console(console, crew, "emp-kit", "Kit Keeper", "kit-keeper-2954", 2955)

    shown = challenges(kit)["waiting"]

    assert [(one["challenge_id"], one["decides_as"]) for one in shown] == [(mine, "keeper")]
    assert [one["foundation"] for one in challenges(signed_out)["waiting"]] == ["architecture", "glossary"]
    kit.close()


def test_a_keeper_accepting_a_foundation_challenge_puts_the_memory_in_the_foundation(
    console: Console, signed_out: ConsoleClient
) -> None:
    crew = Crew(console, signed_out, 2956)
    crew.assign("emp-kit", "architecture")
    raised = promote(crew.rae, SERVICES)
    kit = in_the_console(console, crew, "emp-kit", "Kit Keeper", "kit-keeper-2956", 2957)

    answered = decide(kit, raised["challenge_id"], "accept").json()

    assert answered["waiting"] == []
    assert "/foundations/architecture/" in answered["decided"]["in_force"]
    assert crew.rae.call("read", path=answered["decided"]["in_force"])["foundation"] == "architecture"
    kit.close()


def test_a_foundation_challenge_a_member_raised_says_which_foundation(
    console: Console, signed_out: ConsoleClient
) -> None:
    crew = Crew(console, signed_out, 2958)
    promote(crew.rae, SERVICES)
    rae = in_the_console(console, crew, "emp-rae", "Rae Raiser", "rae-raiser-2958", 2959)

    (raised,) = challenges(rae)["raised"]

    assert (raised["kind"], raised["foundation"], raised["target_title"]) == ("add", "architecture", "Architecture")
    rae.close()
