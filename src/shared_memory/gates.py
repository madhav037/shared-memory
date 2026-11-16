"""The gate (ADR-0024): a later session's file edits on colliding work are refused until the project's wait has passed
since the collision was found, or its member says it is different work.

A gate is worked out from what `Collisions.of` keeps, one collision per pair of sessions with which is later, and from
the clock, on every read, with no background job (ADR-0018). A later session is gated by each earlier session that is
still active, belongs to another member, and whose collision was found less than the project's wait ago, unless the
later member said it is different work. An earlier session that ends or goes idle gates nobody; a member's own
sessions never gate each other. Reading, searching and planning go ahead: only the before-edit hook asks.

Kept in Postgres, so every worker agrees (ADR-0013):

- `gate_ends`: per later and earlier session, how the gate between them ended (`different_work` or `timed_out`), and
  whether the earlier session has been told. A timeout is kept the first time a read finds the wait passed, which is
  when it is written to the audit log. Cleared through `Sessions.on_gone` when either session ends or comes back from
  idle, as the collision is.
- `project_waits`: a project's own wait, in minutes, set by its leads and the team's admins. A project without one
  waits `Settings.gate_wait_minutes`.

What other modules stand on, all of it on `Gates`:

- `before_edit(caller, session, paths)`: why the before-edit hook refuses an edit of these files, or None. Its first
  line always offers different work, since a wrong collision now stops real work.
- `different_work(caller, session)`: lift this session's gate at once; the names of the members it was waiting for.
- `waiting_notices(session)`: what an earlier session is told once: how each gate on its work ended.
- `wait(project_id)` and `set_wait(caller, minutes)`: the project's wait.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from shared_memory.activity import Activities
from shared_memory.audit import DIFFERENT_WORK, GATE_TIMED_OUT, PROJECT_WAIT_CHANGED, Audit, Kind
from shared_memory.clock import Clock
from shared_memory.collisions import Collision, Collisions
from shared_memory.config import Settings
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity
from shared_memory.sessions import Session, Sessions

SCHEMA = """
CREATE TABLE IF NOT EXISTS gate_ends (
    later_session_id BIGINT NOT NULL REFERENCES sessions(id),
    earlier_session_id BIGINT NOT NULL REFERENCES sessions(id),
    ended_by TEXT NOT NULL CHECK (ended_by IN ('different_work', 'timed_out')),
    ended_at TIMESTAMPTZ NOT NULL,
    -- The earlier session has been told how the gate ended.
    told BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (later_session_id, earlier_session_id)
);
CREATE INDEX IF NOT EXISTS gate_ends_earlier ON gate_ends (earlier_session_id) WHERE NOT told;

CREATE TABLE IF NOT EXISTS project_waits (
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id),
    minutes INTEGER NOT NULL,
    changed_by TEXT NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL
);
"""

# The longest wait a project may set: a day, longer than any session stays active without a call.
WAIT_LIMIT_MINUTES = 24 * 60

DIFFERENT = "different_work"
TIMED_OUT = "timed_out"

_AUDITED: dict[str, Kind] = {DIFFERENT: DIFFERENT_WORK, TIMED_OUT: GATE_TIMED_OUT}


@dataclass(frozen=True)
class Waiting:
    """One earlier session a later session's gate waits for."""

    earlier: Session
    activity: str | None
    collision: Collision
    until: datetime


def _left(now: datetime, until: datetime) -> str:
    minutes = math.ceil((until - now).total_seconds() / 60)
    return "less than a minute left" if minutes < 1 else f"{minutes} minute{'s' if minutes != 1 else ''} left"


def refusal(waiting: Sequence[Waiting], now: datetime) -> str:
    """Why a gated session's edit is refused: different work first, then who it waits for and how long."""
    lines = [
        "[gated] This edit waits: another member's session is on nearly the same work. If it is different work, "
        "your member can say so, and calling different_work with this session lifts the gate at once.",
    ]
    for each in waiting:
        who = each.earlier
        agent = who.agent or "a coding agent that has not said which it is"
        activity = f'working on "{each.activity}"' if each.activity else "with no activity stated"
        lines.append(
            f"- {who.member_name} ({who.member_id}) in {agent}, {activity}: {_left(now, each.until)} of the "
            f"project's wait (until {each.until.isoformat()})."
        )
    lines.append(
        "Don't edit, and don't decide alone: stop and ask your member whether to wait (reading, searching and "
        "planning still work), to say it is different work, or to pick something else. When the wait has passed, "
        "the edit goes ahead."
    )
    return "\n".join(lines)


def _ended(by: str, row_name: str, minutes: int) -> str:
    if by == DIFFERENT:
        return (
            f"[gate] {row_name}'s session, gated on nearly the same work as this one, said it is different work and "
            "goes ahead. Tell your member."
        )
    return (
        f"[gate] {row_name}'s session, gated on nearly the same work as this one, waited the project's wait "
        f"({minutes} minutes) with no answer and goes ahead. Tell your member."
    )


