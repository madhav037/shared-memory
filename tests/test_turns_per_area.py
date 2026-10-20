"""Saves take turns per area (ADR-0012): saves by different members, or in different projects, don't wait for each
other; saves into the same project memory still do.

A turn is made slow by slowing the commit a save builds inside it, since embedding happens before the turn (#155). The
tests that race saves also run with their calls split across two workers sharing one database and memory folder
(ADR-0013), where the turns are held in Postgres.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path, PurePosixPath
from typing import Any

import pygit2
import pytest

import shared_memory.store as store_module
from shared_memory.memory import Area, Memory
from shared_memory.store import Committer, MemoryStore
from tests.support import Session, Team, member, promote_now
from tests.test_failed_saves import fail_committing_the_index, git, head, indexed, uncommitted, word

__all__ = ["fail_committing_the_index"]  # a fixture these tests use

SLOW_TURN = 1.0


@pytest.fixture
def slow_turns(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Call it to make every save's turn take SLOW_TURN longer from then on."""

    def slow_down() -> None:
        original = MemoryStore._commit

        def slow_commit(self: MemoryStore, *args: Any, **kwargs: Any) -> Any:
            time.sleep(SLOW_TURN)
            return original(self, *args, **kwargs)

        monkeypatch.setattr(MemoryStore, "_commit", slow_commit)

    return slow_down


def note(title: str, body: str | None = None, type: str = "gotcha") -> dict[str, str]:
    return {
        "title": f"{title} {uuid.uuid4().hex[:6]}",
        "summary": f"What {title} taught.",
        "type": type,
        "body": body or f"{title}: {word()}.",
    }


# Each member's name, by their personal token.
NAMES: dict[str, str] = {}


def members(team: Team, project: str, count: int, prefix: str = "m") -> list[Session]:
    sessions = []
    for number in range(count):
        session = member(team, project, f"{prefix}{number}", f"Member {prefix}{number}")
        NAMES[session.token or ""] = f"Member {prefix}{number}"
        sessions.append(session)
    return sessions


Elsewhere = Callable[[Session], Session]


def split(sessions: list[Session], elsewhere: Elsewhere) -> list[Session]:
    """Every other session handled by the other worker, when the calls are split."""
    return [session if n % 2 == 0 else elsewhere(session) for n, session in enumerate(sessions)]


def all_at_once(calls: list[tuple[Session, str, dict[str, Any]]]) -> tuple[list[Any], float]:
    started = time.monotonic()
    futures: list[Future[Any]] = [session.call_soon(tool, **arguments) for session, tool, arguments in calls]
    results = [future.result(timeout=120) for future in futures]
    return results, time.monotonic() - started


def test_saves_by_different_members_into_their_personal_memory_overlap(
    team: Team, project: str, slow_turns: Callable[[], None], elsewhere: Elsewhere
) -> None:
    sessions = split(members(team, project, 5), elsewhere)
    for session in sessions:
        session.call("remember", **note("Warm-up"))  # each member's folder exists before the timing starts
    slow_turns()

    results, took = all_at_once([(session, "remember", note("Overlapping")) for session in sessions])

    assert len({result["path"] for result in results}) == len(sessions)
    assert took < SLOW_TURN * 3, f"{len(sessions)} saves took {took:.1f} s, as if one at a time"


def test_saves_in_different_projects_overlap(
    team: Team, slow_turns: Callable[[], None], elsewhere: Elsewhere
) -> None:
    owner = team.owner()
    projects = [owner.call("create_project", name=f"Overlap {n}")["project_id"] for n in range(5)]
    sessions = split([owner.in_project(project) for project in projects], elsewhere)
    for session in sessions:
        # Each project's folders already exist, so no promotion creates or empties one the projects share.
        promote_now(session, note("Deploy windows", "Deploys happen on Tuesday mornings only.", type="decision"))
        session.call("remember", **note("Local ports", "The dev database listens on port 6543.", type="decision"))
    personal = [
        session.call("remember", **note("Logging", "Log lines are structured JSON with a request id.", type="gotcha"))
        for session in sessions
    ]
    slow_turns()

    results, took = all_at_once(
        [(session, "promote", {"path": saved["path"], "level": "project"}) for session, saved in zip(sessions, personal, strict=True)]
    )


    assert [result["status"] for result in results] == ["promoted"] * len(sessions)
    assert took < SLOW_TURN * 3, f"{len(sessions)} promotions took {took:.1f} s, as if one at a time"


