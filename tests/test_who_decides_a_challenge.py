"""Who may decide a challenge: its author, a lead of the challenged memory's project, or one of the company's admins
(ADR-0017)."""

from __future__ import annotations

from tests.support import (
    NPM,
    PNPM,
    Session,
    Company,
    added_context,
    challenge,
    member,
    promote_keeping_both,
    promote_now,
)


def payments(company: Company, dana: Session) -> tuple[Session, Session, Session, Session]:
    """A project Dana created, so she leads it, with Cole and Eve working in it and the company's owner, an admin who
    doesn't lead it."""
    project = dana.call("create_project", name="Payments")["project_id"]
    cole = member(company, project, "emp-3", "Cole Coder")
    eve = member(company, project, "emp-4", "Eve Engineer")
    return dana.in_project(project, "payments-api"), cole, eve, company.owner().in_project(project, "payments-api")


def news(session: Session) -> str:
    """What the member's next briefing tells them."""
    return added_context(session.start())


def test_a_project_lead_decides_a_challenge_against_another_members_project_memory(
    company: Company, dana: Session
) -> None:
    lead, cole, eve, _ = payments(company, dana)
    target = promote_now(cole, NPM)
    raised = challenge(eve, PNPM, target)

    accepted = lead.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert accepted["status"] == "accepted"
    assert cole.call("read", path=target)["status"] == "superseded"


def test_an_admin_decides_a_challenge_against_project_memory_in_a_project_they_dont_lead(
    company: Company, dana: Session
) -> None:
    _, cole, eve, admin = payments(company, dana)
    target = promote_now(cole, NPM)
    raised = challenge(eve, PNPM, target)

    rejected = admin.call("decide_challenge", challenge_id=raised["challenge_id"], decision="reject")

    assert rejected["status"] == "rejected"
    assert cole.call("read", path=target)["status"] == "active"


def test_a_member_who_neither_leads_nor_administers_still_waits_for_the_fallback(
    company: Company, dana: Session
) -> None:
    _, cole, eve, _ = payments(company, dana)
    frank = member(company, eve.project or "", "emp-5", "Frank Fixer")
    target = promote_now(cole, NPM)
    raised = challenge(eve, PNPM, target)

    refusal = frank.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert "Only emp-3, the author of the challenged memory, a lead of its project and the company's admins" in refusal
    assert "until it has been open for 3 days" in refusal


def test_only_an_admin_decides_a_challenge_against_company_memory_not_a_project_lead(
    company: Company, dana: Session
) -> None:
    lead, cole, eve, admin = payments(company, dana)
    target = promote_now(cole, NPM, level="company")
    raised = challenge(eve, PNPM, target, level="company")

    refusal = lead.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")
    accepted = admin.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert "Only emp-3, the author of the challenged memory, and the company's admins can decide" in refusal
    assert f"Challenge {raised['challenge_id']}" not in news(lead)
    assert accepted["status"] == "accepted"
    assert "deciding as an admin" in news(cole)


def test_a_lead_who_raised_the_challenge_cant_decide_it_but_an_admin_can(company: Company, dana: Session) -> None:
    lead, cole, _, admin = payments(company, dana)
    target = promote_now(cole, NPM)
    raised = challenge(lead, PNPM, target)

    refusal = lead.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")
    briefing = news(lead)
    accepted = admin.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert f"You raised challenge {raised['challenge_id']}" in refusal
    assert "[challenges waiting for your decision]" not in briefing
    assert accepted["status"] == "accepted"


def test_an_admin_who_raised_the_challenge_cant_decide_it_but_a_lead_can(company: Company, dana: Session) -> None:
    lead, cole, _, admin = payments(company, dana)
    target = promote_now(cole, NPM)
    raised = challenge(admin, PNPM, target)

    refusal = admin.refusal("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")
    accepted = lead.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert f"You raised challenge {raised['challenge_id']}" in refusal
    assert accepted["status"] == "accepted"


def test_a_lead_who_raised_the_challenge_decides_it_as_anyone_may_after_the_fallback(
    company: Company, dana: Session
) -> None:
    lead, cole, _, _ = payments(company, dana)
    target = promote_now(cole, NPM)
    raised = challenge(lead, PNPM, target)

    company.server.clock.advance(days=3)
    accepted = lead.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert accepted["status"] == "accepted"
    assert "deciding as any member may after 3 days" in news(cole)


