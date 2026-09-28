"""A save that fails at any step leaves the memory folder, its git history and the search index as they were.

The failures are real ones: git finding its index held by a process that died holding it, and Postgres refusing
the search index's rows or the audit log's, the last after git has already committed the save.
"""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

from tests.support import Session, Team

Refuse = Callable[[str], None]


def git(team: Team, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(team.server.settings.memory_root), *args], capture_output=True, text=True, check=True
    ).stdout


def head(team: Team) -> str:
    """The last commit, or nothing before the first."""
    root = str(team.server.settings.memory_root)
    return subprocess.run(
        ["git", "-C", root, "rev-parse", "-q", "--verify", "HEAD"], capture_output=True, text=True
    ).stdout.strip()


def uncommitted(team: Team) -> str:
    """Anything in the team's folder that differs from its last commit, staged or not, tracked or not."""
    return git(team, "status", "--porcelain", "--untracked-files=all", "--", team.code)


def files_named(team: Team, fragment: str) -> list[Path]:
    return [file for file in (team.server.settings.memory_root / team.code).rglob("*") if fragment in file.name]


def indexed(team: Team, word: str) -> list[str]:
    """The memories the search index holds a word for.

    Asked of the index itself, since a search always offers the memories nearest in meaning, holding the word or not.
    """
    with psycopg.connect(team.server.settings.database_url) as conn:
        rows = conn.execute(
            "SELECT DISTINCT path FROM sections WHERE team = %s AND tokens @@ to_tsquery('simple', %s) ORDER BY path",
            (team.code, word),
        ).fetchall()
    return [row[0] for row in rows]


def word() -> str:
    """A word no other memory holds, so a search for it finds only the memory it was written into."""
    return f"quillwort{uuid.uuid4().hex[:8]}"


@pytest.fixture
def stale_git_lock(team: Team) -> Iterator[None]:
    """git's index held by a process that died holding it, as a crashed git or a second server leaves it."""
    lock = team.server.settings.memory_root / ".git" / "index.lock"
    lock.write_text("")
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


@contextmanager
def refusing(team: Team, table: str, column: str, message: str) -> Iterator[Refuse]:
    """Make Postgres refuse a table's rows whose column holds any fragment passed to the function this yields."""
    with psycopg.connect(team.server.settings.database_url, autocommit=True) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS refused_fragments (fragment TEXT PRIMARY KEY)")
        conn.execute(
            """
            CREATE OR REPLACE FUNCTION refuse_fragments() RETURNS trigger AS $$
            DECLARE row JSONB;
            BEGIN
                IF TG_OP = 'DELETE' THEN row := to_jsonb(OLD); ELSE row := to_jsonb(NEW); END IF;
                IF EXISTS (SELECT 1 FROM refused_fragments WHERE position(fragment IN row->>TG_ARGV[0]) > 0) THEN
                    RAISE EXCEPTION '%', TG_ARGV[1];
                END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END $$ LANGUAGE plpgsql
            """
        )
        conn.execute(
            f"CREATE TRIGGER refuse_fragments BEFORE INSERT OR UPDATE OR DELETE ON {table}"
            f" FOR EACH ROW EXECUTE FUNCTION refuse_fragments('{column}', '{message}')"
        )

        def refuse(fragment: str) -> None:
            conn.execute("INSERT INTO refused_fragments (fragment) VALUES (%s)", (fragment,))

        try:
            yield refuse
        finally:
            conn.execute(f"DROP TRIGGER refuse_fragments ON {table}")
            conn.execute("DELETE FROM refused_fragments")


@pytest.fixture
def fail_indexing(team: Team) -> Iterator[Refuse]:
    """Make the search index refuse any memory whose path holds a fragment."""
    with refusing(team, "sections", "path", "the search index is unavailable") as refuse:
        yield refuse


@pytest.fixture
def fail_auditing(team: Team) -> Iterator[Refuse]:
    """Make the audit log refuse any entry about a memory whose path holds a fragment."""
    with refusing(team, "audit_events", "target", "the audit log is unavailable") as refuse:
        yield refuse


def remember(session: Session, title: str, body: str, type: str = "gotcha") -> str:
    path: str = session.call("remember", title=title, summary="What was learned.", type=type, body=body)["path"]
    return path


# Git refusing the save


def test_a_new_memory_git_refuses_leaves_no_file_no_commit_and_nothing_to_search(
    team: Team, owner: Session, stale_git_lock: None
) -> None:
    title, unique = f"Unsaved {uuid.uuid4().hex[:6]}", word()
    before = head(team)

    refusal = owner.refusal("remember", title=title, summary="Never lands.", type="gotcha", body=unique)

    assert "not saved" in refusal
    assert "index.lock" in refusal
    assert head(team) == before
    assert uncommitted(team) == ""
    assert files_named(team, title.split()[1]) == []
    assert indexed(team, unique) == []


def test_the_next_members_save_after_a_refused_one_commits_only_their_own_memory(
    team: Team, owner: Session, dana: Session
) -> None:
    lock = team.server.settings.memory_root / ".git" / "index.lock"
    lock.write_text("")
    try:
        owner.refusal("remember", title="Owner's lost note", summary="Never lands.", type="gotcha", body="b")
    finally:
        lock.unlink()

    saved = remember(dana, "Dana's note", "Dana's body.")

    committed = git(team, "show", "--name-only", "--format=", "HEAD").split()
    assert git(team, "log", "-1", "--format=%an").strip() == "Dana Dev"
    assert f"{team.code}/{saved}" in committed
    assert [path for path in committed if path != f"{team.code}/{saved}" and not path.endswith("/index.md")] == []
    assert not [path for path in committed if "/owner-1/" in path]


