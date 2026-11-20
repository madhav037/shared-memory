"""A save that fails at any step leaves the memory folder, its git history and the search index agreeing.

The failures are real ones: git finding main held by a process that died holding it, and Postgres refusing the
search index's rows or the audit log's. A failure before the save moves main leaves main as it was; one after it,
such as the audit log refusing or the search index's transaction failing to commit, is put back by a revert commit.
The tests where another member saves next also run with that member on a second worker (ADR-0013).
"""

from __future__ import annotations

import hashlib
import subprocess
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

from tests.support import Session, Company

Refuse = Callable[[str], None]


def git(company: Company, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(company.server.settings.memory_root), *args], capture_output=True, text=True, check=True
    ).stdout


def head(company: Company) -> str:
    """The last commit, or nothing before the first."""
    root = str(company.server.settings.memory_root)
    return subprocess.run(
        ["git", "-C", root, "rev-parse", "-q", "--verify", "HEAD"], capture_output=True, text=True
    ).stdout.strip()


def tree(company: Company, commit: str) -> str:
    """What a commit holds of the company's folder, as git names it: two commits holding the same files agree."""
    root = str(company.server.settings.memory_root)
    return subprocess.run(
        ["git", "-C", root, "rev-parse", "-q", "--verify", f"{commit}:{company.code}"], capture_output=True, text=True
    ).stdout.strip()


def _blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def uncommitted(company: Company) -> list[str]:
    """Every file in the company's folder that differs from the last commit, or is on only one side of it.

    Compared with the commit itself, not git's index, which saves don't keep up to date.
    """
    root = company.server.settings.memory_root
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "-z", "HEAD", "--", company.code], capture_output=True, text=True
    ).stdout
    committed: dict[str, str] = {}
    for entry in filter(None, listed.split("\0")):
        meta, path = entry.split("\t", 1)
        committed[path] = meta.split()[2]
    folder = root / company.code
    on_disk = {
        f"{company.code}/{file.relative_to(folder).as_posix()}": _blob(file.read_bytes())
        for file in (folder.rglob("*") if folder.is_dir() else [])
        if file.is_file()
    }
    return sorted(path for path in committed.keys() | on_disk.keys() if committed.get(path) != on_disk.get(path))


def files_named(company: Company, fragment: str) -> list[Path]:
    return [file for file in (company.server.settings.memory_root / company.code).rglob("*") if fragment in file.name]


def indexed(company: Company, word: str) -> list[str]:
    """The memories the search index holds a word for.

    Asked of the index itself, since a search always offers the memories nearest in meaning, holding the word or not.
    """
    with psycopg.connect(company.server.settings.database_url) as conn:
        rows = conn.execute(
            "SELECT DISTINCT path FROM sections WHERE team = %s AND tokens @@ to_tsquery('simple', %s) ORDER BY path",
            (company.code, word),
        ).fetchall()
    return [row[0] for row in rows]


def word() -> str:
    """A word no other memory holds, so a search for it finds only the memory it was written into."""
    return f"quillwort{uuid.uuid4().hex[:8]}"


def main_lock(company: Company) -> Path:
    return company.server.settings.memory_root / ".git" / "refs" / "heads" / "main.lock"


@pytest.fixture
def stale_git_lock(company: Company) -> Iterator[None]:
    """main held by a process that died holding it, as a crashed git or a second server leaves it."""
    lock = main_lock(company)
    lock.write_text("")
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


@contextmanager
def refusing(company: Company, table: str, column: str, message: str, *, at_commit: bool = False) -> Iterator[Refuse]:
    """Make Postgres refuse a table's rows whose column holds any fragment passed to the function this yields.

    At commit, the rows are refused only when their transaction commits, not when they are written.
    """
    with psycopg.connect(company.server.settings.database_url, autocommit=True) as conn:
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
        when = (
            "CONSTRAINT TRIGGER refuse_fragments AFTER INSERT OR UPDATE OR DELETE ON {table}"
            " DEFERRABLE INITIALLY DEFERRED"
            if at_commit
            else "TRIGGER refuse_fragments BEFORE INSERT OR UPDATE OR DELETE ON {table}"
        ).format(table=table)
        conn.execute(f"CREATE {when} FOR EACH ROW EXECUTE FUNCTION refuse_fragments('{column}', '{message}')")

        def refuse(fragment: str) -> None:
            conn.execute("INSERT INTO refused_fragments (fragment) VALUES (%s)", (fragment,))

        try:
            yield refuse
        finally:
            conn.execute(f"DROP TRIGGER refuse_fragments ON {table}")
            conn.execute("DELETE FROM refused_fragments")


@pytest.fixture
def fail_indexing(company: Company) -> Iterator[Refuse]:
    """Make the search index refuse any memory whose path holds a fragment."""
    with refusing(company, "sections", "path", "the search index is unavailable") as refuse:
        yield refuse


@pytest.fixture
def fail_committing_the_index(company: Company) -> Iterator[Refuse]:
    """Make the search index's transaction fail to commit for any memory whose path holds a fragment."""
    with refusing(company, "sections", "path", "the search index could not commit", at_commit=True) as refuse:
        yield refuse