def test_a_lead_who_wrote_the_challenged_memory_decides_as_its_author(company: Company, dana: Session) -> None:
    lead, _, eve, _ = payments(company, dana)
    target = promote_now(lead, NPM)
    raised = challenge(eve, PNPM, target)

    briefing = news(lead)
    rejected = lead.call("decide_challenge", challenge_id=raised["challenge_id"], decision="reject")

    assert f"- Challenge {raised['challenge_id']} by emp-4: supersede it with" in briefing
    assert "yours to decide" not in briefing
    assert rejected["status"] == "rejected"
    assert "deciding as" not in news(lead)


def test_the_challenged_memorys_project_is_the_one_whose_leads_decide(company: Company, dana: Session) -> None:
    """Dana leads Payments, where the challenged memory is; Gus leads Ledger, where the challenge was raised from."""
    lead, _, eve, _ = payments(company, dana)
    target = promote_now(eve, NPM)
    added = company.owner().call("add_member", member_id="emp-6", name="Gus Guest")
    gus = Session(company.server, added["personal_token"])
    ledger = gus.call("create_project", name="Ledger")["project_id"]
    frank = member(company, ledger, "emp-5", "Frank Fixer")
    raised = frank.call("retire", path=target, reasoning="npm is gone from every image.")

    refusal = gus.in_project(ledger, "ledger-api").refusal(
        "decide_challenge", challenge_id=raised["challenge_id"], decision="accept"
    )
    accepted = lead.call("decide_challenge", challenge_id=raised["challenge_id"], decision="accept")

    assert "Only emp-4, the author of the challenged memory" in refusal
    assert accepted["status"] == "accepted"
    assert eve.call("read", path=target)["status"] == "retired"


def test_a_lead_and_an_admin_find_the_challenge_in_their_briefing_with_why_it_is_theirs(
    company: Company, dana: Session
) -> None:
    lead, cole, eve, admin = payments(company, dana)
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
    company: Company, dana: Session
) -> None:
    lead, cole, eve, _ = payments(company, dana)
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


# A foundation challenge (ADR-0019) is decided by a lead of its project and nobody else.

FOUNDATION_HEADING = "[foundation challenges waiting for your decision]"
SERVICES = {
    "title": "Billing runs as three services",
    "summary": "Billing is an API, a ledger worker and a webhook relay.",
    "type": "architecture",
    "body": "Billing is three services: the API takes requests, the ledger worker writes entries, and the relay "
    "delivers webhooks.",
}


def an_add(eve: Session) -> int:
    personal = eve.call("remember", **SERVICES)["path"]
    raised = eve.call("promote", path=personal, level="project")
    assert raised["status"] == "challenge_raised", raised
    return int(raised["challenge_id"])


def test_an_admin_who_doesnt_lead_the_project_cant_decide_a_foundation_challenge_but_its_lead_can(
    company: Company, dana: Session
) -> None:
    lead, _, eve, admin = payments(company, dana)
    challenge_id = an_add(eve)

    refusal = admin.refusal("decide_challenge", challenge_id=challenge_id, decision="accept")
    accepted = lead.call("decide_challenge", challenge_id=challenge_id, decision="accept")

    assert "lead of the project" in refusal
    assert FOUNDATION_HEADING not in news(admin)
    assert accepted["status"] == "accepted"
    assert "/foundations/architecture/" in accepted["path"]


def test_nobody_else_decides_a_foundation_challenge_once_the_fallback_has_passed(
    company: Company, dana: Session
) -> None:
    lead, cole, eve, _ = payments(company, dana)
    challenge_id = an_add(eve)

    company.server.clock.advance(days=4)
    refusal = cole.refusal("decide_challenge", challenge_id=challenge_id, decision="accept")

    assert "lead of the project" in refusal
    assert FOUNDATION_HEADING not in news(cole)
    assert FOUNDATION_HEADING in news(lead)


# A doubt (spec #502) is decided by the same people as any other challenge.

TAX = {
    "title": "Sales tax is fifteen percent",
    "summary": "Invoices add fifteen percent sales tax.",
    "type": "convention",
    "body": "Every invoice adds a flat fifteen percent sales tax on the subtotal.",
}
RETRIES = {
    "title": "Billing retries three times",
    "summary": "Failed charges are retried three times.",
    "type": "convention",
    "body": "The billing service retries a failed card charge three times before giving up.",
}
WEBHOOKS = {
    "title": "Webhooks retry for a day",
    "summary": "A failed webhook is retried for twenty-four hours.",
    "type": "gotcha",
    "body": "The relay retries a failed webhook delivery with backoff for twenty-four hours before giving up.",
}


