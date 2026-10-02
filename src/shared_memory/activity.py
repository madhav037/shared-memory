"""A session's activity: its one-line statement of what it is working on, kept while the session is active.

The coding agent states it with `set_activity`, and stating it again replaces it. A session that has stated none shows
the title of its member's most recently claimed card in Doing on the project's board. Activity ends with its session:
`Sessions.on_gone` clears it when the session ends or is found back from idle, and a session that went idle and never
called again is simply not among the active sessions read here.

What other modules stand on, all of it on `Activities`:

- `state(session, activity)`: state or replace the calling session's activity.
- `in_project(project_id)`: the project's active sessions, oldest first, each a `SessionActivity`: the `Session`, its
  activity (None when it stated none and its member has no card in Doing) and whether that activity is a card's title.
- `for_briefing(caller, session)`: those sessions as the briefing lists them, one line each, without the asking one.

Only this module reads the `session_activities` table.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from shared_memory.board import TITLE_LIMIT
from shared_memory.clock import Clock
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller
from shared_memory.sessions import Session, Sessions
from shared_memory.validation import refuse_secret

SCHEMA = """
CREATE TABLE IF NOT EXISTS session_activities (
    session_id BIGINT PRIMARY KEY REFERENCES sessions(id),
    activity TEXT NOT NULL,
    stated_at TIMESTAMPTZ NOT NULL
);
"""

# The longest activity kept, in characters: one line, as long as a card's title may be.
ACTIVITY_LIMIT = TITLE_LIMIT

# What the briefing says of a session that stated no activity and whose member has no card in Doing.
NONE_STATED = "no activity stated"

# The board's answer to which card stands in for an activity: a project and member IDs, to each member's most recently
# claimed card in Doing, by its title. A member with no such card is left out.
DoingCards = Callable[[str, Sequence[str]], dict[str, str]]


@dataclass(frozen=True)
class SessionActivity:
    """One active session with what it is working on."""

    session: Session
    # What it stated, else its member's card in Doing, else None.
    activity: str | None
    # The activity is a card's title, because the session stated none.
    from_card: bool


class UnusableActivity(Refused):
    """An activity the server will not keep: empty, of several lines, or over the limit."""


def _one_line(activity: str) -> str:
    stated = activity.strip()
    if not stated:
        raise UnusableActivity("An activity says what this session is working on, in one line. This one is empty.")
    if "\n" in stated or "\r" in stated:
        raise UnusableActivity("An activity is one line: say what this session is working on in a single sentence.")
    if len(stated) > ACTIVITY_LIMIT:
        raise UnusableActivity(
            f"An activity is at most {ACTIVITY_LIMIT} characters and this one is {len(stated)}. Say what this session "
            "is working on more briefly."
        )
    refuse_secret(stated, "This activity", "into an activity, which every session in the project is shown")
    return stated


def briefing_line(each: SessionActivity) -> str:
    """One active session as a briefing lists it: its member, coding agent, repository and activity."""
    where = ", ".join(part for part in (each.session.agent, each.session.repository) if part)
    named = f"{each.session.member_name} ({where})" if where else each.session.member_name
    return f"- {named}: {each.activity or NONE_STATED}"


class Activities:
    def __init__(self, db: Database, clock: Clock, sessions: Sessions, doing_cards: DoingCards) -> None:
        self._db = db
        self._clock = clock
        self._sessions = sessions
        self._doing_cards = doing_cards
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)
        sessions.on_gone(self._clear)

    @staticmethod
    def _clear(conn: Conn, ids: Sequence[int]) -> None:
        conn.execute("DELETE FROM session_activities WHERE session_id = ANY(%s)", (list(ids),))

    def state(self, session: Session, activity: str) -> str:
        """State the session's activity, in place of any it stated before. Returns it as it is kept."""
        stated = _one_line(activity)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO session_activities (session_id, activity, stated_at) VALUES (%s, %s, %s)"
                " ON CONFLICT (session_id) DO UPDATE SET activity = EXCLUDED.activity, stated_at = EXCLUDED.stated_at",
                (session.id, stated, self._clock()),
            )
        return stated

    def in_project(self, project_id: str) -> list[SessionActivity]:
        """A project's active sessions, oldest first, each with its activity. Whether the asker may reach the project
        is the asker's to check."""
        active = self._sessions.active(project_id)
        if not active:
            return []
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT session_id, activity, stated_at FROM session_activities WHERE session_id = ANY(%s)",
                ([session.id for session in active],),
            ).fetchall()
        # An activity older than its session's start was stated before the session ended and started again.
        started = {session.id: session.started_at for session in active}
        stated = {row["session_id"]: row["activity"] for row in rows if row["stated_at"] >= started[row["session_id"]]}
        without = sorted({session.member_id for session in active if session.id not in stated})
        cards = self._doing_cards(project_id, without) if without else {}
        return [
            SessionActivity(session, stated[session.id], False)
            if session.id in stated
            else SessionActivity(session, cards.get(session.member_id), session.member_id in cards)
            for session in active
        ]

    def of(self, session: Session) -> str | None:
        """One session's activity, as `in_project` gives it: None when it has none, or is no longer active."""
        mine = (each.activity for each in self.in_project(session.project_id) if each.session.id == session.id)
        return next(mine, None)

    def for_briefing(self, caller: Caller, session: Session | None) -> list[str]:
        """The other active sessions in the caller's project as its briefing lists them, one line each, oldest first.
        The asking session's own line is left out. Nothing for a session outside a project, or in a project the member
        can't reach."""
        if caller.project is None or caller.project.project_id in caller.unreachable:
            return []
        return [
            briefing_line(each)
            for each in self.in_project(caller.project.project_id)
            if session is None or each.session.id != session.id
        ]
