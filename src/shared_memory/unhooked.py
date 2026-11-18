"""Sessions no hook reaches (#518): a coding agent with no hooks (Copilot in VS Code, Cursor on Windows) can't be
gated, since nothing refuses its edits. Every hook that names a session says a hook reaches it; a later session no hook
has reached is told once, in its tools' notices, that its gate waits, and the console marks a session that can't be
gated.

Whether a session's agent has hooks is judged from its coding agent where that is known: one whose agent always has
hooks is never told to hold its gate itself, and is never marked, even before its first hook calls; one whose agent
runs with no hooks in some setups is marked until a hook of its calls; one whose agent is not known yet is not marked,
since a tool call reports it soon enough, but is told of its gate in its tools' notices, which costs it nothing.

Kept in Postgres, so every worker agrees (ADR-0013):

- `gate_hooked`: each session a hook of its coding agent has called for, so its edits can be refused. Kept for the
  session's life, since its coding agent stays the same.
- `gate_told_unhooked`: per later and earlier session, that the later session, which no hook reaches, has been told
  its gate waits. Cleared through `Sessions.on_gone` when either session ends or comes back from idle.

What other modules stand on, all of it on `Unhooked`:

- `heard_by_hook(session)`: a hook of this session's coding agent has called.
- `can_be_gated(sessions)`: whether each session's edits can be refused, for the console.
- `notices(caller, session)`: what a later session no hook reaches is told once of its gate.
"""

from __future__ import annotations

from collections.abc import Sequence

from shared_memory.agents import ANOTHER_AGENT, CURSOR, GITHUB_COPILOT
from shared_memory.clock import Clock
from shared_memory.db import Conn, Database
from shared_memory.gates import Gates, refusal
from shared_memory.identity import Caller
from shared_memory.sessions import Session, Sessions

SCHEMA = """
-- A hook of the session's coding agent has called the server: its hook before a tool can refuse a gated edit.
CREATE TABLE IF NOT EXISTS gate_hooked (
    session_id BIGINT PRIMARY KEY REFERENCES sessions(id)
);

-- The later session, which no hook has reached, has been told that its gate waits for the earlier session.
CREATE TABLE IF NOT EXISTS gate_told_unhooked (
    later_session_id BIGINT NOT NULL REFERENCES sessions(id),
    earlier_session_id BIGINT NOT NULL REFERENCES sessions(id),
    PRIMARY KEY (later_session_id, earlier_session_id)
);
"""

# The coding agents, as `agents.agent_named` names them, that run with no hooks in some setups: GitHub Copilot, the
# one name for Copilot in VS Code (no hooks) and Copilot CLI (hooks), and Cursor, whose hooks don't run on Windows.
SOMETIMES_UNHOOKED = frozenset({GITHUB_COPILOT, CURSOR})

# How many sessions a worker remembers a hook was seen for before it starts over, asking the database again.
HOOKED_REMEMBERED = 10_000

# What a later session that no hook reaches is told once, in place of a refusal that nothing can give it.
UNHOOKED_GATED = (
    "[gated] This session's edits on this work wait: another member's session is on nearly the same work. If it is "
    "different work, your member can say so, and calling different_work with this session lifts the gate at once. "
    "This coding agent has no hook to refuse an edit, so it is yours to hold them: edit no file of that work until "
    "the gate lifts."
)


def always_hooked(agent: str | None) -> bool:
    """Whether this coding agent is known to have hooks in every setup."""
    return agent is not None and agent != ANOTHER_AGENT and agent not in SOMETIMES_UNHOOKED


class Unhooked:
    def __init__(self, db: Database, sessions: Sessions, gates: Gates, clock: Clock) -> None:
        self._db = db
        self._gates = gates
        self._clock = clock
        # The sessions this worker has seen a hook for, so a hook's call keeps it with one write at most.
        self._hooked: set[int] = set()
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)
        sessions.on_gone(self._clear)

    @staticmethod
    def _clear(conn: Conn, ids: Sequence[int]) -> None:
        gone = list(ids)
        conn.execute(
            "DELETE FROM gate_told_unhooked WHERE later_session_id = ANY(%s) OR earlier_session_id = ANY(%s)",
            (gone, gone),
        )

    def heard_by_hook(self, session: Session) -> None:
        """A hook of this session's coding agent has called: its hook before a tool can refuse a gated edit."""
        if session.id in self._hooked:
            return
        with self._db.transaction() as conn:
            conn.execute("INSERT INTO gate_hooked (session_id) VALUES (%s) ON CONFLICT DO NOTHING", (session.id,))
        if len(self._hooked) >= HOOKED_REMEMBERED:
            self._hooked.clear()
        self._hooked.add(session.id)

    def _hooked_among(self, ids: Sequence[int]) -> set[int]:
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT session_id FROM gate_hooked WHERE session_id = ANY(%s)", (list(ids),)
            ).fetchall()
        return {row["session_id"] for row in rows}

    def can_be_gated(self, sessions: Sequence[Session]) -> dict[int, bool]:
        """Whether each session's edits can be refused, by its id. One can't be when its coding agent is one that
        runs with no hooks in some setups and no hook of its has called. Any other can, as far as the server knows:
        one whose agent is not known yet is not marked until a tool call has reported it."""
        unsure = [each.id for each in sessions if each.agent in SOMETIMES_UNHOOKED]
        hooked = self._hooked_among(unsure) if unsure else set()
        return {each.id: each.id not in unsure or each.id in hooked for each in sessions}

    def notices(self, caller: Caller, session: Session) -> list[str]:
        """What a later session no hook has reached is told once of the earlier sessions its gate waits for, since no
        refusal can reach it: who, their activity and the time left, with different work first. Nothing for a session
        a hook has reached, or whose coding agent always has hooks, which hears of its gate when an edit is refused."""
        if always_hooked(session.agent):
            return []
        if session.id in self._hooked or self._hooked_among([session.id]):
            self._hooked.add(session.id)
            return []
        waiting = self._gates.waiting(caller, session)
        if not waiting:
            return []
        with self._db.transaction() as conn:
            rows = conn.execute(
                "INSERT INTO gate_told_unhooked (later_session_id, earlier_session_id)"
                " SELECT %s, earlier FROM unnest(%s::bigint[]) AS earlier"
                " ON CONFLICT DO NOTHING RETURNING earlier_session_id",
                (session.id, [each.earlier.id for each in waiting]),
            ).fetchall()
        fresh = {row["earlier_session_id"] for row in rows}
        told = [each for each in waiting if each.earlier.id in fresh]
        return [refusal(told, self._clock(), first=UNHOOKED_GATED)] if told else []