@pytest.fixture
def fail_auditing(company: Company) -> Iterator[Refuse]:
    """Make the audit log refuse any entry about a memory whose path holds a fragment."""
    with refusing(company, "audit_events", "target", "the audit log is unavailable") as refuse:
        yield refuse


def remember(session: Session, title: str, body: str, type: str = "gotcha") -> str:
    path: str = session.call("remember", title=title, summary="What was learned.", type=type, body=body)["path"]
    return path


def assert_reverted(company: Company, before: str) -> None:
    """main moved past `before` only by the save and the commit putting it back, which hold what `before` held."""
    assert head(company) != before
    assert git(company, "rev-parse", "HEAD~2").strip() == before
    assert git(company, "log", "-1", "--format=%s").startswith("Revert ")
    assert tree(company, "HEAD") == tree(company, before)
    assert uncommitted(company) == []


# Git refusing the save, before main moves


def test_a_new_memory_git_refuses_leaves_no_file_no_commit_and_nothing_to_search(
    company: Company, owner: Session, stale_git_lock: None
) -> None:
    title, unique = f"Unsaved {uuid.uuid4().hex[:6]}", word()
    before = head(company)

    refusal = owner.refusal("remember", title=title, summary="Never lands.", type="gotcha", body=unique)

    assert "not saved" in refusal
    assert "main.lock" in refusal
    assert head(company) == before
    assert uncommitted(company) == []
    assert files_named(company, title.split()[1]) == []
    assert indexed(company, unique) == []


def test_the_next_members_save_after_a_refused_one_commits_only_their_own_memory(
    company: Company, owner: Session, dana: Session, elsewhere: Callable[[Session], Session]
) -> None:
    dana = elsewhere(dana)
    remember(dana, f"Dana's first {uuid.uuid4().hex[:6]}", "b")
    lock = main_lock(company)
    lock.write_text("")
    try:
        owner.refusal("remember", title="Owner's lost note", summary="Never lands.", type="gotcha", body="b")
    finally:
        lock.unlink()

    saved = remember(dana, "Dana's note", "Dana's body.")

    committed = git(company, "show", "--name-only", "--format=", "HEAD").split()
    assert git(company, "log", "-1", "--format=%an").strip() == "Dana Dev"
    assert f"{company.code}/{saved}" in committed
    assert [path for path in committed if path != f"{company.code}/{saved}" and not path.endswith("/index.md")] == []
    assert not [path for path in committed if "/owner-1/" in path]


def test_an_edit_git_refuses_leaves_the_memory_as_it_was(company: Company, owner: Session) -> None:
    kept, changed = word(), word()
    path = remember(owner, f"Edited {uuid.uuid4().hex[:6]}", kept)
    before = head(company)

    lock = main_lock(company)
    lock.write_text("")
    try:
        refusal = owner.refusal("edit_memory", path=path, body=changed)
    finally:
        lock.unlink()

    assert "not saved" in refusal
    assert owner.call("read", path=path)["body"].strip() == kept
    assert head(company) == before
    assert uncommitted(company) == []
    assert indexed(company, kept) == [path]
    assert indexed(company, changed) == []


def test_a_delete_git_refuses_leaves_the_memory_in_place(company: Company, owner: Session) -> None:
    unique = word()
    path = remember(owner, f"Kept {uuid.uuid4().hex[:6]}", unique)

    lock = main_lock(company)
    lock.write_text("")
    try:
        refusal = owner.refusal("delete_memory", path=path)
    finally:
        lock.unlink()

    assert "not saved" in refusal
    assert owner.call("read", path=path)["body"].strip() == unique
    assert uncommitted(company) == []
    assert indexed(company, unique) == [path]


# The search index refusing the save, before main moves


def test_a_new_memory_the_search_index_refuses_leaves_no_file_and_no_commit(
    company: Company, owner: Session, fail_indexing: Refuse
) -> None:
    tag = uuid.uuid4().hex[:8]
    fail_indexing(tag)
    before = head(company)

    refusal = owner.refusal("remember", title=f"Unindexed {tag}", summary="Never lands.", type="gotcha", body="b")

    assert "not saved" in refusal
    assert "search index is unavailable" in refusal
    assert head(company) == before
    assert uncommitted(company) == []
    assert files_named(company, tag) == []


def test_an_edit_the_search_index_refuses_leaves_the_file_git_and_search_as_they_were(
    company: Company, owner: Session, fail_indexing: Refuse
) -> None:
    tag, kept, changed = uuid.uuid4().hex[:8], word(), word()
    path = remember(owner, f"Indexed {tag}", kept)
    fail_indexing(tag)
    before = head(company)

    refusal = owner.refusal("edit_memory", path=path, summary="Reworded.", body=changed)

    assert "not saved" in refusal
    memory = owner.call("read", path=path)
    assert (memory["summary"], memory["body"].strip()) == ("What was learned.", kept)
    assert head(company) == before
    assert uncommitted(company) == []
    assert indexed(company, kept) == [path]
    assert indexed(company, changed) == []


