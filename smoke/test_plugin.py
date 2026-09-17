"""The plugin's wiring in real Claude Code, re-checking what prototype #2 found."""

from __future__ import annotations

from pathlib import Path

from smoke.conftest import SmokeServer
from smoke.support import REPOSITORY, ask, member
from tests.support import Session, Team


def test_the_hooks_and_the_mcp_connection_carry_the_members_identity(
    server: SmokeServer, team: Team, tmp_path: Path
) -> None:
    project = team.owner().call("create_project", name="Wiring")["project_id"]
    dana = member(team, project, "emp-2", "Dana Dev")
    before = len(server.log.requests)

    run = ask(dana, tmp_path, "Reply with just the word OK.")

    requests = server.log.requests[before:]
    assert {"/hooks/session-start", "/hooks/prompt-submitted", "/mcp"} <= {request.path for request in requests}
    for request in requests:
        assert request.headers.get("authorization") == f"Bearer {dana.token}", request.path
        assert request.headers.get("x-shared-memory-project") == project, request.path
        assert request.headers.get("x-shared-memory-repository") == REPOSITORY, request.path
    assert [hook.outcome for hook in run.hooks] == ["success", "success"]
    assert "OK" in run.answer


def test_an_unreachable_server_does_not_block_the_prompt(
    server: SmokeServer, unreachable_server_url: str, tmp_path: Path
) -> None:
    session = Session(server, "smt_unused", "no-such-project", REPOSITORY)

    run = ask(session, tmp_path, "Reply with just the word OK.", server_url=unreachable_server_url)

    (session_start,) = run.hooks_for("SessionStart")
    assert "Shared Memory is unavailable" in session_start.output
    (prompt_submitted,) = run.hooks_for("UserPromptSubmit")
    assert prompt_submitted.seconds < 5
    assert "OK" in run.answer


def test_a_slow_server_holds_up_the_prompt_for_only_a_few_seconds(
    server: SmokeServer, slow_server_url: str, tmp_path: Path
) -> None:
    session = Session(server, "smt_unused", "no-such-project", REPOSITORY)

    run = ask(session, tmp_path, "Reply with just the word OK.", server_url=slow_server_url)

    (prompt_submitted,) = run.hooks_for("UserPromptSubmit")
    assert prompt_submitted.seconds < 5
    assert "OK" in run.answer