class Gates:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        identity: Identity,
        sessions: Sessions,
        activities: Activities,
        collisions: Collisions,
        audit: Audit,
        clock: Clock,
    ) -> None:
        self._default_wait = round(settings.gate_wait_minutes)
        self._db = db
        self._identity = identity
        self._activities = activities
        self._collisions = collisions
        self._audit = audit
        self._clock = clock
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)
        sessions.on_gone(self._clear)

    @staticmethod
    def _clear(conn: Conn, ids: Sequence[int]) -> None:
        gone = list(ids)
        conn.execute(
            "DELETE FROM gate_ends WHERE later_session_id = ANY(%s) OR earlier_session_id = ANY(%s)", (gone, gone)
        )

    # The project's wait

    def wait(self, project_id: str) -> int:
        """The project's wait in minutes: its own, or the server's default."""
        with self._db.transaction() as conn:
            row = conn.execute("SELECT minutes FROM project_waits WHERE project_id = %s", (project_id,)).fetchone()
        return int(row["minutes"]) if row else self._default_wait

    def set_wait(self, caller: Caller, minutes: int) -> int:
        """Set the caller's project's wait: for its leads and the team's admins."""
        project_id = caller.require_project().project_id
        if not self._identity.looks_after(caller.member, project_id):
            raise Refused(
                "Only this project's leads and the team's admins can change its wait. Any member of the project can "
                "read it, by calling project_wait with nothing."
            )
        if not 1 <= minutes <= WAIT_LIMIT_MINUTES:
            raise Refused(f"The wait is a whole number of minutes from 1 to {WAIT_LIMIT_MINUTES}.")
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO project_waits (project_id, minutes, changed_by, changed_at) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (project_id) DO UPDATE SET minutes = EXCLUDED.minutes,"
                " changed_by = EXCLUDED.changed_by, changed_at = EXCLUDED.changed_at",
                (project_id, minutes, caller.member_id, self._clock()),
            )
        self._audit.record(
            PROJECT_WAIT_CHANGED, member=caller.member, project_id=project_id, detail={"minutes": minutes}
        )
        return minutes

    # The gate

    def _waiting(self, caller: Caller, session: Session) -> list[Waiting]:
        """The earlier sessions this session's gate waits for now. A pair whose wait has just been found passed is
        kept as timed out, and written to the audit log once."""
        mine = [each for each in self._collisions.of(session) if each.later_session_id == session.id]
        if not mine:
            return []
        active = {each.session.id: each for each in self._activities.in_project(session.project_id)}
        others = [
            each
            for each in mine
            if each.earlier_session_id in active and active[each.earlier_session_id].session.member_id != session.member_id
        ]
        if not others:
            return []
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT earlier_session_id FROM gate_ends WHERE later_session_id = %s", (session.id,)
            ).fetchall()
        ended = {row["earlier_session_id"] for row in rows}
        now = self._clock()
        wait = timedelta(minutes=self.wait(session.project_id))
        waiting = []
        for each in others:
            if each.earlier_session_id in ended:
                continue
            earlier = active[each.earlier_session_id]
            until = each.found_at + wait
            if now >= until:
                self._end(caller, session, earlier.session, each, TIMED_OUT)
            else:
                waiting.append(Waiting(earlier.session, earlier.activity, each, until))
        return waiting

    def _end(self, caller: Caller, later: Session, earlier: Session, collision: Collision, by: str) -> bool:
        """Keep how the gate between these two sessions ended, and write it to the audit log, unless another call
        already did."""
        with self._db.transaction() as conn:
            kept = conn.execute(
                "INSERT INTO gate_ends (later_session_id, earlier_session_id, ended_by, ended_at)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING later_session_id",
                (later.id, earlier.id, by, self._clock()),
            ).fetchone()
        if kept is None:
            return False
        self._audit.record(
            _AUDITED[by],
            member=caller.member,
            project_id=later.project_id,
            target=earlier.member_id,
            detail={"earlier": earlier.member_id, "score": round(collision.score, 4), "cause": collision.cause.value},
        )
        return True

    def before_edit(self, caller: Caller, session: Session, paths: Sequence[str]) -> str | None:
        """Why the before-edit hook refuses this session's edit of these files, or None to let the gate pass it. A
        tool that names no file is not an edit, and is never gated."""
        if not paths:
            return None
        waiting = self._waiting(caller, session)
        return refusal(waiting, self._clock()) if waiting else None

    def different_work(self, caller: Caller, session: Session) -> list[str]:
        """Lift this session's gate at once: its member says it is different work. The names of the members it was
        waiting for, each recorded in the audit log with the collision's score."""
        lifted = []
        for each in self._waiting(caller, session):
            if self._end(caller, session, each.earlier, each.collision, DIFFERENT):
                lifted.append(each.earlier.member_name)
        return lifted

    def waiting_notices(self, session: Session) -> list[str]:
        """What an earlier session is told once: how each gate a later session had on its work ended. Asking marks it
        told."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "UPDATE gate_ends SET told = TRUE WHERE earlier_session_id = %s AND NOT told"
                " RETURNING later_session_id, ended_by",
                (session.id,),
            ).fetchall()
        if not rows:
            return []
        later = {each.session.id: each.session for each in self._activities.in_project(session.project_id)}
        minutes = self.wait(session.project_id)
        return [
            _ended(row["ended_by"], later[row["later_session_id"]].member_name, minutes)
            for row in rows
            if row["later_session_id"] in later
        ]
