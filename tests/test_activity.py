"""A session's activity, and the project's other active sessions in the briefing."""

from __future__ import annotations

import dataclasses
import re

from shared_memory.activity import ACTIVITY_LIMIT
from tests.support import (
    Console,
    ConsoleClient,
    RunningServer,
    Session,
    Team,
    add,
    added_context,
    create,
    signed_in_owner,
)
from tests.test_board import card
from tests.test_briefing import promote
from tests.test_briefing_board import briefed, in_order
from tests.test_known_issues import FLAKY_UPLOADS, saved

HEADING = "[active sessions]"
NONE_STATED = "no activity stated"
# What a session is known to run in once a tool call of the tests' own MCP client has named it.
BY_TOOL = "another agent, billing-api"
# A session known only by its hooks has not said which coding agent it runs in.
BY_HOOK = "billing-api"


def line(member: str, activity: str, where: str = BY_TOOL) -> str:
    """One active session as a briefing lists it."""
    return f"- {member} ({where}): {activity}"


def state(session: Session, activity: str) -> None:
    session.call("set_activity", activity=activity, session=session.identifier)


def others_in(briefing: str) -> list[str]:
    """The lines a briefing lists the project's other active sessions with."""
    if HEADING not in briefing:
        return []
    lines = briefing[briefing.index(HEADING) :].splitlines()[1:]
    return lines[: next((at for at, each in enumerate(lines) if not each.startswith("- ")), None)]


def others(session: Session) -> list[str]:
    """The other active sessions this session's briefing lists, checked to be the same by its session-start hook and by
    the briefing tool."""
    listed = others_in(added_context(session.start()))
    assert others_in(session.call("briefing", session=session.identifier)) == listed
    return listed


def test_a_session_states_its_activity_and_a_second_call_replaces_it(owner: Session, dana: Session) -> None:
    dana.start()

    state(dana, "Retrying failed webhooks")
    first = others(owner)
    state(dana, "Splitting the invoice module")

    assert first == [line("Dana Dev", "Retrying failed webhooks")]
    assert others(owner) == [line("Dana Dev", "Splitting the invoice module")]


def test_stating_an_activity_starts_a_session_the_server_did_not_know(owner: Session, dana: Session) -> None:
    state(dana, "Retrying failed webhooks")

    assert others(owner) == [line("Dana Dev", "Retrying failed webhooks")]


def test_an_activity_over_the_cap_of_more_than_one_line_or_empty_is_refused(owner: Session, dana: Session) -> None:
    state(dana, "x" * ACTIVITY_LIMIT)

    too_long = dana.refusal("set_activity", activity="x" * (ACTIVITY_LIMIT + 1), session=dana.identifier)
    two_lines = dana.refusal("set_activity", activity="Retrying webhooks\nand invoices", session=dana.identifier)
    empty = dana.refusal("set_activity", activity="  ", session=dana.identifier)

    assert str(ACTIVITY_LIMIT) in too_long
    assert "one line" in two_lines
    assert "what this session is working on" in empty
    assert others(owner) == [line("Dana Dev", "x" * ACTIVITY_LIMIT)], "a refused activity replaces nothing"


def test_an_activity_holding_a_secret_is_refused(dana: Session) -> None:
    refusal = dana.refusal(
        "set_activity", activity="Rotating AKIAIOSFODNN7EXAMPLE out of the deploy", session=dana.identifier
    )

    assert "secret" in refusal


def test_a_session_that_stated_no_activity_shows_its_members_most_recently_claimed_card_in_doing(
    team: Team, owner: Session, dana: Session
) -> None:
    card(owner, "Retry failed webhooks")
    card(owner, "Split the invoice module")
    card(owner, "Upgrade the queue client")
    dana.call("claim_card", number=2)
    team.server.clock.advance(minutes=1)
    dana.call("claim_card", number=1)
    team.server.clock.advance(minutes=1)
    dana.call("claim_card", number=3)
    dana.call("update_card", number=3, column="blocked", blocked_reason="Waiting on the provider's sandbox.")
    dana.start()
    dana.as_session("second-session").start()

    listed = others(owner)

    assert listed == [line("Dana Dev", "Retry failed webhooks", BY_HOOK)] * 2, "a member's two sessions both show it"


