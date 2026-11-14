"""A hosted server whose license key has lapsed is read-only (#469, ADR-0022): every change to memory is refused with a
plain answer naming the date and that paying restores it, while reading, search, the briefing and the hooks keep
working. A self-hosted server with a lapsed key never turns read-only (#416). Driven through the Session driver over
HTTP."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from anyio.from_thread import start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.embeddings import FastEmbedEmbedder
from tests.license_keys import TEST_PUBLIC_KEYS, a_key
from tests.support import (
    BUG,
    CENTS,
    NPM,
    PNPM,
    POSTGRES,
    REPO_ROOT,
    SERVICES,
    RunningServer,
    Session,
    TestClock,
    added_context,
    challenge,
    fresh_database,
    member,
    new_team,
    promote,
    remember,
    unfenced_in,
)

# The test clock stands at 1 September 2026, so a key whose last day was the day before has lapsed.
LAPSED_ON = date(2026, 8, 31)
RENEWED_UNTIL = date(2026, 10, 1)

STALE_PRICES = {
    "title": "The price cache serves stale prices after a deploy",
    "summary": "Prices stay stale for up to an hour after each deploy.",
    "body": "After a deploy the price cache keeps serving the old prices for up to an hour.\n\n"
    "Workaround: flush the price cache by hand once the deploy finishes.",
}


def hosted_key(expires: date = LAPSED_ON) -> str:
    return a_key(member_cap=1000, issued=date(2025, 9, 1), expires=expires, hosted=True)


def self_hosted_key(expires: date = LAPSED_ON) -> str:
    return a_key(member_cap=1000, issued=date(2025, 9, 1), expires=expires)


@pytest.fixture(scope="module")
def hosted(tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    settings = Settings(
        database_url=fresh_database("shared_memory_read_only"),
        memory_root=tmp_path_factory.mktemp("read-only-memory"),
        model_cache=REPO_ROOT / ".cache" / "fastembed",
        rate_limit_on=False,
    )
    clock = TestClock()
    app = build_app(
        settings, clock=clock, embedder=FastEmbedEmbedder(settings.model_cache), license_keys=TEST_PUBLIC_KEYS
    )
    with start_blocking_portal() as portal:
        running = RunningServer(app, settings, clock, portal)
        try:
            yield running
        finally:
            running.stop()


def under(server: RunningServer, key: str) -> None:
    """Run the server under this license key, as if it were set in its environment ("" for none)."""
    licenses = server.app.state.licenses
    licenses.settings = dataclasses.replace(licenses.settings, license_key=key)
    licenses.clear()


@dataclasses.dataclass
class Team:
    """A team with memory of every kind, made while its server was still licensed."""

    owner: Session
    dana: Session
    project_memory: str
    pinned: str
    personal: str
    challenge_id: int
    known_issue: str
    card: int


def saved_known_issue(session: Session, issue: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = session.call("save_known_issue", **issue)
    if result["status"] == "similar_memories":
        keep_both = {similar["path"]: "keep_both" for similar in result["similar"]}
        result = session.call("save_known_issue", **issue, reference=result["reference"], resolutions=keep_both)
    assert result["status"] == "saved", result
    return result


@pytest.fixture
def team(hosted: RunningServer) -> Iterator[Team]:
    hosted.clock.now = TestClock().now
    under(hosted, "")
    made = new_team(hosted)
    project = made.owner().call("create_project", name="Billing")["project_id"]
    owner = made.owner().in_project(project, "billing-api")
    dana = member(made, project, "emp-2", "Dana Dev")
    project_memory = promote(owner, NPM)["path"]
    raised = challenge(dana, PNPM, project_memory)
    pinned = promote(owner, CENTS)["path"]
    owner.call("pin", path=pinned)
    issue = saved_known_issue(owner, BUG)
    yield Team(
        owner=owner,
        dana=dana,
        project_memory=project_memory,
        pinned=pinned,
        personal=remember(owner, POSTGRES),
        challenge_id=raised["challenge_id"],
        known_issue=issue["path"],
        card=issue["card"],
    )
    under(hosted, "")


def read_only_refusal(refusal: str) -> bool:
    return "read-only" in refusal and LAPSED_ON.isoformat() in refusal and "Paying" in refusal


def test_a_hosted_server_whose_key_has_lapsed_refuses_every_change_to_memory(
    hosted: RunningServer, team: Team
) -> None:
    owner = team.owner
    before = unfenced_in(owner.call("tree"))
    under(hosted, hosted_key())

    changes: dict[str, dict[str, Any]] = {
        "remember": SERVICES,
        "edit_memory": {"path": team.personal, "title": "Postgres and Redis"},
        "delete_memory": {"path": team.personal},
        "promote": {"path": team.personal, "level": "project"},
        "retire": {"path": team.project_memory},
        "add_to_foundation": {"path": team.pinned, "foundation": "decisions"},
        "save_known_issue": STALE_PRICES,
        "decide_challenge": {"challenge_id": team.challenge_id, "decision": "accept"},
        "pin": {"path": team.project_memory},
        "unpin": {"path": team.pinned},
        "create_project": {"name": "Payments"},
        "add_foundation": {"name": "Runbooks"},
        "add_member": {"member_id": "emp-3", "name": "Eve Eng"},
        "add_card": {"title": "Retry failed webhooks"},
    }
    refusals = {tool: owner.refusal(tool, **arguments) for tool, arguments in changes.items()}

    assert {tool: refusal for tool, refusal in refusals.items() if not read_only_refusal(refusal)} == {}
    assert unfenced_in(owner.call("tree")) == before
    assert owner.call("read", path=team.personal)["title"] == POSTGRES["title"]
    assert owner.call("read", path=team.project_memory)["status"] == "active"


def test_a_read_only_server_still_serves_reading_search_and_the_briefing(hosted: RunningServer, team: Team) -> None:
    under(hosted, hosted_key())
    owner = team.owner

    assert owner.call("read", path=team.project_memory)["title"] == NPM["title"]
    assert team.project_memory in [found["path"] for found in owner.call("search", query="npm install")["results"]]
    assert owner.call("tree")["folders"]
    assert CENTS["title"] in owner.call("briefing")
    assert owner.call("board")["columns"]


def test_a_read_only_servers_hooks_still_brief_and_never_block_a_coding_agent(
    hosted: RunningServer, team: Team
) -> None:
    under(hosted, hosted_key())
    owner = team.owner

    assert CENTS["title"] in added_context(owner.start())
    owner.prompt("How are money amounts stored?")
    assert owner.edit("src/ledger.py") == {}
    assert owner.end() == {}


def test_a_read_only_server_still_runs_the_team(hosted: RunningServer, team: Team) -> None:
    under(hosted, hosted_key())
    owner = team.owner

    assert owner.call("take_lock", path="src/ledger.py", session="s-1")["locked"] is True
    assert owner.call("set_activity", activity="Splitting the ledger", session="s-1")
    moved = owner.call("update_card", number=team.card, column="done")
    assert owner.call("reissue_token", member_id="emp-2")["personal_token"]
    assert owner.call("remove_member", member_id="emp-2") == {"removed": "emp-2"}

    (not_retired,) = moved["known_issues_fixed"]
    assert moved["column"] == "done"
    assert not_retired["status"] == "not_retired"
    assert read_only_refusal(not_retired["reason"])
    assert owner.call("read", path=team.known_issue)["status"] == "active"


def test_a_call_without_a_valid_personal_token_is_refused_for_that_not_for_read_only(
    hosted: RunningServer, team: Team
) -> None:
    under(hosted, hosted_key())
    stranger = dataclasses.replace(team.owner, token="smt_not-a-real-token")

    assert "not recognised" in stranger.refusal("remember", **SERVICES)


def test_installing_a_renewed_key_ends_read_only(hosted: RunningServer, team: Team) -> None:
    under(hosted, hosted_key())
    assert read_only_refusal(team.owner.refusal("remember", **SERVICES))

    under(hosted, hosted_key(expires=RENEWED_UNTIL))

    assert team.owner.call("remember", **SERVICES)["path"]


def test_a_self_hosted_server_whose_key_has_lapsed_still_saves(hosted: RunningServer, team: Team) -> None:
    under(hosted, self_hosted_key())
    owner = team.owner

    saved = remember(owner, SERVICES)
    assert owner.call("edit_memory", path=saved, title="Billing is three services, still")["path"]
    assert owner.call("decide_challenge", challenge_id=team.challenge_id, decision="reject")
    assert owner.call("retire", path=team.project_memory)["status"] == "retired"
    assert owner.call("add_card", title="Retry failed webhooks")["number"]
