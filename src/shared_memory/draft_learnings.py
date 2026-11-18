"""Draft learnings (#551, spec #503): what a session's coding agent drafts from what the session learned, for its member
to confirm as personal memory.

The server has no model (ADR-0004), so the coding agent drafts them and the server only keeps them: up to
`Settings.draft_learning_most` waiting for each member in each project. The member confirms each one, which saves it
as their personal memory through `MemoryService.remember`, so a confirmed draft learning gets everything a save gets
(suspected instructions, similar memories, the area's turn); or declines it, which drops it at once.

A draft learning is private to its member: every read is filtered by the member and the project it was drafted in, a
refusal for anyone else's says only that there is none, and no console route, export or audit entry reads this table.
One older than `Settings.draft_learning_days` is filtered out by the clock and deleted as draft learnings are kept or
read, since nothing sweeps (ADR-0018).

Kept in Postgres, so every worker agrees (ADR-0013):

- `draft_learnings`: one row per draft learning: whose and where, the session and moment it was drafted at, the card
  it was drafted for if any, its text and tied files, when it was drafted, and, once confirmed, the memory it became.

What other modules stand on, all of it on `DraftLearnings`:

- `keep(caller, session, sent, card)`: keep a session's draft learnings for its member, refused over the limit with
  the ones already waiting named.
- `confirm(caller, id, edits)`: save one as the member's personal memory; the save's answer.
- `decline(caller, id)`: drop one.
- `ASKING`: what a session that has just sent draft learnings is asked to do with them.
- `asked_for_card(number)`: what a session that has just moved its own card to Done is asked to draft (#552).

Only this module reads the `draft_learnings` table.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timedelta
from typing import Any, Literal, get_args

from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.fence import escape
from shared_memory.identity import Caller
from shared_memory.memory import KNOWN_ISSUE, Memory
from shared_memory.service import MemoryService
from shared_memory.sessions import Session
from shared_memory.validation import validate

SCHEMA = """
CREATE TABLE IF NOT EXISTS draft_learnings (
    id BIGSERIAL PRIMARY KEY,
    member_pk BIGINT NOT NULL REFERENCES members(id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    session_id BIGINT NOT NULL REFERENCES sessions(id),
    -- When the coding agent drafted it: compaction, session_end or card_done.
    moment TEXT NOT NULL,
    -- The card moved to Done that it was drafted for, at the card_done moment.
    card INTEGER,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    type TEXT NOT NULL,
    body TEXT NOT NULL,
    tied_files TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL,
    -- offered until the member confirms it; a declined one is deleted.
    state TEXT NOT NULL DEFAULT 'offered',
    -- The personal memory it was saved as, once confirmed.
    memory_path TEXT
);
CREATE INDEX IF NOT EXISTS draft_learnings_waiting ON draft_learnings (member_pk, project_id, state);
CREATE INDEX IF NOT EXISTS draft_learnings_created ON draft_learnings (created_at);
"""

# When a coding agent drafts learnings: just before context compaction, at session end, or when a card moves to Done.
Moment = Literal["compaction", "session_end", "card_done"]
MOMENTS: tuple[str, ...] = get_args(Moment)

OFFERED = "offered"
CONFIRMED = "confirmed"


@dataclass(frozen=True)
class DraftLearning:
    """A draft learning as a coding agent sends it."""

    moment: Moment
    title: str
    summary: str
    type: str
    body: str
    tied_files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Edits:
    """What a member changed in a draft learning before confirming it; None leaves a field as sent."""

    title: str | None = None
    summary: str | None = None
    type: str | None = None
    body: str | None = None
    tied_files: list[str] | None = None

    def applied_to(self, sent: DraftLearning) -> DraftLearning:
        """The draft learning as sent, with these edits made to it."""
        return replace(sent, **{each.name: value for each in fields(self) if (value := getattr(self, each.name)) is not None})


@dataclass(frozen=True)
class Kept:
    """A draft learning kept for its member."""

    id: int
    title: str
    card: int | None = None


# What a session is asked to do with the draft learnings it just sent: put each to the member.
ASKING = (
    "Show the member each draft learning and ask which to save. confirm_draft_learning(id) saves one as their "
    "personal memory, with edits if they changed it; decline_draft_learning(id) drops it. They stay private to "
    "the member until confirmed."
)


def asked_for_card(number: int) -> str:
    """What a session is asked when it has just moved a card it is the assignee of to Done: finishing the work is when
    its lessons get recorded, while the session still holds them."""
    return (
        f"Card {number} is done. Draft one to three learnings from its work that a teammate would need, none if nothing "
        f"is worth keeping, and send them with draft_learnings, moment card_done and card {number}."
    )


def _over_the_limit(most: int, sending: int, waiting: list[Kept]) -> Refused:
    """Why a call over the limit keeps none, naming the ones waiting so the agent can put them to the member."""
    named = "; ".join(f"{each.id}: {escape(each.title)}" for each in waiting)
    return Refused(
        f"A member has at most {most} draft learnings waiting in a project; this sends {sending} with {len(waiting)} "
        f"already waiting. Waiting, by id: {named}. Ask the member to confirm each (confirm_draft_learning) or decline "
        "it (decline_draft_learning) first, or send fewer."
    )


def _none_waiting(draft_learning: int) -> Refused:
    """One that isn't this member's, isn't in this project, was declined or was dropped: all told alike, so nothing
    says another member has one."""
    return Refused(f"There is no draft learning {draft_learning} waiting for you in this project.")


class DraftLearnings:
    def __init__(self, settings: Settings, db: Database, service: MemoryService, clock: Clock) -> None:
        self._settings = settings
        self._db = db
        self._service = service
        self._clock = clock
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)

    def _drop_old(self, conn: Conn) -> datetime:
        """Delete every draft learning past its days; the oldest moment one may be drafted at and still count."""
        since = self._clock() - timedelta(days=self._settings.draft_learning_days)
        conn.execute("DELETE FROM draft_learnings WHERE created_at <= %s", (since,))
        return since

    def _checked(self, sent: DraftLearning) -> DraftLearning:
        if sent.moment not in MOMENTS:
            raise Refused(f"A draft learning's moment is one of {', '.join(MOMENTS)}; this one is {sent.moment!r}.")
        if sent.type == KNOWN_ISSUE:
            raise Refused("A known issue is not a draft learning: save it with save_known_issue.")
        checked = replace(sent, title=sent.title.strip(), summary=sent.summary.strip())
        validate(_memory(checked, author=""), self._settings.memory_word_limit)
        return checked

    def keep(
        self, caller: Caller, session: Session, sent: Sequence[DraftLearning], card: int | None = None
    ) -> list[Kept]:
        """Keep a session's draft learnings for its member in its project, each refused as a save would refuse it.
        Refused, keeping none, when they and those already waiting would be over the most a member has waiting."""
        checked = [self._checked(each) for each in sent]
        if not checked:
            return []
        most = self._settings.draft_learning_most
        with self._db.transaction() as conn:
            # One member's draft learnings in one project are kept one call at a time, so two can't pass the limit.
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"draft_learnings:{caller.member.pk}:{session.project_id}",),
            )
            since = self._drop_old(conn)
            waiting = [
                Kept(row["id"], row["title"], row["card"])
                for row in conn.execute(
                    "SELECT id, title, card FROM draft_learnings WHERE member_pk = %s AND project_id = %s"
                    " AND state = %s AND created_at > %s ORDER BY id",
                    (caller.member.pk, session.project_id, OFFERED, since),
                ).fetchall()
            ]
            if len(waiting) + len(checked) > most:
                raise _over_the_limit(most, len(checked), waiting)
            now = self._clock()
            kept = []
            for each in checked:
                row = conn.execute(
                    "INSERT INTO draft_learnings (member_pk, project_id, session_id, moment, card, title, summary,"
                    " type, body, tied_files, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    " RETURNING id, card",
                    (
                        caller.member.pk,
                        session.project_id,
                        session.id,
                        each.moment,
                        card,
                        each.title,
                        each.summary,
                        each.type,
                        each.body,
                        list(each.tied_files),
                        now,
                    ),
                ).fetchone()
                assert row is not None
                kept.append(Kept(row["id"], each.title, row["card"]))
        return kept

    def _claim(self, caller: Caller, draft_learning: int) -> DraftLearning:
        """Mark this member's waiting draft learning confirmed, so no other call confirms it too; it as sent."""
        project = caller.require_project()
        with self._db.transaction() as conn:
            since = self._drop_old(conn)
            row = conn.execute(
                "UPDATE draft_learnings SET state = %s WHERE id = %s AND member_pk = %s AND project_id = %s"
                " AND state = %s AND created_at > %s RETURNING moment, title, summary, type, body, tied_files",
                (CONFIRMED, draft_learning, caller.member.pk, project.project_id, OFFERED, since),
            ).fetchone()
            if row is None:
                raise self._unclaimable(conn, caller, project.project_id, draft_learning)
        return DraftLearning(row["moment"], row["title"], row["summary"], row["type"], row["body"], list(row["tied_files"]))

    @staticmethod
    def _unclaimable(conn: Conn, caller: Caller, project_id: str, draft_learning: int) -> Refused:
        """Why this member can't confirm or decline this draft learning: they already confirmed it, or there is none."""
        confirmed = conn.execute(
            "SELECT memory_path FROM draft_learnings WHERE id = %s AND member_pk = %s AND project_id = %s"
            " AND state = %s",
            (draft_learning, caller.member.pk, project_id, CONFIRMED),
        ).fetchone()
        if confirmed is not None:
            saved = f" as {confirmed['memory_path']}" if confirmed["memory_path"] else ""
            return Refused(f"Draft learning {draft_learning} is already confirmed: it was saved{saved}.")
        return _none_waiting(draft_learning)

    def confirm(self, caller: Caller, draft_learning: int, edits: Edits | None = None) -> dict[str, Any]:
        """Save this member's draft learning, as edited, as their personal memory through the normal save, and mark it
        confirmed. The save's answer, naming the draft learning. A save that fails leaves it waiting."""
        sent = self._claim(caller, draft_learning)
        saved = self._save(caller, draft_learning, sent if edits is None else edits.applied_to(sent))
        self._record(draft_learning, saved["path"])
        return {"draft_learning": draft_learning, **saved}

    def _save(self, caller: Caller, draft_learning: int, confirmed: DraftLearning) -> dict[str, Any]:
        """Save a claimed draft learning as the member's personal memory; the save's answer. A save that fails, refused
        or not, gives the claim back, so the draft learning waits to be confirmed again."""
        try:
            return self._service.remember(
                caller, confirmed.title, confirmed.summary, confirmed.type, confirmed.body, confirmed.tied_files
            )
        except Exception:
            self._release(draft_learning)
            raise

    def _release(self, draft_learning: int) -> None:
        """Give back a claim whose save failed: the draft learning waits again."""
        with self._db.transaction() as conn:
            conn.execute("UPDATE draft_learnings SET state = %s WHERE id = %s", (OFFERED, draft_learning))

    def _record(self, draft_learning: int, memory_path: str) -> None:
        """Record the personal memory a confirmed draft learning was saved as."""
        with self._db.transaction() as conn:
            conn.execute("UPDATE draft_learnings SET memory_path = %s WHERE id = %s", (memory_path, draft_learning))

    def decline(self, caller: Caller, draft_learning: int) -> int:
        """Drop this member's waiting draft learning at once."""
        project = caller.require_project()
        with self._db.transaction() as conn:
            since = self._drop_old(conn)
            row = conn.execute(
                "DELETE FROM draft_learnings WHERE id = %s AND member_pk = %s AND project_id = %s AND state = %s"
                " AND created_at > %s RETURNING id",
                (draft_learning, caller.member.pk, project.project_id, OFFERED, since),
            ).fetchone()
            if row is None:
                raise self._unclaimable(conn, caller, project.project_id, draft_learning)
        return draft_learning


def _memory(sent: DraftLearning, author: str) -> Memory:
    return Memory(
        title=sent.title,
        summary=sent.summary,
        type=sent.type,
        author=author,
        body=sent.body,
        tied_files=list(sent.tied_files),
    )
