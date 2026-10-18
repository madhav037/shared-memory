"""What a session costs the coding agent's context (#310): what it pays on starting, and what one recall adds to a
prompt. Each is measured over HTTP with the briefing's own estimate of about four characters to a token, and held to
a budget. A budget is raised only on purpose: the test fails above it plus a tenth, so cost cannot creep up unseen.

The briefing measured is a project with nothing pinned. The listing is measured for a coding agent that isn't Claude
Code, which is listed the `guide` tool the Claude Code plugin's skill makes unnecessary. Claude Code's listing is that
one minus `guide`, so it is covered."""

from __future__ import annotations

from shared_memory.briefing import estimate_tokens
from tests.support import Session, Team, added_context, promote_keeping_both

# The budgets, in tokens, each with the figure measured on 2026-10-18 once #303 to #309 had landed.
BUDGETS = {
    "member start": 6100,  # measured: 6052
    "admin start": 6450,  # measured: 6422
    "one recall": 250,  # measured: 218
}
MARGIN = 1.10

NON_CLAUDE_AGENT = "codex-mcp-client"


def within_budget(name: str, measured: int) -> None:
    budget = BUDGETS[name]
    assert measured <= budget * MARGIN, (
        f"{name} now costs about {measured} tokens, over its budget of {budget} plus {MARGIN - 1:.0%}. "
        "Raising the budget must be deliberate: say in the change why the cost is worth it."
    )


def start_cost(session: Session) -> int:
    """The tokens a session pays on starting: its tool listing, the connection instructions and its briefing."""
    agent = session.as_agent(NON_CLAUDE_AGENT)
    instructions, _ = agent.on_connecting()
    briefing = added_context(agent.start())
    assert briefing
    return estimate_tokens(agent.tool_listing()) + estimate_tokens(instructions) + estimate_tokens(briefing)


def test_a_session_starting_as_a_member_stays_within_its_budget(team: Team, dana: Session) -> None:
    measured = start_cost(dana)

    within_budget("member start", measured)


def test_a_session_starting_as_an_admin_stays_within_its_budget(owner: Session) -> None:
    measured = start_cost(owner)

    within_budget("admin start", measured)


def test_one_recall_stays_within_its_budget(owner: Session) -> None:
    for number in range(3):
        promote_keeping_both(
            owner,
            {
                "title": f"Retry rule {number}",
                "summary": f"Failed card charges are retried (rule {number}).",
                "type": "convention",
                "body": f"When a card charge fails we retry it (rule {number}). Detail only in the body {number}.",
            },
        )
    fresh = owner.as_session("a-fresh-session")

    context = added_context(fresh.prompt("why did the charge fail and get retried"))

    assert context.count("[project memory]") == 3 and context.count("Detail only in the body") == 1
    measured = estimate_tokens(context)
    within_budget("one recall", measured)