def test_a_stated_activity_wins_over_the_card(owner: Session, dana: Session) -> None:
    card(owner, "Retry failed webhooks")
    dana.call("claim_card", number=1)
    dana.start()

    state(dana, "Reading the provider's retry headers")

    assert others(owner) == [line("Dana Dev", "Reading the provider's retry headers")]


def test_a_session_with_no_activity_and_no_card_in_doing_is_listed_as_having_stated_none(
    owner: Session, dana: Session
) -> None:
    card(owner, "Retry failed webhooks")
    owner.call("claim_card", number=1)
    dana.start()

    assert others(owner) == [line("Dana Dev", NONE_STATED, BY_HOOK)]


def test_another_sessions_briefing_names_its_member_coding_agent_repository_and_activity(
    owner: Session, dana: Session
) -> None:
    state(dana.as_agent("codex-mcp-client"), "Retrying failed webhooks")
    state(owner, "Splitting the invoice module")

    assert others(owner) == [line("Dana Dev", "Retrying failed webhooks", "Codex, billing-api")]
    assert others(dana.as_agent("codex-mcp-client")) == [line("Olive Owner", "Splitting the invoice module")]


def test_a_members_own_other_session_is_listed_and_the_asking_session_is_not(owner: Session) -> None:
    second = owner.as_session("second-session")
    state(owner, "Splitting the invoice module")
    state(second, "Retrying failed webhooks")

    assert others(owner) == [line("Olive Owner", "Retrying failed webhooks")]
    assert others(second) == [line("Olive Owner", "Splitting the invoice module")]


def test_a_session_alone_in_its_project_is_told_of_no_others(owner: Session) -> None:
    state(owner, "Splitting the invoice module")

    assert HEADING not in added_context(owner.start())
    assert "no other session is active" in owner.call("briefing", session=owner.identifier)


def test_a_session_that_ended_is_not_listed_and_its_activity_is_gone_when_it_comes_back(
    owner: Session, dana: Session
) -> None:
    state(dana, "Retrying failed webhooks")

    dana.end()
    while_ended = others(owner)
    dana.start()

    assert while_ended == []
    assert others(owner) == [line("Dana Dev", NONE_STATED)]


def test_a_session_gone_idle_is_not_listed_and_its_activity_is_gone_when_it_comes_back(
    team: Team, owner: Session, dana: Session
) -> None:
    state(dana, "Retrying failed webhooks")

    team.server.clock.advance(minutes=30)
    while_idle = others(owner)
    dana.prompt("write a haiku about cats")

    assert while_idle == []
    assert others(owner) == [line("Dana Dev", NONE_STATED)]


def test_active_sessions_come_last_in_the_briefing(owner: Session, dana: Session) -> None:
    owner.call("pin", path=promote(owner, "Use pnpm, not npm", "We use pnpm for every package."))
    card(owner, "Split the invoice module")
    owner.call("claim_card", number=1)
    saved(owner, FLAKY_UPLOADS)
    alone = briefed(owner)

    state(dana, "Retrying failed webhooks")
    briefing = briefed(owner)

    assert in_order(
        briefing,
        "Use pnpm, not npm",
        'card 1 "Split the invoice module" (Doing)',
        "- Large uploads time out behind the proxy",
        HEADING,
        line("Dana Dev", "Retrying failed webhooks"),
        "</shared-memory-briefing>",
    )
    before, _, after = briefing.partition(f"\n\n{HEADING}")
    assert before + after[after.index("\n</shared-memory-briefing>") :] == alone, "what was there is unchanged"


def test_past_the_cap_the_sessions_that_do_not_fit_are_counted(owner: Session, dana: Session) -> None:
    long_body = " ".join(["Billing charges are retried with exponential backoff."] * 80)
    owner.call("pin", path=promote(owner, "Retry policy", long_body))
    for number in range(1, 4):
        card(owner, f"Retry failed webhooks from the payment provider, batch {number}")
        owner.call("claim_card", number=number)
    alone = briefed(owner)
    for number in range(1, 41):
        state(dana.as_session(f"session-{number}"), f"Retrying failed webhooks from the payment provider, batch {number}")

    briefing = briefed(owner)

    shown = len(others_in(briefing))
    assert len(briefing) // 4 <= 1500
    assert 0 < shown < 40
    assert f"{40 - shown} more active sessions did not fit within the briefing cap." in briefing
    assert briefing.startswith(alone[: alone.index("\n</shared-memory-briefing>")]), "what was there is unchanged"


