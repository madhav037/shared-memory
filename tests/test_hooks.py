"""How the hook endpoints answer each coding agent: each family's own format, from each family's payload (ADR-0011)."""

from __future__ import annotations

import json
import socket
import threading
from typing import Any
from urllib.parse import urlsplit

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


HOOK_BODY_LIMIT = 1_000_000


def posted_raw(session: Session, event: str, framing: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
    """Post a hook over a bare socket: send these headers and this much body, then wait for the answer.

    When the body sent is shorter than the headers promise, it never finishes arriving, so an answer at all shows the
    server answered without reading the body whole. The body is sent from another thread, because a server that stops
    reading leaves the sender blocked.
    """
    address = urlsplit(session.server.url)
    assert address.hostname is not None and address.port is not None
    lines = [f"POST /hooks/{event} HTTP/1.1", f"Host: {address.netloc}", "Content-Type: application/json"]
    lines += [f"{name}: {value}" for name, value in {**session.headers(), **framing}.items()]
    connection = socket.create_connection((address.hostname, address.port), timeout=15)

    def send() -> None:
        try:
            connection.sendall(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
        except OSError:
            pass

    threading.Thread(target=send, daemon=True).start()
    try:
        received = b""
        while b"\r\n\r\n" not in received:
            chunk = connection.recv(65536)
            assert chunk, "the server closed the connection without answering"
            received += chunk
        head, _, rest = received.partition(b"\r\n\r\n")
        status = int(head.split(b" ")[1])
        length = next(
            int(line.split(b":")[1]) for line in head.split(b"\r\n") if line.lower().startswith(b"content-length:")
        )
        while len(rest) < length:
            chunk = connection.recv(65536)
            assert chunk, "the server closed the connection mid-answer"
            rest += chunk
        answer: dict[str, Any] = json.loads(rest[:length])
        return status, answer
    finally:
        connection.close()


@pytest.mark.parametrize("event", ["session-start", "prompt-submitted"])
def test_an_anonymous_hook_is_answered_without_its_body_being_read(team: Team, event: str) -> None:
    anonymous = Session(team.server, None)

    answer = posted_raw(anonymous, event, {"Content-Length": str(500_000)}, b'{"prompt": "')

    assert answer == (200, {})


def test_a_hook_with_an_unknown_personal_token_is_answered_without_its_body_being_read(
    team: Team, owner: Session
) -> None:
    unknown = Session(team.server, "smt_nope", owner.project, "billing-api")

    answer = posted_raw(unknown, "prompt-submitted", {"Content-Length": str(500_000)}, b'{"prompt": "')

    assert answer == (200, {})


def test_a_hook_body_declared_over_the_limit_is_refused_without_being_read(owner: Session) -> None:
    answer = posted_raw(owner, "prompt-submitted", {"Content-Length": str(HOOK_BODY_LIMIT + 1)}, b'{"prompt": "')

    assert answer == (200, {})


def test_a_streamed_hook_body_is_refused_once_it_runs_past_the_limit(owner: Session) -> None:
    pieces = [b'{"prompt": "'] + [b"x" * 65536] * (HOOK_BODY_LIMIT // 65536 + 2)
    chunked = b"".join(b"%x\r\n%s\r\n" % (len(piece), piece) for piece in pieces)

    answer = posted_raw(owner, "prompt-submitted", {"Transfer-Encoding": "chunked"}, chunked)

    assert answer == (200, {})


def test_a_hook_body_just_under_the_limit_is_still_answered(owner: Session) -> None:
    promoted(owner, "Money amounts", "All money amounts are stored as integer cents, never floats.")
    prompt = "store the refund amount in the database. " + " " * (HOOK_BODY_LIMIT - 1000)
    body = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}).encode()

    status, answer = posted_raw(owner, "prompt-submitted", {"Content-Length": str(len(body))}, body)

    assert status == 200
    assert "integer cents" in added_context(answer)
