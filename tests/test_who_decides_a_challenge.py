"""Who may decide a challenge: its author, a lead of the challenged memory's project, or one of the team's admins
(ADR-0017)."""

from __future__ import annotations

from tests.support import NPM, PNPM, Session, Team, added_context, challenge, member, promote_now


def payments(team: Team, dana: Session) -> tuple[Session, Session, Session, Session]:
    """A project Dana created, so she leads it, with Cole and Eve working in it and the team's owner, an admin who
    doesn't lead it."""
    project = dana.call("create_project", name="Payments")["project_id"]
    cole = member(team, project, "emp-3", "Cole Coder")
    eve = member(team, project, "emp-4", "Eve Engineer")
    return dana.in_project(project, "payments-api"), cole, eve, team.owner().in_project(project, "payments-api")


def news(session: Session) -> str:
    """What the member's next briefing tells them."""
    return added_context(session.start())


def test_a_project_lead_decides_a_challenge_against_another_members_project_memory(team: Team, dana: Session) -> None:
    lead, cole, eve, _ = payments(team, dana)
    target = promote_now(cole, NPM)
    raised = challenge(eve, PNPM, target)

    accepted = lead.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert accepted["status"] == "accepted"
    assert cole.call("read", path=target)["status"] == "superseded"


def test_an_admin_decides_a_challenge_against_project_memory_in_a_project_they_dont_lead(
    team: Team, dana: Session
) -> None:
    _, cole, eve, admin = payments(team, dana)
    target = promote_now(cole, NPM)
    raised = challenge(eve, PNPM, target)

    rejected = admin.call("decide_challenge", challenge_id=raised["challenge_id"], decision="reject")

    assert rejected["status"] == "rejected"
    assert cole.call("read", path=target)["status"] == "active"


def test_a_member_who_neither_leads_nor_administers_still_waits_for_the_fallback(team: Team, dana: Session) -> None:
    _, cole, eve, _ = payments(team, dana)
    frank = member(team, eve.project or "", "emp-5", "Frank Fixer")
    target = promote_now(cole, NPM)
    raised = challenge(eve, PNPM, target)

    refusal = frank.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert "Only emp-3, the author of the challenged memory, a lead of its project and the team's admins" in refusal
    assert "until it has been open for 3 days" in refusal


def test_only_an_admin_decides_a_challenge_against_team_memory_not_a_project_lead(team: Team, dana: Session) -> None:
    lead, cole, eve, admin = payments(team, dana)
    target = promote_now(cole, NPM, level="team")
    raised = challenge(eve, PNPM, target, level="team")

    refusal = lead.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")
    accepted = admin.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert "Only emp-3, the author of the challenged memory, and the team's admins can decide" in refusal
    assert f"Challenge {raised['challenge_id']}" not in news(lead)
    assert accepted["status"] == "accepted"
    assert "deciding as an admin" in news(cole)


def test_a_lead_who_raised_the_challenge_cant_decide_it_but_an_admin_can(team: Team, dana: Session) -> None:
    lead, cole, _, admin = payments(team, dana)
    target = promote_now(cole, NPM)
    raised = challenge(lead, PNPM, target)

    refusal = lead.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")
    briefing = news(lead)
    accepted = admin.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert f"You raised challenge {raised['challenge_id']}" in refusal
    assert "[challenges waiting for your decision]" not in briefing
    assert accepted["status"] == "accepted"


def test_an_admin_who_raised_the_challenge_cant_decide_it_but_a_lead_can(team: Team, dana: Session) -> None:
    lead, cole, _, admin = payments(team, dana)
    target = promote_now(cole, NPM)
    raised = challenge(admin, PNPM, target)

    refusal = admin.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")
    accepted = lead.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert f"You raised challenge {raised['challenge_id']}" in refusal
    assert accepted["status"] == "accepted"