def test_saves_into_the_same_project_memory_still_take_turns(
    team: Team, project: str, slow_turns: Callable[[], None], elsewhere: Elsewhere
) -> None:
    sessions = split(members(team, project, 3), elsewhere)
    subjects = ["Kafka topic naming", "Terraform state locking", "Pixel density of icons"]
    personal = [
        session.call("remember", **note(subject, f"{subject} is settled: {word()}.", type="convention"))
        for session, subject in zip(sessions, subjects, strict=True)
    ]
    slow_turns()

    results, took = all_at_once(
        [(session, "promote", {"path": saved["path"], "level": "project"}) for session, saved in zip(sessions, personal, strict=True)]
    )

    assert [result["status"] for result in results] == ["promoted"] * len(sessions)
    assert took >= SLOW_TURN * len(sessions), f"{len(sessions)} promotions into one project took only {took:.1f} s"


def test_a_save_that_loses_the_race_to_move_main_builds_on_the_new_main_and_both_land(
    team: Team, owner: Session, dana: Session, monkeypatch: pytest.MonkeyPatch, elsewhere: Elsewhere
) -> None:
    dana = elsewhere(dana)
    owner.call("remember", **note("Owner's folder"))
    losing, winning = note("Loses the race"), note("Wins the race")
    original = store_module._move_main
    attempts: list[str] = []

    def contested(repository: pygit2.Repository, expected: Any, commit: pygit2.Oid, why: str, *turn: Any) -> bool:
        if losing["title"] in why:
            attempts.append(why)
            if len(attempts) == 1:
                # Another area moves main between the losing save building its commit and moving main to it.
                dana.call("remember", **winning)
        return original(repository, expected, commit, why, *turn)

    monkeypatch.setattr(store_module, "_move_main", contested)

    lost = owner.call("remember", **losing)

    assert len(attempts) == 2
    log = git(team, "log", "-2", "--format=%an|%s").splitlines()
    assert log == [f"Olive Owner|Remember: {losing['title']}", f"Dana Dev|Remember: {winning['title']}"]
    assert owner.call("read", path=lost["path"])["title"] == losing["title"]
    people = git(team, "show", f"HEAD:{team.code}/{PurePosixPath(lost['path']).parents[2]}/index.md")
    assert "[emp-2/]" in people and "[owner-1/]" in people
    assert uncommitted(team) == []


def test_two_areas_creating_folders_under_one_parent_both_appear_in_its_index(
    team: Team, project: str, monkeypatch: pytest.MonkeyPatch, elsewhere: Elsewhere
) -> None:
    original = store_module.write_whole
    order: dict[str, list[Path]] = {"memories": [], "listings": []}
    arriving = threading.Lock()

    def late_listing(file: Path, text: str) -> None:
        """Each save creates its folder a little after the one before, and the first to list the members' shared
        folder writes its listing last: without taking turns on that folder, the earliest listing would win."""
        kind = "listings" if file.name == "index.md" and file.parent.name == "people" else "memories"
        if kind == "listings" or file.name != "index.md":
            with arriving:
                order[kind].append(file)
                place = len(order[kind])
            time.sleep(0.2 * (place - 1) if kind == "memories" else max(0.0, 1.0 - 0.4 * place))
        original(file, text)
    monkeypatch.setattr(store_module, "write_whole", late_listing)
    for trial in range(2):
        sessions = split(members(team, project, 3, prefix=f"new{trial}-"), elsewhere)
        order["memories"].clear()
        order["listings"].clear()

        all_at_once([(session, "remember", note("First memory")) for session in sessions])

        people = f"{team.code}/projects/{project}/people/index.md"
        listed = git(team, "show", f"HEAD:{people}")
        on_disk = (team.server.settings.memory_root / people).read_text(encoding="utf-8")
        for number in range(3):
            assert f"[new{trial}-{number}/]" in listed
        assert on_disk == listed
    assert uncommitted(team) == []