def test_an_edit_git_refuses_leaves_the_memory_as_it_was(team: Team, owner: Session) -> None:
    kept, changed = word(), word()
    path = remember(owner, f"Edited {uuid.uuid4().hex[:6]}", kept)
    before = head(team)

    lock = team.server.settings.memory_root / ".git" / "index.lock"
    lock.write_text("")
    try:
        refusal = owner.refusal("edit_memory", path=path, body=changed)
    finally:
        lock.unlink()

    assert "not saved" in refusal
    assert owner.call("read", path=path)["body"].strip() == kept
    assert head(team) == before
    assert uncommitted(team) == ""
    assert indexed(team, kept) == [path]
    assert indexed(team, changed) == []


def test_a_delete_git_refuses_leaves_the_memory_in_place(team: Team, owner: Session) -> None:
    unique = word()
    path = remember(owner, f"Kept {uuid.uuid4().hex[:6]}", unique)

    lock = team.server.settings.memory_root / ".git" / "index.lock"
    lock.write_text("")
    try:
        refusal = owner.refusal("delete_memory", path=path)
    finally:
        lock.unlink()

    assert "not saved" in refusal
    assert owner.call("read", path=path)["body"].strip() == unique
    assert uncommitted(team) == ""
    assert indexed(team, unique) == [path]


# The search index refusing the save


def test_a_new_memory_the_search_index_refuses_leaves_no_file_and_no_commit(
    team: Team, owner: Session, fail_indexing: Refuse
) -> None:
    tag = uuid.uuid4().hex[:8]
    fail_indexing(tag)
    before = head(team)

    refusal = owner.refusal("remember", title=f"Unindexed {tag}", summary="Never lands.", type="gotcha", body="b")

    assert "not saved" in refusal
    assert "search index is unavailable" in refusal
    assert head(team) == before
    assert uncommitted(team) == ""
    assert files_named(team, tag) == []


def test_an_edit_the_search_index_refuses_leaves_the_file_git_and_search_as_they_were(
    team: Team, owner: Session, fail_indexing: Refuse
) -> None:
    tag, kept, changed = uuid.uuid4().hex[:8], word(), word()
    path = remember(owner, f"Indexed {tag}", kept)
    fail_indexing(tag)
    before = head(team)

    refusal = owner.refusal("edit_memory", path=path, summary="Reworded.", body=changed)

    assert "not saved" in refusal
    memory = owner.call("read", path=path)
    assert (memory["summary"], memory["body"].strip()) == ("What was learned.", kept)
    assert head(team) == before
    assert uncommitted(team) == ""
    assert indexed(team, kept) == [path]
    assert indexed(team, changed) == []


def test_a_promotion_the_search_index_refuses_leaves_the_memory_personal(
    team: Team, owner: Session, fail_indexing: Refuse
) -> None:
    tag, unique = uuid.uuid4().hex[:8], word()
    path = remember(owner, f"Promoted {tag}", unique, type="architecture")
    fail_indexing(tag)
    before = head(team)

    refusal = owner.refusal("promote", path=path, level="project")

    assert "not saved" in refusal
    assert owner.call("read", path=path)["level"] == "personal"
    assert [file.name for file in files_named(team, tag)] == [f"promoted-{tag}.md"]
    assert head(team) == before
    assert uncommitted(team) == ""
    assert indexed(team, unique) == [path]


# The audit log refusing the save, after git has committed it


def test_a_new_memory_the_audit_log_refuses_is_taken_back_out_of_git_and_the_index(
    team: Team, owner: Session, fail_auditing: Refuse
) -> None:
    tag, unique = uuid.uuid4().hex[:8], word()
    fail_auditing(tag)
    before = head(team)

    refusal = owner.refusal("remember", title=f"Unaudited {tag}", summary="Never lands.", type="gotcha", body=unique)

    assert "not saved" in refusal
    assert "audit log is unavailable" in refusal
    assert head(team) == before
    assert uncommitted(team) == ""
    assert files_named(team, tag) == []
    assert indexed(team, unique) == []


def test_an_edit_the_audit_log_refuses_leaves_the_file_git_and_search_as_they_were(
    team: Team, owner: Session, fail_auditing: Refuse
) -> None:
    tag, kept, changed = uuid.uuid4().hex[:8], word(), word()
    path = remember(owner, f"Audited {tag}", kept)
    fail_auditing(tag)
    before = head(team)

    refusal = owner.refusal("edit_memory", path=path, body=changed)

    assert "not saved" in refusal
    assert owner.call("read", path=path)["body"].strip() == kept
    assert head(team) == before
    assert uncommitted(team) == ""
    assert indexed(team, kept) == [path]
    assert indexed(team, changed) == []


# Stray files in the memory folder


def test_a_save_commits_only_the_files_it_changed(team: Team, owner: Session) -> None:
    folder = team.server.settings.memory_root / team.code
    stray = [folder / "stray.md", folder / f".left-behind.md.{uuid.uuid4().hex}.saving"]
    folder.mkdir(parents=True, exist_ok=True)
    for file in stray:
        file.write_text("Not written by any save.\n")
    try:
        saved = remember(owner, f"Committed alone {uuid.uuid4().hex[:6]}", "b")

        committed = git(team, "show", "--name-only", "--format=", "HEAD").split()
    finally:
        for file in stray:
            file.unlink(missing_ok=True)

    assert f"{team.code}/{saved}" in committed
    assert not [path for path in committed if "stray" in path or "left-behind" in path]
