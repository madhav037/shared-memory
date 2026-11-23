"""The sessions the server knows: each running conversation of a member's coding agent in one project (ADR-0018).

A session is told apart by the identifier its coding agent's hooks send, kept per member and project. It is active
from its first call until its session-end hook, or until it has made no call for the idle time. Active is worked out
from the clock on every read: nothing sweeps, so every worker agrees (ADR-0013).

What other modules stand on, all of it on `Sessions`:

- `touch(caller, identifier)`: the calling session, from a hook or from a tool that takes `session`. It starts a
  session the server doesn't know, moves a known one's last-seen time, and brings back one that ended or went idle.
- `start(caller)`: a session under an identifier made here, for an agent that was never told one.
- `end(caller, identifier)`: the session-end hook.
- `active(project_id)`: a project's active sessions, oldest first.
- `lately(project_id, within)`: a project's active sessions and those that ended or went idle no longer ago than
  `within`, for a module that reaches a session gone a little while, such as a message waiting for its member.
- `ended_among(conn, ids)`: which of these sessions have ended, each with where it was, for a module that keeps
  something of a session past its end, such as its handoff note, from inside an `on_gone` listener.
- `still_active(ids)`: which of these sessions are active, for a module that keeps something per session and must
  count an ended or idle session's as gone wherever it reads it.
- `on_gone(listener)`: called, inside the transaction, with the sessions that just ended or were found back from
  idle, so a module clears what it kept for them. A session that goes idle and never calls again is never reported:
  `still_active` is what says it is gone.
- `waiting_notices(session)`: what a session is told once: that it is back from idle, or back after it had ended.
- `report(session, branch, files)`: where a session is, from its hook before a tool: its git branch and the files
  that tool named, kept beside the session as the files it touched (ADR-0025).
- `keep_utc_offset(session, minutes)`: the UTC offset its session-start hook reported, kept as
  `Session.utc_offset_minutes` for the warnings' clock times when its member has no time zone (#592).
- `mute(session, on)`: mute or unmute a session; `Session.muted` says which it is (#514).
- `idle_after`: the idle time, from `Settings.session_idle_minutes`.

A module keeping rows per session refers to `Session.id`. Only this module reads the `sessions` table, and it reads
members and projects through `Identity`.
"""

from __future__ import annotations

import dataclasses
import secrets
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id BIGSERIAL PRIMARY KEY,
    member_id BIGINT NOT NULL REFERENCES members(id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    -- What the session's coding agent sends in its hook payloads, or what `briefing` made up for it.
    identifier TEXT NOT NULL,
    repository TEXT,
    agent TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    -- It called again after going idle and has not yet been told that its activity and locks ended.
    back_from_idle BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (member_id, project_id, identifier)
);

-- It called again after it had ended and has not yet been told that its activity and locks ended.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS back_from_end BOOLEAN NOT NULL DEFAULT FALSE;

-- Where the session is, from its hook before each tool: its git branch, and the files its tools named, the most
-- recent first. Both start over when the session comes back from idle or after it had ended. Never the tool's name.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS branch TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS touched_files TEXT[] NOT NULL DEFAULT '{}';