def test_a_failed_save_never_undoes_another_areas_save_that_landed_meanwhile(
    team: Team,
    owner: Session,
    dana: Session,
    fail_committing_the_index: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
    elsewhere: Elsewhere,
) -> None:
    dana = elsewhere(dana)
    owner.call("remember", **note("Owner's folder"))
    doomed, landing = note("Doomed save"), note("Lands meanwhile")
    fail_committing_the_index(doomed["title"].lower().replace(" ", "-").replace("'", ""))
    original = store_module._move_main
    landed: list[dict[str, Any]] = []

    def meanwhile(repository: pygit2.Repository, expected: Any, commit: pygit2.Oid, why: str, *turn: Any) -> bool:
        if doomed["title"] in why and not landed:
            landed.append(dana.call("remember", **landing))
        return original(repository, expected, commit, why, *turn)

    monkeypatch.setattr(store_module, "_move_main", meanwhile)

    refusal = owner.refusal("remember", **doomed)

    assert "not saved" in refusal
    saved = landed[0]["path"]
    assert dana.call("read", path=saved)["title"] == landing["title"]
    assert indexed(team, landing["body"].split()[-1].rstrip(".")) == [saved]
    assert f"{team.code}/{saved}" in git(team, "ls-tree", "-r", "--name-only", "HEAD")
    people = git(team, "show", f"HEAD:{team.code}/{PurePosixPath(saved).parents[2]}/index.md")
    assert "[emp-2/]" in people
    assert git(team, "log", "-1", "--format=%s").startswith("Revert ")
    assert uncommitted(team) == []


def test_many_members_saving_at_once_leave_one_commit_each_authored_by_them(
    team: Team, project: str, elsewhere: Elsewhere
) -> None:
    other = team.owner().call("create_project", name="Second project")["project_id"]
    sessions = split(members(team, project, 6) + members(team, other, 4, prefix="o"), elsewhere)
    before = int(git(team, "rev-list", "--count", "HEAD")) if head(team) else 0
    saves = [(session, "remember", note("Parallel note")) for session in sessions for _ in range(3)]

    results, _ = all_at_once(saves)

    assert int(git(team, "rev-list", "--count", "HEAD")) == before + len(saves)
    authors = {f"Remember: {arguments['title']}": NAMES[session.token or ""] for session, _, arguments in saves}
    commits = [line.split("|", 1) for line in git(team, "log", f"-{len(saves)}", "--format=%an|%s").splitlines()]
    assert sorted(subject for _, subject in commits) == sorted(authors)
    assert all(author == authors[subject] for author, subject in commits)
    for (session, _, arguments), result in zip(saves, results, strict=True):
        assert session.call("read", path=result["path"])["title"] == arguments["title"]
        assert indexed(team, arguments["body"].split()[-1].rstrip(".")) == [result["path"]]
    for folder in (f"projects/{project}/people", f"projects/{other}/people", "projects"):
        listed = git(team, "show", f"HEAD:{team.code}/{folder}/index.md")
        below = (team.server.settings.memory_root / team.code / folder).iterdir()
        assert all(f"[{sub.name}/]" in listed for sub in below if sub.is_dir())
    assert uncommitted(team) == []

def test_a_save_writing_outside_the_areas_it_declared_fails_loudly(tmp_path: Any) -> None:
    store = MemoryStore(tmp_path / "memory")
    memory = Memory(title="Stray", summary="Written outside its area.", type="gotcha", author="m1", body="Stray.")
    mine = Area("personal", "p1", "m1")

    with pytest.raises(AssertionError, match="outside"):
        with store.change("t1", Committer("m1", "Member One"), "Stray", areas=[mine]) as change:
            change.write(PurePosixPath("projects/p1/people/m2/gotchas/stray.md"), memory)

    assert not (tmp_path / "memory" / "t1").exists()