def test_cards_and_sessions_that_do_not_fit_are_counted_together(owner: Session, dana: Session) -> None:
    long_body = " ".join(["Billing charges are retried with exponential backoff."] * 80)
    owner.call("pin", path=promote(owner, "Retry policy", long_body))
    for number in range(1, 21):
        card(owner, f"Retry failed webhooks from the payment provider, batch {number}")
        owner.call("claim_card", number=number)
    state(dana, "Retrying failed webhooks")
    state(dana.as_session("second-session"), "Splitting the invoice module")

    briefing = briefed(owner)

    shown = sum(f'card {number} "' in briefing for number in range(1, 21))
    assert len(briefing) // 4 <= 1500
    assert 0 < shown < 20
    assert HEADING not in briefing
    assert f"{20 - shown} more of your cards and 2 more active sessions did not fit" in briefing
    assert "the board tool lists your cards" in briefing


def test_a_restricted_projects_sessions_appear_only_in_briefings_of_sessions_in_that_project(
    console: Console, signed_out: ConsoleClient
) -> None:
    owner = signed_in_owner(console, signed_out, "olive-activity", 2221)
    billing = create(signed_out, "Billing")["project_id"]
    checkout = create(signed_out, "Checkout")["project_id"]
    dana = Session(console.server, add(signed_out, "emp-2", "Dana Dev")["personal_token"])
    cole = Session(console.server, add(signed_out, "emp-3", "Cole Coder")["personal_token"])
    restricting = signed_out.post_json(f"/api/projects/{billing}/restrict", {"restricted": True})
    assert restricting.status_code == 200, restricting.text
    allowing = signed_out.post_json(f"/api/projects/{billing}/access", {"member_id": "emp-2"})
    assert allowing.status_code == 200, allowing.text
    state(dana.in_project(billing), "Retrying failed webhooks")
    state(cole.in_project(checkout), "Moving the cart to the new API")
    in_app = "another agent, app"

    assert others(owner.in_project(billing)) == [line("Dana Dev", "Retrying failed webhooks", in_app)]
    assert others(owner.in_project(checkout)) == [line("Cole Coder", "Moving the cart to the new API", in_app)]
    assert others(dana.in_project(checkout))[0] == line("Cole Coder", "Moving the cart to the new API", in_app)
    assert HEADING not in added_context(cole.in_project(billing).start()), "a member the project is closed to"


def test_the_briefing_tool_shows_the_list_the_session_start_hook_shows(owner: Session, dana: Session) -> None:
    owner.call("pin", path=promote(owner, "Use pnpm, not npm", "We use pnpm for every package."))
    state(dana, "Retrying failed webhooks")

    started = added_context(owner.start())

    assert others_in(started) == [line("Dana Dev", "Retrying failed webhooks")]
    assert owner.call("briefing", session=owner.identifier) == started


def test_the_briefing_prompt_starts_no_session_beside_the_one_the_hooks_started(owner: Session, dana: Session) -> None:
    """A prompt takes no arguments, so it cannot say which session asked: an agent with hooks keeps its one session."""
    owner.call("pin", path=promote(owner, "Use pnpm, not npm", "We use pnpm for every package."))
    state(dana, "Retrying failed webhooks")
    owner.start()

    prompted = owner.run_prompt("briefing")

    assert sorted(known.identifier for known in owner.active_sessions() if known.member_id == "owner-1") == [
        "test-session"
    ]
    assert "Use pnpm, not npm" in prompted
    assert re.findall(r"identifier in Shared Memory is `([^`]+)`", prompted) == [], "it hands out no second identifier"
    assert HEADING not in prompted, "its own session would be listed among the others"
    assert "Olive Owner" not in prompted
    assert "starts no session" in prompted and "`session`" in prompted


def test_an_activity_stated_through_one_worker_is_listed_by_another(
    owner: Session, dana: Session, second_server: RunningServer
) -> None:
    state(dana, "Retrying failed webhooks")

    assert others(dataclasses.replace(owner, server=second_server)) == [line("Dana Dev", "Retrying failed webhooks")]
