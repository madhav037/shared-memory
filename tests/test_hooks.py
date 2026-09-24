"""How the hook endpoints answer each coding agent: each family's own format, from each family's payload (ADR-0011)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.support import Session, Team, added_context

# Where each agent family reads the context out of an answer, and so the shape the server owes it. None is the format
# an agent that asks for none gets: Claude Code's, which is what these endpoints have always answered.
CONTEXT_FIELDS: dict[str | None, tuple[str, ...]] = {
    None: ("hookSpecificOutput", "additionalContext"),
    "copilot-cli": ("additionalContext",),
    "cursor": ("additional_context",),
    "cline": ("contextModification",),
}


def context_in(output: dict[str, Any], format: str | None) -> str:
    """What an agent of this family would take into its session from this answer."""
    found: Any = output
    for field in CONTEXT_FIELDS[format]:
        found = found[field]
    text: str = found
    return text


def promoted(session: Session, title: str, body: str) -> str:
    """A project memory of this session's project, which recall can reach."""
    personal = session.call("remember", title=title, summary=f"{title}.", type="convention", body=body)["path"]
    result = session.call("promote", path=personal, level="project")
    if result["status"] == "similar_memories":
        keep = {similar["path"]: "keep_both" for similar in result["similar"]}
        result = session.call("promote", path=personal, level="project", reference=result["reference"], resolutions=keep)
    path: str = result["path"]
    return path


def pinned(session: Session, title: str, body: str) -> str:
    """A project memory pinned into this session's briefing."""
    path = promoted(session, title, body)
    session.call("pin", path=path)
    return path


def test_cursor_is_briefed_in_its_own_format(owner: Session) -> None:
    pinned(owner, "Use pnpm, not npm", "We use pnpm for every package.")

    output = owner.start(format="cursor")

    assert list(output) == ["additional_context"]
    assert "Use pnpm, not npm" in output["additional_context"]


def test_copilot_cli_recalls_memory_at_the_top_level(owner: Session) -> None:
    promoted(owner, "Money amounts", "All money amounts are stored as integer cents, never floats.")

    output = owner.prompt("store the refund amount in the database", format="copilot-cli")

    assert list(output) == ["additionalContext"]
    assert "integer cents" in output["additionalContext"]


def test_cline_is_briefed_without_its_task_being_cancelled(owner: Session) -> None:
    pinned(owner, "Use pnpm, not npm", "We use pnpm for every package.")

    output = owner.start(format="cline")

    assert output["cancel"] is False
    assert "Use pnpm, not npm" in output["contextModification"]


def test_the_prompt_is_read_from_clines_nested_payload(owner: Session) -> None:
    promoted(owner, "Money amounts", "All money amounts are stored as integer cents, never floats.")

    output = owner.hook_payload(
        "prompt-submitted",
        {
            "clineVersion": "4.1.20",
            "hookName": "UserPromptSubmit",
            "taskId": "task-1",
            "workspaceRoots": ["/work/app"],
            "userPromptSubmit": {"prompt": "store the refund amount in the database", "attachments": []},
        },
        format="cline",
    )

    assert "integer cents" in output["contextModification"]


def test_the_event_name_an_agent_sent_is_echoed_back_to_it(owner: Session) -> None:
    pinned(owner, "Use pnpm, not npm", "We use pnpm for every package.")

    output = owner.hook_payload("session-start", {"hook_event_name": "sessionStart", "source": "startup"})

    assert output["hookSpecificOutput"]["hookEventName"] == "sessionStart"


def test_an_agent_that_names_no_event_is_answered_with_the_endpoints_own(owner: Session) -> None:
    pinned(owner, "Use pnpm, not npm", "We use pnpm for every package.")

    output = owner.hook_payload("session-start", {"source": "startup"})

    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_a_prompt_sent_as_content_parts_is_read(owner: Session) -> None:
    promoted(owner, "Money amounts", "All money amounts are stored as integer cents, never floats.")

    output = owner.hook_payload(
        "prompt-submitted",
        {
            "hook_event_name": "UserPromptSubmit",
            "prompt": [{"type": "text", "text": "store the refund amount in the database"}],
        },
    )

    assert "integer cents" in added_context(output)


def test_a_format_this_server_does_not_know_is_answered_as_claude_code_is(owner: Session) -> None:
    pinned(owner, "Use pnpm, not npm", "We use pnpm for every package.")

    output = owner.start(format="nonesuch")

    assert "Use pnpm, not npm" in added_context(output)


def test_a_refused_session_is_told_nothing_in_a_format_with_nowhere_to_say_it(team: Team, owner: Session) -> None:
    revoked = Session(team.server, "smt_nope", owner.project, "billing-api")

    assert "not recognised" in revoked.start()["systemMessage"]
    assert revoked.start(format="cursor") == {}
    assert revoked.start(format="copilot-cli") == {}


def test_a_refused_session_is_never_cancelled_in_clines_format(team: Team, owner: Session) -> None:
    revoked = Session(team.server, "smt_nope", owner.project, "billing-api")

    assert revoked.start(format="cline") == {}
    assert revoked.prompt("store the refund amount", format="cline") == {}


@pytest.mark.parametrize("format", list(CONTEXT_FIELDS))
def test_both_events_are_answered_in_every_familys_own_format(owner: Session, format: str | None) -> None:
    pinned(owner, "Money amounts", "All money amounts are stored as integer cents, never floats.")

    briefed = owner.start(format=format)
    recalled = owner.prompt("store the refund amount in the database", format=format)

    assert "integer cents" in context_in(briefed, format)
    assert "integer cents" in context_in(recalled, format)


def test_a_payload_the_server_cannot_read_still_answers_every_family_emptily(owner: Session) -> None:
    for format in CONTEXT_FIELDS:
        url = f"{owner.server.url}/hooks/prompt-submitted" + (f"?format={format}" if format else "")
        answer = httpx.post(url, content=b"not json", headers=owner.headers())

        assert (answer.status_code, answer.json()) == (200, {}), format
