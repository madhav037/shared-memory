from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager, suppress
from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS teams (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS members (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    member_id TEXT NOT NULL,
    name TEXT NOT NULL,
    is_owner BOOLEAN NOT NULL DEFAULT FALSE,
    removed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (team_id, member_id)
);

CREATE TABLE IF NOT EXISTS tokens (
    id BIGSERIAL PRIMARY KEY,
    member_id BIGINT NOT NULL REFERENCES members(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS repositories (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    name TEXT NOT NULL,
    PRIMARY KEY (project_id, name)
);

CREATE TABLE IF NOT EXISTS project_leads (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    member_id BIGINT NOT NULL REFERENCES members(id),
    appointed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (project_id, member_id)
);

-- Who keeps a foundation (ADR-0019): decides the challenges to it, and changes it at once. The slug is a core
-- foundation's or an extra's.
CREATE TABLE IF NOT EXISTS foundation_keepers (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    foundation TEXT NOT NULL,
    member_id BIGINT NOT NULL REFERENCES members(id),
    assigned_by BIGINT NOT NULL REFERENCES members(id),
    assigned_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (project_id, foundation, member_id)
);

-- A project's extra foundations (ADR-0019), beside the core four. The slug is the name's, and is the folder's name.
CREATE TABLE IF NOT EXISTS project_foundations (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    added_by BIGINT NOT NULL REFERENCES members(id),
    added_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (project_id, slug)
);

-- A restricted project keeps its access list when it is unrestricted, so restricting it again is one click.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS restricted BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS project_access (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    member_id BIGINT NOT NULL REFERENCES members(id),
    granted_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (project_id, member_id)
);

ALTER TABLE members ADD COLUMN IF NOT EXISTS github_login TEXT;
ALTER TABLE members ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE members ADD COLUMN IF NOT EXISTS github_user_id BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS members_one_github_login_per_team
    ON members (team_id, lower(github_login)) WHERE github_login IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS members_one_github_account_per_team
    ON members (team_id, github_user_id) WHERE github_user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS console_sessions (
    id BIGSERIAL PRIMARY KEY,
    member_id BIGINT NOT NULL REFERENCES members(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS console_sign_ins (
    state_hash TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL,
    team_id BIGINT REFERENCES teams(id),
    actor_id BIGINT REFERENCES members(id),
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    project_id TEXT,
    target TEXT,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS audit_events_by_team ON audit_events (team_id, id DESC);

-- A project's board (ADR-0014). Its row numbers the project's cards, and every change to the board locks it, so two
-- changes never interleave their numbering or their ordering.
CREATE TABLE IF NOT EXISTS boards (
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id),
    last_number INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS cards (
    id BIGSERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES boards(project_id),
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    board_column TEXT NOT NULL,
    -- Its place within its column, 1 at the top.
    position INTEGER NOT NULL,
    priority TEXT NOT NULL,
    labels TEXT[] NOT NULL DEFAULT '{}',
    due_date DATE,
    creator_id BIGINT NOT NULL REFERENCES members(id),
    assignee_id BIGINT REFERENCES members(id),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    -- When it came into the column it is in.
    moved_at TIMESTAMPTZ NOT NULL,
    UNIQUE (project_id, number)
);

CREATE INDEX IF NOT EXISTS cards_by_column ON cards (project_id, board_column, position);
-- Why a card in Blocked is waiting, and the card it waits on, if it waits on one; both cleared when it leaves Blocked.
ALTER TABLE cards ADD COLUMN IF NOT EXISTS blocked_reason TEXT;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS waits_on_id BIGINT REFERENCES cards(id) ON DELETE SET NULL;

-- What a card points at, in the order it was given: a memory by its path, or a file as repository:path.
CREATE TABLE IF NOT EXISTS card_links (
    card_id BIGINT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    place INTEGER NOT NULL,
    PRIMARY KEY (card_id, kind, target)
);

-- What members said on a card, oldest first. Anyone who reaches the project may comment, whoever the assignee is.
CREATE TABLE IF NOT EXISTS card_comments (
    id BIGSERIAL PRIMARY KEY,
    card_id BIGINT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    author_id BIGINT NOT NULL REFERENCES members(id),
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS card_comments_by_card ON card_comments (card_id, id);

-- A save's marker under one of its turns: the paths it may touch there, recorded before it writes any, and cleared
-- once it has landed or been undone. One found by the turn's next holder was left by a save cut off mid-turn.
CREATE TABLE IF NOT EXISTS save_markers (
    turn BIGINT NOT NULL,
    save_id UUID NOT NULL,
    team TEXT NOT NULL,
    paths TEXT[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (turn, save_id)
);
"""


Conn = psycopg.Connection[dict[str, Any]]


class SaveTransaction:
    """One save's transaction, holding the locks its turns are made of (ADR-0013). Which locks, and in what order, is
    decided by `store.Turns`.

    Waiting for a lock is not bounded by the statement timeout: a turn can take seconds to come, and the wait ends
    when the holder's transaction does, or its connection closes.
    """

    def __init__(self, conn: Conn, apart: Callable[[], AbstractContextManager[Conn]]) -> None:
        """apart opens a transaction on another connection, committed on its own."""
        self._conn = conn
        self._apart = apart
        self._id = uuid.uuid4()

    def hold(self, key: int) -> None:
        """Wait for a lock, and hold it until this transaction ends."""
        self._conn.execute("SET LOCAL statement_timeout = 0")
        self._conn.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
        self._conn.execute("RESET statement_timeout")

    @contextmanager
    def briefly(self, key: int) -> Iterator[None]:
        """Wait for a lock, and hold it only for the block, on this transaction's connection: no second connection
        is taken while the save holds this one."""
        self._conn.execute("SET LOCAL statement_timeout = 0")
        self._conn.execute("SELECT pg_advisory_lock(%s)", (key,))
        self._conn.execute("RESET statement_timeout")
        try:
            yield
        finally:
            self._conn.execute("SELECT pg_advisory_unlock(%s)", (key,))

    def left_behind(self, turns: Sequence[int]) -> dict[int, list[str]]:
        """The paths other saves' markers under these turns name: under a turn this save holds, only a save cut off
        mid-turn leaves one. One indexed lookup."""
        rows = self._conn.execute(
            "SELECT turn, paths FROM save_markers WHERE turn = ANY(%s) AND save_id <> %s", (list(turns), self._id)
        ).fetchall()
        found: dict[int, list[str]] = {}
        for row in rows:
            found.setdefault(row["turn"], []).extend(row["paths"])
        return found

    def mark(self, team: str, paths: dict[int, list[str]]) -> None:
        """Record, under each turn, the paths this save may touch there, committed at once and apart from the save,
        so the record outlives a save cut off before its transaction ends."""
        with self._apart() as conn:
            for turn, under in paths.items():
                conn.execute(
                    "INSERT INTO save_markers (turn, save_id, team, paths) VALUES (%s, %s, %s, %s)",
                    (turn, self._id, team, under),
                )

    def unmark(self) -> None:
        """Clear this save's markers, committed apart from the save: it was undone."""
        with self._apart() as conn:
            conn.execute("DELETE FROM save_markers WHERE save_id = %s", (self._id,))

    @contextmanager
    def apart(self, turns: Sequence[int]) -> Iterator[None]:
        """A transaction apart from the save, committed on its own when the block ends cleanly, for putting back what
        a save cut off under these turns left: the database work done in the block (the save's listeners included)
        and the clearing of its markers commit together, whatever becomes of this save."""
        with self._apart() as conn:
            yield
            conn.execute(
                "DELETE FROM save_markers WHERE turn = ANY(%s) AND save_id <> %s", (list(turns), self._id)
            )

    def commit(self) -> None:
        """Commit the save's database work and clear its markers with it, having checked first, while its turns are
        still held, everything Postgres would otherwise check only at commit. A refusal leaves the transaction open
        and usable, to undo the save."""
        with self._conn.transaction():  # a savepoint
            self._conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        self._conn.execute("DELETE FROM save_markers WHERE save_id = %s", (self._id,))
        self._conn.commit()


# One worker's connections to Postgres by default, and how many of them saves may hold at once: at most
# APART_CONNECTIONS of those for the work a save commits apart from its own transaction (its markers, and putting back
# what a cut-off save left). `Settings` sizes them from the connections all workers share.
POOL_SIZE = 20
SAVING_CONNECTIONS = 10
APART_CONNECTIONS = 2


class Database:
    def __init__(
        self,
        url: str,
        statement_timeout_seconds: float,
        pool_size: int = POOL_SIZE,
        saving_connections: int = SAVING_CONNECTIONS,
        sets_up: bool = True,
    ) -> None:
        """statement_timeout_seconds bounds every statement, waiting for a table included, so a stalled database
        fails requests instead of freezing every one of them.

        sets_up says whether this, and the classes built on it, create their tables. A worker started by `serve`
        leaves that to the setup that ran before it (see `app.setup`)."""
        options = f"-c statement_timeout={round(statement_timeout_seconds * 1000)}"
        self.sets_up = sets_up
        if sets_up:
            with psycopg.connect(url, autocommit=True, options=options) as conn:
                conn.execute(SCHEMA)
        self._pool: ConnectionPool[Conn] = ConnectionPool(
            url,
            min_size=1,
            max_size=pool_size,
            open=True,
            kwargs={"row_factory": dict_row, "options": options},
            configure=register_vector,
        )

        # Saves keep at least one connection besides the apart ones, however small the pool.
        self.apart_connections = max(1, min(APART_CONNECTIONS, saving_connections - 1))
        self._saves = threading.BoundedSemaphore(max(1, saving_connections - self.apart_connections))
        self._apart = threading.BoundedSemaphore(self.apart_connections)
        self._saving = threading.local()

    @contextmanager
    def transaction(self) -> Iterator[Conn]:
        """A transaction of its own; inside a save's transaction on the same thread, a savepoint in that one."""
        joined: Conn | None = getattr(self._saving, "conn", None)
        if joined is not None:
            with joined.transaction():
                yield joined
            return
        with self._pool.connection() as conn:
            yield conn

    @contextmanager
    def save_transaction(self) -> Iterator[SaveTransaction]:
        """One connection and one transaction for all of a save's database work: its turns (ADR-0013), its listeners
        and its audit entry. It commits when the save commits it, or when the block ends cleanly; it rolls back when
        the block fails.

        Saves in different areas run at once (ADR-0012). Each holding a connection per listener while waiting for
        another for its audit entry, they would run the pool dry and wait on each other. Saves hold at most
        the saving connections of the pool, so reads and hooks always find one free.
        """
        with self._saves, self._pool.connection() as conn:
            self._saving.conn = conn
            try:
                yield SaveTransaction(conn, self._apart_from_save)
                conn.commit()
            except BaseException:
                # A connection lost mid-save can't roll back; Postgres has already, and released its turns.
                with suppress(psycopg.Error):
                    conn.rollback()
                raise
            finally:
                self._saving.conn = None

    @contextmanager
    def _apart_from_save(self) -> Iterator[Conn]:
        """A transaction on a connection of its own, for work a save commits apart from its own transaction. While it
        is open, transactions opened on the save's thread join it instead of the save's.

        Counted within the saving connections, so a save holding its own connection while it waits for this one never
        takes one reads and hooks need, and never waits on another save holding its own."""
        saving: Conn | None = getattr(self._saving, "conn", None)
        with self._apart, self._pool.connection() as conn:
            self._saving.conn = conn
            try:
                yield conn
            finally:
                self._saving.conn = saving

    def close(self) -> None:
        self._pool.close()