def doubted(session: Session, path: str) -> int:
    raised = session.call("challenge", path=path, reason="misled", reasoning="It led my session astray.")
    return int(raised["challenge_id"])


def test_the_author_a_lead_of_the_memorys_project_and_an_admin_can_each_decide_a_doubt(
    company: Company, dana: Session
) -> None:
    lead, cole, eve, admin = payments(company, dana)
    paths = [promote_keeping_both(cole, memory) for memory in (TAX, RETRIES, WEBHOOKS)]
    doubts = [doubted(eve, path) for path in paths]
    deciders = (cole, lead, admin)
    capacities = [
        [(one["may_decide"], one["decides_as"]) for one in decider.call("read", path=path)["open_challenges"]]
        for decider, path in zip(deciders, paths, strict=True)
    ]

    decided = [
        decider.call("decide_challenge", challenge_id=challenge_id, decision="reject")
        for decider, challenge_id in zip(deciders, doubts, strict=True)
    ]

    assert capacities == [[(True, "author")], [(True, "lead")], [(True, "admin")]]
    assert [one["status"] for one in decided] == ["rejected", "rejected", "rejected"]
    told = news(cole)
    assert (
        f"Challenge {doubts[1]} by emp-4 against your memory {paths[1]} was rejected by emp-2, deciding as a project lead"
        in told
    )
    assert (
        f"Challenge {doubts[2]} by emp-4 against your memory {paths[2]} was rejected by owner-1, deciding as an admin"
        in told
    )


def test_any_other_member_is_refused_deciding_a_doubt(company: Company, dana: Session) -> None:
    _, cole, eve, _ = payments(company, dana)
    frank = member(company, eve.project or "", "emp-5", "Frank Fixer")
    path = promote_keeping_both(cole, TAX)
    challenge_id = doubted(eve, path)

    refusals = [
        one.refusal("decide_challenge", challenge_id=challenge_id, decision=decision)
        for one in (frank, eve)
        for decision in ("accept", "reject")
    ]

    assert all("Only emp-3, the author of the challenged memory" in refusal for refusal in refusals), refusals
    assert cole.call("read", path=path)["status"] == "active"
    assert [one["challenge_id"] for one in cole.call("read", path=path)["open_challenges"]] == [challenge_id]


def test_a_lead_who_raised_a_doubt_or_joined_it_cant_decide_it_as_lead_but_an_admin_can(
    company: Company, dana: Session
) -> None:
    lead, cole, eve, admin = payments(company, dana)
    raised_path = promote_keeping_both(cole, TAX)
    joined_path = promote_keeping_both(cole, RETRIES)
    raised = doubted(lead, raised_path)
    joined = doubted(eve, joined_path)
    doubted(lead, joined_path)

    refusals = [lead.refusal("decide_challenge", challenge_id=one, decision="reject") for one in (raised, joined)]
    briefing = news(lead)
    decided = [admin.call("decide_challenge", challenge_id=one, decision="reject") for one in (raised, joined)]

    assert f"You raised challenge {raised}" in refusals[0]
    assert f"You raised challenge {joined}" in refusals[1]
    assert "[challenges waiting for your decision]" not in briefing
    assert [one["status"] for one in decided] == ["rejected", "rejected"]


def test_an_admin_who_raised_a_doubt_cant_decide_it_as_admin_but_a_lead_can(company: Company, dana: Session) -> None:
    lead, cole, _, admin = payments(company, dana)
    path = promote_keeping_both(cole, TAX)
    challenge_id = doubted(admin, path)

    refusal = admin.refusal("decide_challenge", challenge_id=challenge_id, decision="accept")
    accepted = lead.call("decide_challenge", challenge_id=challenge_id, decision="accept")

    assert f"You raised challenge {challenge_id}" in refusal
    assert accepted["status"] == "accepted"


def test_an_author_who_doubted_their_own_memory_decides_it_as_its_author(company: Company, dana: Session) -> None:
    _, cole, _, _ = payments(company, dana)
    path = promote_keeping_both(cole, TAX)
    challenge_id = doubted(cole, path)

    capacity = [(one["may_decide"], one["decides_as"]) for one in cole.call("read", path=path)["open_challenges"]]
    accepted = cole.call("decide_challenge", challenge_id=challenge_id, decision="accept")

    assert capacity == [(True, "author")]
    assert accepted["status"] == "accepted"
