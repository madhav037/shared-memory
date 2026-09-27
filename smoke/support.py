"""Helpers for smoke tests: set up members and memory through the server, then ask Claude as a member."""

from __future__ import annotations

from pathlib import Path

from smoke.claude import ClaudeRun, run_claude
from tests.support import Session, Team

REPOSITORY = "smoke-app"


def member(team: Team, project: str, member_id: str, name: str) -> Session:
    added = team.owner().call("add_member", member_id=member_id, name=name)
    return Session(team.server, added["personal_token"], project, REPOSITORY)


def promote(session: Session, title: str, summary: str, body: str, type: str = "convention") -> str:
    """Save a personal memory and promote it into project memory, keeping any similar memories."""
    personal = session.call("remember", title=title, summary=summary, type=type, body=body)["path"]
    result = session.call("promote", path=personal, level="project")
    if result["status"] == "similar_memories":
        keep = {similar["path"]: "keep_both" for similar in result["similar"]}
        result = session.call("promote", path=personal, level="project", reference=result["reference"], resolutions=keep)
    assert result["status"] == "promoted", result
    path: str = result["path"]
    return path


def ask(session: Session, workdir: Path, *prompts: str, server_url: str | None = None) -> ClaudeRun:
    """Run a headless Claude Code session as this member, in a repository connected to the session's project."""
    assert session.token and session.project and session.repository
    return run_claude(
        workdir,
        server_url=server_url or session.server.url,
        token=session.token,
        project=session.project,
        repository=session.repository,
        prompts=list(prompts),
    )