def test_a_lead_who_raised_the_challenge_decides_it_as_anyone_may_after_the_fallback(team: Team, dana: Session) -> None:
    lead, cole, _, _ = payments(team, dana)
    target = promote_now(cole, NPM)
    raised = challenge(lead, PNPM, target)

    team.server.clock.advance(days=3)
    accepted = lead.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert accepted["status"] == "accepted"
    assert "deciding as any member may after 3 days" in news(cole)


def test_a_lead_who_wrote_the_challenged_memory_decides_as_its_author(team: Team, dana: Session) -> None:
    lead, _, eve, _ = payments(team, dana)
    target = promote_now(lead, NPM)
    raised = challenge(eve, PNPM, target)

    briefing = news(lead)
    rejected = lead.call("decide_challenge", challenge_id=raised["challenge_id"], decision="reject")

    assert f"- Challenge {raised['challenge_id']} by emp-4: supersede it with" in briefing
    assert "yours to decide" not in briefing
    assert rejected["status"] == "rejected"
    assert "deciding as" not in news(lead)


def test_the_challenged_memorys_project_is_the_one_whose_leads_decide(team: Team, dana: Session) -> None:
    """Dana leads Payments, where the challenged memory is; Gus leads Ledger, where the challenge was raised from."""
    lead, _, eve, _ = payments(team, dana)
    target = promote_now(eve, NPM)
    added = team.owner().call("add_member", member_id="emp-6", name="Gus Guest")
    gus = Session(team.server, added["personal_token"])
    ledger = gus.call("create_project", name="Ledger")["project_id"]
    frank = member(team, ledger, "emp-5", "Frank Fixer")
    raised = frank.call("retire", path=target, reasoning="npm is gone from every image.")

    refusal = gus.in_project(ledger, "ledger-api").refusal(
        "decide_challenge", challenge_id=raised["challenge_id"], decision="accept"
    )
    accepted = lead.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert "Only emp-4, the author of the challenged memory" in refusal
    assert accepted["status"] == "accepted"
    assert eve.call("read", path=target)["status"] == "retired"


def test_a_lead_and_an_admin_find_the_challenge_in_their_briefing_with_why_it_is_theirs(
    team: Team, dana: Session
) -> None:
    lead, cole, eve, admin = payments(team, dana)
    target = promote_now(cole, NPM)
    raised = challenge(eve, PNPM, target, reasoning="CI rejects a second lockfile.")
    number = raised["challenge_id"]

    assert f"- Challenge {number} by emp-4, yours to decide as a project lead: supersede it with" in news(lead)
    assert f"- Challenge {number} by emp-4, yours to decide as an admin: supersede it with" in news(admin)
    assert f"- Challenge {number} by emp-4: supersede it with" in news(cole)
    assert f"Challenge {number}" not in news(eve)
    assert [(one["may_decide"], one["decides_as"]) for one in lead.call("read", path=target)["open_challenges"]] == [
        (True, "lead")
    ]
    assert [(one["may_decide"], one["decides_as"]) for one in eve.call("read", path=target)["open_challenges"]] == [
        (False, None)
    ]


def test_the_author_is_told_who_decided_and_in_what_capacity_and_the_challenger_as_before(
    team: Team, dana: Session
) -> None:
    lead, cole, eve, _ = payments(team, dana)
    target = promote_now(cole, NPM)
    raised = challenge(eve, PNPM, target)

    lead.call("decide_challenge", challenge_id=raised["challenge_id"], decision="reject")

    told = news(cole)
    assert (
        f"Challenge {raised['challenge_id']} by emp-4 against your memory {target} was rejected by emp-2, "
        "deciding as a project lead: your memory stands as it is."
    ) in told
    assert f"Your challenge {raised['challenge_id']} against {target} was rejected by emp-2." in news(eve)


def test_an_author_who_decides_their_own_challenge_is_told_nothing_more(owner: Session, dana: Session) -> None:
    target = promote_now(owner, NPM)
    raised = challenge(dana, PNPM, target)

    owner.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert "shared memory news" not in news(owner)
