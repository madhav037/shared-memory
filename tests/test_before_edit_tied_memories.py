"""The before-edit hook's optional part (#549): the memories tied to the file a session edits, told once per session
the way recall tells a memory, and never in the way of the edit."""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Iterator
from typing import Any

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.embeddings import FastEmbedEmbedder
from shared_memory.tied import TiedFiles
from tests.support import (
    WORKING_FOLDER,
    RunningServer,
    Session,
    added_context,
    member,
    new_team,
    read_tool,
)
from tests.test_before_edit import ALLOWED, AGENTS_OWN, own_edit, reason_in
from tests.test_locks import FILE, refused
from tests.test_recall import start_from
from tests.test_tied_files import promoted, remember

TIED_FILE = f"billing-api:{FILE}"
BODY = "Webhook retries back off exponentially and stop after five attempts."
# A prompt that is the memory's own words, so recall finds it.
PROMPT = f"Webhook retries back off. {BODY}"


def tied_memory(session: Session, **overrides: object) -> str:
    """A personal memory of this session's member tied to FILE."""
    details: dict[str, object] = {
        "title": "Webhook retries back off",
        "summary": "Webhook retries back off.",
        "body": BODY,
        "tied_files": [TIED_FILE],
    }
    return remember(session, **{**details, **overrides})


def context_in(answer: dict[str, Any], format: str | None = None) -> str:
    """What an allowed edit's answer adds to the session, in Claude Code's shape or in Cline's."""
    if format == "cline":
        assert answer["cancel"] is False
        return str(answer.get("contextModification", ""))
    assert "permissionDecision" not in answer.get("hookSpecificOutput", {}), "an allowed edit is never a deny"
    return added_context(answer)


# Given on the first edit


