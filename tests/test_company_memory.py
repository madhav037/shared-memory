"""The expand step of the team -> company rename (ADR-0031, #625).

The top level of memory is company memory, kept under `company/` in each team's folder. A session may still say
`team` where it says a level, and is answered with `company`; the console's JSON API names the company beside the
team. A server that still holds memory under `team/` moves it to `company/` once, as it sets up, keeping every
memory's history, pins and challenges.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import psycopg

from shared_memory.app import setup
from tests.support import Console, ConsoleClient, Session, Team

GATEWAY = {
    "title": "Gateway timeouts",
    "summary": "The payment gateway times out after 30 seconds.",
    "type": "gotcha",
    "body": "When the payment gateway is slow the client raises ERR_TIMEOUT after 30 seconds.",
}
RETRIES = {
    "title": "Webhook retries",
    "summary": "Webhooks are retried five times.",
    "type": "convention",
    "body": "Every webhook delivery is retried five times with exponential backoff before it is dropped.",
}


def promoted(session: Session, memory: dict[str, str], level: str) -> dict[str, Any]:
    result: dict[str, Any] = session.call("promote", path=session.call("remember", **memory)["path"], level=level)
    assert result["status"] == "promoted", result
    return result


def test_promoting_to_team_or_to_company_lands_in_company_memory(owner: Session) -> None:
    said_team = promoted(owner, GATEWAY, "team")
    said_company = promoted(owner, RETRIES, "company")

    assert said_team["path"].startswith("company/gotchas/")
    assert said_company["path"].startswith("company/conventions/")
    assert owner.call("read", path=said_company["path"])["level"] == "company"


def test_searching_company_or_team_finds_the_same_memories_and_says_company(owner: Session) -> None:
    path = promoted(owner, GATEWAY, "company")["path"]

    by_company = owner.call("search", query="payment gateway timeout", level="company")["results"]
    by_team = owner.call("search", query="payment gateway timeout", level="team")["results"]

    assert [(hit["path"], hit["level"]) for hit in by_company] == [(path, "company")]
    assert by_team == by_company


def test_the_tree_of_company_or_team_is_company_memory(owner: Session) -> None:
    promoted(owner, GATEWAY, "company")

    by_company = owner.call("tree", level="company")
    by_team = owner.call("tree", level="team")

    assert by_team == by_company
    assert [folder["folder"] for folder in by_company["folders"]] == ["company/gotchas"]


def test_a_pinned_company_memory_reaches_every_briefing(team: Team, owner: Session) -> None:
    path = promoted(owner, GATEWAY, "company")["path"]
    other = team.owner().call("create_project", name="Payments")["project_id"]

    owner.call("pin", path=path)

    assert "ERR_TIMEOUT after 30 seconds" in team.owner().in_project(other).call("briefing")


def test_adding_a_member_names_the_company_beside_the_team(team: Team, project: str) -> None:
    added = team.owner().call("add_member", member_id="emp-9", name="Ira Ito")

    assert added["company"] == added["team"] == team.code


def test_the_console_names_the_company_beside_the_team(console: Console, signed_out: ConsoleClient) -> None:
    code, _ = console.a_team("olive-company")
    console.github.as_(6250, "olive-company")
    signed_out.sign_in()

    signed_in_as = signed_out.status()["member"]

    assert signed_in_as["company"] == signed_in_as["team"] == code


def _commit(root: Path, path: str, text: str, message: str) -> None:
    """Commit one file into the memory folder's main as an older server would have, without touching the index the
    server leaves stale: a throwaway index read from main takes the file."""
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8", newline="\n")
    env = {
        **os.environ,
        "GIT_INDEX_FILE": str(root / ".git" / "rename-test-index"),
        "GIT_AUTHOR_NAME": "Olive Owner",
        "GIT_AUTHOR_EMAIL": "E1001@members.invalid",
        "GIT_COMMITTER_NAME": "Shared Memory",
        "GIT_COMMITTER_EMAIL": "server@shared-memory.invalid",
    }
    git = ["git", "-C", str(root)]
    has_main = subprocess.run([*git, "rev-parse", "--verify", "-q", "main"], capture_output=True).returncode == 0  # noqa: S607
    commands = [["read-tree", "main"]] if has_main else [["read-tree", "--empty"]]
    for command in [*commands, ["add", "--", path], ["commit", "-q", "-m", message]]:
        subprocess.run([*git, *command], env=env, check=True, capture_output=True)  # noqa: S603


def _memory(title: str, body: str, **header: str) -> str:
    extra = "".join(f"{key}: {value}\n" for key, value in header.items())
    return f"---\ntitle: {title}\nsummary: {title}.\ntype: convention\nauthor: E1001\n{extra}---\n{body}\n"


def test_team_memory_moves_to_company_memory_with_its_history_pins_and_exceptions(
    console: Console, signed_out: ConsoleClient
) -> None:
    code, token = console.a_team("olive-moving")
    console.github.as_(6251, "olive-moving")
    signed_out.sign_in()
    owner = Session(console.server, token)
    project = owner.call("create_project", name="Billing")["project_id"]
    root = console.server.settings.memory_root
    _commit(root, f"{code}/team/conventions/use-npm.md", _memory("Use npm", "Install with npm."), "Save Use npm")
    _commit(root, f"{code}/team/conventions/use-npm.md", _memory("Use npm", "Install with npm ci."), "Edit Use npm")
    exception = f"projects/{project}/shared/conventions/use-yarn.md"
    _commit(
        root,
        f"{code}/{exception}",
        _memory("Use yarn", "This project installs with yarn.", exception_to="team/conventions/use-npm.md"),
        "Save Use yarn",
    )
    with psycopg.connect(console.server.settings.database_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO pins (team, path, kind, level, project_id, pinned_by, pinned_at)"
            " VALUES (%s, 'team/conventions/use-npm.md', 'memory', 'team', NULL, 'E1001', now())",
            (code,),
        )

    setup(console.server.settings)

    moved = "company/conventions/use-npm.md"
    history = signed_out.get(f"/api/memory/history?path={moved}").json()
    assert owner.in_project(project).call("read", path=moved)["body"] == "Install with npm ci."
    assert [version["message"] for version in history["versions"]][-2:] == ["Edit Use npm", "Save Use npm"]
    assert owner.in_project(project).call("read", path=exception)["exception_to"] == moved
    assert "Install with npm ci." in owner.in_project(project).call("briefing")
    assert not (root / code / "team").exists()
    committed = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", "main", "--", code],  # noqa: S607
        capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    assert f"{code}/{moved}" in committed
    assert not [path for path in committed if path.startswith(f"{code}/team/")]


def test_setting_up_again_moves_nothing(console: Console, signed_out: ConsoleClient) -> None:
    code, token = console.a_team("olive-moved")
    owner = Session(console.server, token)
    owner.call("create_project", name="Billing")
    root = console.server.settings.memory_root
    _commit(root, f"{code}/team/gotchas/slow-ci.md", _memory("Slow CI", "CI takes ten minutes."), "Save Slow CI")
    setup(console.server.settings)
    before = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "main"], capture_output=True, text=True, check=True  # noqa: S607
    ).stdout

    setup(console.server.settings)

    after = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "main"], capture_output=True, text=True, check=True  # noqa: S607
    ).stdout
    assert after == before
    assert (root / code / "company" / "gotchas" / "slow-ci.md").is_file()