-- Muted (#514): its messages that are not urgent wait for its next prompt or its unmute. A session back from idle
-- or after it had ended starts unmuted.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS muted BOOLEAN NOT NULL DEFAULT FALSE;

-- The UTC offset, in minutes east of UTC, its session-start hook last reported from its machine's clock (#592), or
-- NULL while none has. It outlasts an idle spell or an end: the machine's clock has not moved.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS utc_offset_minutes INTEGER;

CREATE INDEX IF NOT EXISTS sessions_not_ended ON sessions (project_id, last_seen_at) WHERE ended_at IS NULL;
-- A project's sessions by when they were last seen, ended or not, for those gone a little while.
CREATE INDEX IF NOT EXISTS sessions_by_project ON sessions (project_id, last_seen_at);
"""

# The longest identifier kept. Coding agents send a UUID or something as short.
IDENTIFIER_LIMIT = 100

# How many sessions one member keeps going in one project. A new one past it ends the one seen longest ago, so an agent
# that names a new session on every call can't fill the project with them.
SESSION_LIMIT = 50

# How many of the files a session touched are kept, the most recent first, and the longest path kept among them.
TOUCHED_KEPT = 20
TOUCHED_PATH_LIMIT = 500

BACK_FROM_IDLE = (
    "[session] This session made no call to Shared Memory for longer than a session may sit idle, so its activity "
    "and locks ended. State its activity again, and take a file's lock again before editing it: another session may "
    "hold it now."
)

BACK_FROM_END = (
    "[session] This session ended and has now started again, so its activity and locks ended. State its activity "
    "again, and take a file's lock again before editing it: another session may hold it now."
)

# Called inside the transaction that found these sessions gone, with their ids.
Gone = Callable[[Conn, Sequence[int]], None]


@dataclass(frozen=True)
class Session:
    """One session as the server knows it."""

    # What another module's rows refer to.
    id: int
    identifier: str
    member_id: str
    member_name: str
    project_id: str
    repository: str | None
    # The coding agent it runs in, once a tool call has reported it or a hook has said which it came from.
    agent: str | None
    started_at: datetime
    last_seen_at: datetime
    # Its git branch as its hooks last said, and the files its tools named, the most recent first (ADR-0025).
    branch: str | None = None
    touched_files: tuple[str, ...] = ()
    # Its messages that are not urgent wait for its next prompt or its unmute (#514).
    muted: bool = False
    # The UTC offset, in minutes east of UTC, its session-start hook last reported, or None while none has (#592).
    utc_offset_minutes: int | None = None


@dataclass(frozen=True)
class Whereabouts:
    """Where an ended session was: its project, its git branch and the files it touched, the most recent first."""

    project_id: str
    branch: str | None
    touched_files: tuple[str, ...]
    ended_at: datetime


class UnusableIdentifier(Refused):
    """A session identifier the server will not keep."""


def usable(identifier: object) -> str | None:
    """A session identifier as it is kept, or None for one that can't be: not text, empty or too long."""
    if not isinstance(identifier, str):
        return None
    cleaned = identifier.strip()
    return cleaned if cleaned and len(cleaned) <= IDENTIFIER_LIMIT else None


def briefing_line(session: Session) -> str:
    """What tells a coding agent its session's identifier, with its briefing, and the repository it works in: an agent
    has no other way to learn the name its files are written under (repository:path)."""
    named = (
        f"This session's identifier in Shared Memory is `{session.identifier}`. Pass it as `session` to the Shared "
        "Memory tools that take one."
    )
    if not session.repository:
        return named
    return (
        f"{named} It works in the repository `{session.repository}`: write a file in it as `{session.repository}:` "
        f"and its path from the repository's root, for example `{session.repository}:package.json`."
    )


class Sessions:
    def __init__(self, settings: Settings, db: Database, identity: Identity, clock: Clock) -> None:
        self._db = db
        self._identity = identity
        self._clock = clock
        self.idle_after = timedelta(minutes=settings.session_idle_minutes)
        self._gone: list[Gone] = []
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)

    def on_gone(self, listener: Gone) -> None:
        """Have a module told when sessions end or are found back from idle. A session may be reported twice (back
        from idle, then ended), so a listener clears what it finds and expects nothing."""
        self._gone.append(listener)

    def _tell_gone(self, conn: Conn, ids: Sequence[int]) -> None:
        if ids:
            for listener in self._gone:
                listener(conn, ids)

    def start(self, caller: Caller) -> Session:
        """Start a session under an identifier made here, for a coding agent whose hooks told it none."""
        return self.touch(caller, secrets.token_hex(8))

    def touch(self, caller: Caller, identifier: str, hooked_by: str | None = None) -> Session:
        """The calling session, seen now: started if the server doesn't know it, active again if it had ended or gone
        idle. One back from idle, or back after it had ended, has lost its activity and locks, and is told so once
        (`waiting_notices`). `hooked_by` is the coding agent a hook says it runs in, kept only for a session whose
        agent no tool call has reported: the caller's own agent, which a tool call reports, replaces it."""
        project = caller.require_project()
        kept = usable(identifier)
        if kept is None:
            raise UnusableIdentifier(
                f"A session identifier is 1-{IDENTIFIER_LIMIT} characters. Pass as `session` the identifier this "
                "session's briefing named, or call briefing without one to be given one."
            )
        now = self._clock()
        key = (caller.member.pk, project.project_id, kept)
        with self._db.transaction() as conn:
            row = conn.execute(
                "INSERT INTO sessions (member_id, project_id, identifier, repository, agent, started_at, last_seen_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (member_id, project_id, identifier) DO NOTHING"
                " RETURNING id, repository, agent, started_at, branch, touched_files, muted,"
                " utc_offset_minutes",
                (*key, caller.repository, caller.agent or hooked_by, now, now),
            ).fetchone()
            # A session new or back from its end is one more going: past the limit, the one seen longest ago ends.
            going_again = row is not None
            if row is None:
                known = conn.execute(
                    "SELECT id, last_seen_at, ended_at FROM sessions"
                    " WHERE member_id = %s AND project_id = %s AND identifier = %s FOR UPDATE",
                    key,
                ).fetchone()
                assert known is not None
                ended = known["ended_at"] is not None
                idle = not ended and now - known["last_seen_at"] >= self.idle_after
                if idle:
                    self._tell_gone(conn, [known["id"]])
                row = conn.execute(
                    "UPDATE sessions SET last_seen_at = %s, ended_at = NULL,"
                    " started_at = CASE WHEN %s THEN %s ELSE started_at END,"
                    " back_from_idle = (back_from_idle OR %s) AND NOT %s, back_from_end = back_from_end OR %s,"
                    " repository = COALESCE(%s, repository), agent = COALESCE(%s, agent, %s),"
                    " branch = CASE WHEN %s THEN NULL ELSE branch END,"
                    " touched_files = CASE WHEN %s THEN '{}' ELSE touched_files END,"
                    " muted = muted AND NOT %s"
                    " WHERE id = %s RETURNING id, repository, agent, started_at, branch, touched_files, muted,"
                " utc_offset_minutes",
                    (
                        now, ended, now, idle, ended, ended, caller.repository, caller.agent, hooked_by,
                        idle or ended, idle or ended, idle or ended, known["id"],
                    ),  # fmt: skip
                ).fetchone()
                assert row is not None
                going_again = ended
            if going_again:
                crowded = conn.execute(
                    "UPDATE sessions SET ended_at = %s, back_from_idle = FALSE WHERE id IN (SELECT id FROM sessions"
                    " WHERE member_id = %s AND project_id = %s AND ended_at IS NULL AND id <> %s"
                    " ORDER BY last_seen_at DESC, id DESC OFFSET %s) RETURNING id",
                    (now, caller.member.pk, project.project_id, row["id"], SESSION_LIMIT - 1),
                ).fetchall()
                self._tell_gone(conn, [each["id"] for each in crowded])
        return Session(
            id=row["id"],
            identifier=kept,
            member_id=caller.member_id,
            member_name=caller.member.name,
            project_id=project.project_id,
            repository=row["repository"],
            agent=row["agent"],
            started_at=row["started_at"],
            last_seen_at=now,
            branch=row["branch"],
            touched_files=tuple(row["touched_files"]),
            muted=row["muted"],
            utc_offset_minutes=row["utc_offset_minutes"],
        )

    def keep_utc_offset(self, session: Session, minutes: int) -> Session:
        """Keep the UTC offset this session's session-start hook reported, in minutes east of UTC: the fallback for
        the clock times in its warnings while its member has no time zone. The session as it now is."""
        if minutes == session.utc_offset_minutes:
            return session
        with self._db.transaction() as conn:
            conn.execute("UPDATE sessions SET utc_offset_minutes = %s WHERE id = %s", (minutes, session.id))
        return dataclasses.replace(session, utc_offset_minutes=minutes)

    def mute(self, session: Session, on: bool) -> Session:
        """Mute this session, or unmute it: while muted, its messages that are not urgent wait for its next prompt or
        its unmute. The session as it now is."""
        with self._db.transaction() as conn:
            conn.execute("UPDATE sessions SET muted = %s WHERE id = %s", (on, session.id))
        return dataclasses.replace(session, muted=on)

    def report(self, session: Session, branch: str | None, files: Sequence[str]) -> None:
        """Keep where this session is, as its hook before a tool says: its branch, where the hook named one, and the
        files the tool named, ahead of those it touched before. Nothing is written when nothing changes."""
        touched = [file for file in dict.fromkeys(files) if len(file) <= TOUCHED_PATH_LIMIT][:TOUCHED_KEPT]
        kept = list(dict.fromkeys([*touched, *session.touched_files]))[:TOUCHED_KEPT]
        moved = branch is not None and branch != session.branch
        if not moved and kept == list(session.touched_files):
            return
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE sessions SET branch = COALESCE(%s, branch), touched_files = %s WHERE id = %s",
                (branch, kept, session.id),
            )

    def end(self, caller: Caller, identifier: str) -> None:
        """End the calling session, as its session-end hook asks. One the server doesn't know, or that has already
        ended, is left as it is."""
        project = caller.require_project()
        with self._db.transaction() as conn:
            rows = conn.execute(
                "UPDATE sessions SET ended_at = %s, back_from_idle = FALSE"
                " WHERE member_id = %s AND project_id = %s AND identifier = %s AND ended_at IS NULL RETURNING id",
                (self._clock(), caller.member.pk, project.project_id, identifier.strip()),
            ).fetchall()
            self._tell_gone(conn, [row["id"] for row in rows])

    def active(self, project_id: str) -> list[Session]:
        """A project's active sessions, oldest first. Whether the asker may reach the project is the asker's to
        check."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT id, identifier, member_id, project_id, repository, agent, started_at, last_seen_at, branch,"
                " touched_files, muted, utc_offset_minutes FROM sessions"
                " WHERE project_id = %s AND ended_at IS NULL AND last_seen_at > %s ORDER BY started_at, id",
                (project_id, self._clock() - self.idle_after),
            ).fetchall()
        members = self._identity.named(row["member_id"] for row in rows)
        return [_session(row, *members[row["member_id"]]) for row in rows]

    def lately(self, project_id: str, within: timedelta) -> list[tuple[Session, bool]]:
        """A project's sessions that are active, or that ended or went idle no longer than `within` ago, the most
        recently seen first, each with whether it is active now. An idle session went idle at its last call plus the
        idle time."""
        now = self._clock()
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT id, identifier, member_id, project_id, repository, agent, started_at, last_seen_at, branch,"
                " touched_files, muted, utc_offset_minutes, (ended_at IS NULL AND last_seen_at > %s) AS active FROM sessions"
                " WHERE project_id = %s AND last_seen_at > %s AND COALESCE(ended_at, last_seen_at + %s) > %s"
                " ORDER BY last_seen_at DESC, id DESC",
                (now - self.idle_after, project_id, now - within - self.idle_after, self.idle_after, now - within),
            ).fetchall()
        members = self._identity.named(row["member_id"] for row in rows)
        return [(_session(row, *members[row["member_id"]]), bool(row["active"])) for row in rows]

    def ended_among(self, conn: Conn, ids: Iterable[int]) -> dict[int, Whereabouts]:
        """Which of these sessions have ended, each with where it was, read in a transaction already open. A session
        reported gone because it came back from idle has not ended."""
        rows = conn.execute(
            "SELECT id, project_id, branch, touched_files, ended_at FROM sessions"
            " WHERE id = ANY(%s) AND ended_at IS NOT NULL",
            (list(ids),),
        ).fetchall()
        return {
            row["id"]: Whereabouts(row["project_id"], row["branch"], tuple(row["touched_files"]), row["ended_at"])
            for row in rows
        }

    def still_active(self, ids: Iterable[int], conn: Conn | None = None) -> set[int]:
        """Which of these sessions are active now. Pass the connection of a transaction already open to ask within
        it."""
        asked = list(ids)
        if not asked:
            return set()
        query = "SELECT id FROM sessions WHERE id = ANY(%s) AND ended_at IS NULL AND last_seen_at > %s"
        values = (asked, self._clock() - self.idle_after)
        if conn is not None:
            return {row["id"] for row in conn.execute(query, values).fetchall()}
        with self._db.transaction() as own:
            return {row["id"] for row in own.execute(query, values).fetchall()}

    def waiting_notices(self, session: Session) -> list[str]:
        """What this session is told once, with its next prompt or the answer of its next tool call: that it is back
        from idle, or back after it had ended, so its activity and locks ended. Asking marks it told."""
        with self._db.transaction() as conn:
            told = conn.execute(
                "WITH was AS (SELECT id, back_from_end FROM sessions"
                " WHERE id = %s AND (back_from_idle OR back_from_end) FOR UPDATE)"
                " UPDATE sessions s SET back_from_idle = FALSE, back_from_end = FALSE FROM was WHERE s.id = was.id"
                " RETURNING was.back_from_end",
                (session.id,),
            ).fetchone()
        if told is None:
            return []
        return [BACK_FROM_END if told["back_from_end"] else BACK_FROM_IDLE]

    def end_unreachable(self, conn: Conn, caller: Caller) -> Callable[[], None]:
        """End every session whose member can no longer reach its project: removed from the company, or shut out of a
        restricted project. Identity calls this inside the transaction of any change that may have cost a member a
        project (`Identity.on_access_lost`), so the change and the sessions' end happen together or not at all."""
        company_pk = caller.member.company_pk
        # Only the not-ended sessions of this company's projects, which the not-ended index finds by project.
        open_pairs = conn.execute(
            "SELECT DISTINCT member_id, project_id FROM sessions WHERE ended_at IS NULL AND project_id = ANY(%s)",
            (self._identity.company_projects(conn, company_pk),),
        ).fetchall()
        lost = self._identity.cannot_reach(conn, company_pk, [(row["member_id"], row["project_id"]) for row in open_pairs])
        if not lost:
            return lambda: None
        rows = conn.execute(
            "UPDATE sessions s SET ended_at = %s, back_from_idle = FALSE"
            " FROM unnest(%s::bigint[], %s::text[]) AS x(member_id, project_id)"
            " WHERE s.member_id = x.member_id AND s.project_id = x.project_id AND s.ended_at IS NULL RETURNING s.id",
            (self._clock(), [pk for pk, _ in lost], [project_id for _, project_id in lost]),
        ).fetchall()
        self._tell_gone(conn, [row["id"] for row in rows])
        return lambda: None


def _session(row: dict[str, Any], member_id: str, member_name: str) -> Session:
    return Session(
        id=row["id"],
        identifier=row["identifier"],
        member_id=member_id,
        member_name=member_name,
        project_id=row["project_id"],
        repository=row["repository"],
        agent=row["agent"],
        started_at=row["started_at"],
        last_seen_at=row["last_seen_at"],
        branch=row["branch"],
        touched_files=tuple(row["touched_files"]),
        muted=row["muted"],
        utc_offset_minutes=row["utc_offset_minutes"],
    )