def test_a_promotion_the_search_index_refuses_leaves_the_memory_personal(
    company: Company, owner: Session, fail_indexing: Refuse
) -> None:
    tag, unique = uuid.uuid4().hex[:8], word()
    path = remember(owner, f"Promoted {tag}", unique, type="architecture")
    fail_indexing(tag)
    before = head(company)

    refusal = owner.refusal("promote", path=path, level="project")

    assert "not saved" in refusal
    assert owner.call("read", path=path)["level"] == "personal"
    assert [file.name for file in files_named(company, tag)] == [f"promoted-{tag}.md"]
    assert head(company) == before
    assert uncommitted(company) == []
    assert indexed(company, unique) == [path]


# The audit log refusing the save, after main has moved


def test_a_new_memory_the_audit_log_refuses_is_reverted_out_of_git_and_the_index(
    company: Company, owner: Session, fail_auditing: Refuse
) -> None:
    remember(owner, f"Already there {uuid.uuid4().hex[:6]}", "b")
    tag, unique = uuid.uuid4().hex[:8], word()
    fail_auditing(tag)
    before = head(company)

    refusal = owner.refusal("remember", title=f"Unaudited {tag}", summary="Never lands.", type="gotcha", body=unique)

    assert "not saved" in refusal
    assert "audit log is unavailable" in refusal
    assert_reverted(company, before)
    assert files_named(company, tag) == []
    assert indexed(company, unique) == []


def test_an_edit_the_audit_log_refuses_leaves_the_file_git_and_search_as_they_were(
    company: Company, owner: Session, fail_auditing: Refuse
) -> None:
    tag, kept, changed = uuid.uuid4().hex[:8], word(), word()
    path = remember(owner, f"Audited {tag}", kept)
    fail_auditing(tag)
    before = head(company)

    refusal = owner.refusal("edit_memory", path=path, body=changed)

    assert "not saved" in refusal
    assert owner.call("read", path=path)["body"].strip() == kept
    assert_reverted(company, before)
    assert indexed(company, kept) == [path]
    assert indexed(company, changed) == []


# The search index failing to commit, after main has moved


def test_a_new_memory_whose_index_fails_to_commit_is_reverted_and_files_git_and_search_agree(
    company: Company, owner: Session, fail_committing_the_index: Refuse
) -> None:
    remember(owner, f"Already there {uuid.uuid4().hex[:6]}", "b")
    tag, unique = uuid.uuid4().hex[:8], word()
    fail_committing_the_index(tag)
    before = head(company)

    refusal = owner.refusal("remember", title=f"Uncommitted {tag}", summary="Never lands.", type="gotcha", body=unique)

    assert "not saved" in refusal
    assert "search index could not commit" in refusal
    assert_reverted(company, before)
    assert files_named(company, tag) == []
    assert indexed(company, unique) == []


def test_an_edit_whose_index_fails_to_commit_is_reverted_and_the_memory_reads_as_it_was(
    company: Company,
    owner: Session,
    dana: Session,
    fail_committing_the_index: Refuse,
    elsewhere: Callable[[Session], Session],
) -> None:
    dana = elsewhere(dana)
    tag, kept, changed = uuid.uuid4().hex[:8], word(), word()
    path = remember(owner, f"Reverted {tag}", kept)
    fail_committing_the_index(tag)
    before = head(company)

    refusal = owner.refusal("edit_memory", path=path, body=changed)

    assert "not saved" in refusal
    assert elsewhere(owner).call("read", path=path)["body"].strip() == kept
    assert_reverted(company, before)
    assert indexed(company, kept) == [path]
    assert indexed(company, changed) == []

    # The next member's save lands on top of the revert, carrying nothing of the reverted edit.
    saved = remember(dana, f"After the revert {uuid.uuid4().hex[:6]}", "Dana's body.")
    committed = git(company, "show", "--name-only", "--format=", "HEAD").split()
    assert git(company, "log", "-1", "--format=%an").strip() == "Dana Dev"
    assert [path for path in committed if not path.endswith("/index.md")] == [f"{company.code}/{saved}"]
    assert uncommitted(company) == []


# Stray files in the memory folder


def test_a_save_commits_only_the_files_it_changed(company: Company, owner: Session) -> None:
    folder = company.server.settings.memory_root / company.code
    stray = [folder / "stray.md", folder / f".left-behind.md.{uuid.uuid4().hex}.saving"]
    folder.mkdir(parents=True, exist_ok=True)
    for file in stray:
        file.write_text("Not written by any save.\n")
    try:
        saved = remember(owner, f"Committed alone {uuid.uuid4().hex[:6]}", "b")

        committed = git(company, "show", "--name-only", "--format=", "HEAD").split()
    finally:
        for file in stray:
            file.unlink(missing_ok=True)

    assert f"{company.code}/{saved}" in committed
    assert not [path for path in committed if "stray" in path or "left-behind" in path]