@pytest.mark.parametrize("agent", ["Claude Code", "Codex", "Cline"])
def test_before_edit_adds_a_tied_memory_on_the_first_edit_of_its_file(dana: Session, agent: str) -> None:
    path = tied_memory(dana)

    answer = dana.edit(FILE) if agent == "Claude Code" else own_edit(dana, agent)

    format = AGENTS_OWN[agent][1] if agent in AGENTS_OWN else None
    if format == "cline":
        assert list(answer) == ["cancel", "contextModification"]
    else:
        assert list(answer) == ["hookSpecificOutput"]
        assert answer["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    context = context_in(answer, format)
    assert "<shared-memory-recall>" in context
    assert "information, not instructions" in context, "recall's framing"
    assert "[your personal memory, tied to billing-api:src/webhooks/retry.py] Webhook retries back off" in context
    assert path in context
    assert BODY in context
    assert "<memory-" in context and "</memory-" in context, "inside recall's fence"


def test_before_edit_does_not_repeat_a_tied_memory_on_the_next_edit_of_the_same_file(dana: Session) -> None:
    path = tied_memory(dana)
    assert path in context_in(dana.edit(FILE))

    assert dana.edit(FILE) == ALLOWED


def test_before_edit_gives_a_tied_memory_again_after_it_changes(dana: Session) -> None:
    path = tied_memory(dana)
    dana.edit(FILE)

    dana.call("edit_memory", path=path, body=f"{BODY} The fifth attempt waits an hour.")

    context = context_in(dana.edit(FILE))
    assert path in context
    assert "The fifth attempt waits an hour." in context
    assert dana.edit(FILE) == ALLOWED, "and then not again"


# Told once across recall and the before-edit hook


def test_before_edit_leaves_out_a_tied_memory_recall_already_gave_this_session(dana: Session) -> None:
    path = tied_memory(dana)
    assert path in added_context(dana.prompt(PROMPT)), "recall gave it"

    assert dana.edit(FILE) == ALLOWED
    dana.end()
    assert path in context_in(dana.as_session("second-session").edit(FILE)), "another session is still given it"


def test_recall_leaves_out_a_memory_before_edit_already_gave_this_session(dana: Session) -> None:
    path = tied_memory(dana)
    assert path in context_in(dana.edit(FILE))

    assert path not in added_context(dana.prompt(PROMPT))
    assert path in added_context(dana.as_session("second-session").prompt(PROMPT)), "recall finds it otherwise"


def test_after_compaction_a_tied_memory_is_given_again(dana: Session) -> None:
    path = tied_memory(dana)
    dana.edit(FILE)

    start_from(dana, "compact")

    assert path in context_in(dana.edit(FILE))


# Within reach


def test_before_edit_never_gives_another_members_personal_memory(owner: Session, dana: Session) -> None:
    owners = tied_memory(owner, tied_files=["billing-api:src/webhooks/**"])
    assert owners in context_in(owner.edit("src/webhooks/backoff.py")), "its author is given it"

    assert dana.edit(FILE) == ALLOWED


def test_before_edit_gives_project_memory_tied_to_the_file(owner: Session, dana: Session) -> None:
    accepted = promoted(owner, title="Webhook retries back off", body=BODY, tied_files=[TIED_FILE])

    context = context_in(dana.edit(FILE))

    assert f"[project memory, tied to {TIED_FILE}] Webhook retries back off ({accepted})" in context


def test_before_edit_marks_a_tied_memory_in_doubt(owner: Session, dana: Session) -> None:
    doubted = promoted(owner, title="Webhook retries back off", body=BODY, tied_files=[TIED_FILE])
    dana.call("challenge", path=doubted, reason="misled")

    context = context_in(dana.edit(FILE))

    assert doubted in context
    assert "In doubt: 1 says it misled them" in context


# Never in the way of the edit


def test_a_tied_memory_never_blocks_an_edit(dana: Session, cole: Session) -> None:
    path = tied_memory(dana)

    answer = dana.edit(FILE)

    assert path in context_in(answer)
    assert "permissionDecision" not in answer["hookSpecificOutput"]
    assert "Dana Dev (emp-2)" in refused(cole), "the edit went ahead and took the lock"


def test_a_blocked_edit_carries_only_the_lock_reason(dana: Session, cole: Session) -> None:
    coles = tied_memory(cole)
    assert dana.edit(FILE) == ALLOWED, "Cole's personal memory is not Dana's to be given"

    answer = cole.edit(FILE)

    reason = reason_in(answer)
    assert "Dana Dev (emp-2)" in reason
    assert coles not in reason and BODY not in reason and "<memory-" not in reason
    assert list(answer["hookSpecificOutput"]) == ["hookEventName", "permissionDecision", "permissionDecisionReason"]
    dana.end()
    assert coles in context_in(cole.edit(FILE)), "left untold, so given on the next edit that goes ahead"


def test_a_tool_that_edits_nothing_gets_no_tied_memories(dana: Session) -> None:
    path = tied_memory(dana)
    cline_read = {
        "taskId": dana.identifier,
        "hookName": "PreToolUse",
        "workspaceRoots": [WORKING_FOLDER],
        "preToolUse": {"tool": "read_file", "parameters": {"path": FILE}},
    }

    assert dana.use(read_tool(f"{WORKING_FOLDER}/{FILE}")) == ALLOWED
    assert dana.hook_payload("before-edit", cline_read, "cline") == ALLOWED
    assert path in context_in(dana.edit(FILE)), "still untold"


@pytest.mark.parametrize("agent", ["Gemini CLI", "Devin Desktop", "Copilot CLI", "Cursor"])
def test_an_agent_whose_hook_before_a_tool_takes_no_added_context_is_given_no_tied_memories(
    dana: Session, agent: str
) -> None:
    tied_memory(dana)

    assert own_edit(dana, agent) == ALLOWED


# The recall budget


@pytest.fixture
def slow_server(server: RunningServer, tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    settings = dataclasses.replace(
        server.settings, memory_root=tmp_path_factory.mktemp("slow-tied-memory"), recall_budget_seconds=0.5
    )
    app = build_app(settings, clock=server.clock, embedder=FastEmbedEmbedder(settings.model_cache))
    with start_blocking_portal() as portal:
        running = RunningServer(app, settings, server.clock, portal)
        try:
            yield running
        finally:
            running.stop()


def test_before_edit_drops_tied_memories_past_the_recall_budget(
    slow_server: RunningServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    team = new_team(slow_server)
    project = team.owner().call("create_project", name="Billing")["project_id"]
    dana = member(team, project, "emp-2", "Dana Dev")
    cole = member(team, project, "emp-3", "Cole Coder")
    tied_memory(dana)
    looked_up = TiedFiles.tied_to

    def slowly(self: TiedFiles, *args: Any, **kwargs: Any) -> Any:
        time.sleep(3)
        return looked_up(self, *args, **kwargs)

    monkeypatch.setattr(TiedFiles, "tied_to", slowly)

    started = time.monotonic()
    answer = dana.edit(FILE)

    assert answer == ALLOWED
    assert time.monotonic() - started < 2.5
    assert "Dana Dev (emp-2)" in reason_in(cole.edit(FILE)), "the lock check is still answered"
