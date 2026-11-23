"""The audit log: who changed what, and when.

It answers "who did this" for changes that leave no memory file behind — signing in, members, roles, access, tokens and a project's never-lock patterns —
alongside the memory changes themselves. It is append-only and holds no memory content: it points at paths, and the
memory folder's git history holds what they said.

A sign-in that no member can be found for belongs to no company; those entries are shown to every company's readers, because a
server holds one company in practice and nobody else could otherwise see that someone tried.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from psycopg.types.json import Jsonb

from shared_memory.clock import Clock
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity, Member, project_in

#: Every kind of change the server records. The constants below are annotated with it, so mypy refuses a new
#: one that is not named here, and the console's contract offers the same list to `npm run api:check`.
Kind = Literal[
    "signed_in",
    "sign_in_refused",
    "token_issued",
    "member_added",
    "member_removed",
    "member_changed",
    "admin_granted",
    "admin_revoked",
    "ownership_handed_over",
    "project_created",
    "project_renamed",
    "lead_appointed",
    "lead_removed",
    "keeper_assigned",
    "keeper_removed",
    "foundation_added",
    "foundation_removed",
    "repository_added",
    "repository_removed",
    "project_restricted",
    "project_opened",
    "access_granted",
    "access_revoked",
    "memory_saved",
    "memory_edited",
    "memory_deleted",
    "memory_promoted",
    "memory_superseded",
    "memory_retired",
    "memory_pinned",
    "memory_unpinned",
    "challenge_raised",
    "challenge_decided",
    "card_added",
    "card_edited",
    "card_moved",
    "card_claimed",
    "card_commented",
    "card_deleted",
    "card_returned",
    "never_lock_pattern_added",
    "never_lock_pattern_removed",
    "rate_limits_changed",
    "license_installed",
    "token_limited",
    "team_exported",
    "gate_timed_out",
    "different_work",
    "project_wait_changed",
    "gate_agreed",
    "gate_refused",
    "urgent_message",
    "department_created",
    "department_renamed",
    "department_removed",
    "department_lead_appointed",
    "department_lead_removed",
    "project_moved",
    "department_restricted",
    "department_opened",
    "department_access_granted",
    "department_access_revoked",
]

SIGNED_IN: Kind = "signed_in"
SIGN_IN_REFUSED: Kind = "sign_in_refused"
TOKEN_ISSUED: Kind = "token_issued"  # noqa: S105  # a name, not a secret
MEMBER_ADDED: Kind = "member_added"
MEMBER_REMOVED: Kind = "member_removed"
MEMBER_CHANGED: Kind = "member_changed"
ADMIN_GRANTED: Kind = "admin_granted"
ADMIN_REVOKED: Kind = "admin_revoked"
OWNERSHIP_HANDED_OVER: Kind = "ownership_handed_over"
PROJECT_CREATED: Kind = "project_created"
PROJECT_RENAMED: Kind = "project_renamed"
LEAD_APPOINTED: Kind = "lead_appointed"
LEAD_REMOVED: Kind = "lead_removed"
# A foundation's keeper; the entry's target is the member. A keeper dropped for losing the project is a removal too.
KEEPER_ASSIGNED: Kind = "keeper_assigned"
KEEPER_REMOVED: Kind = "keeper_removed"
# An extra foundation of a project; the entry's target is its slug.
FOUNDATION_ADDED: Kind = "foundation_added"
FOUNDATION_REMOVED: Kind = "foundation_removed"
REPOSITORY_ADDED: Kind = "repository_added"
REPOSITORY_REMOVED: Kind = "repository_removed"
PROJECT_RESTRICTED: Kind = "project_restricted"
PROJECT_OPENED: Kind = "project_opened"
ACCESS_GRANTED: Kind = "access_granted"
ACCESS_REVOKED: Kind = "access_revoked"
MEMORY_SAVED: Kind = "memory_saved"
MEMORY_EDITED: Kind = "memory_edited"
MEMORY_DELETED: Kind = "memory_deleted"
MEMORY_PROMOTED: Kind = "memory_promoted"
MEMORY_SUPERSEDED: Kind = "memory_superseded"
MEMORY_RETIRED: Kind = "memory_retired"
MEMORY_PINNED: Kind = "memory_pinned"
MEMORY_UNPINNED: Kind = "memory_unpinned"
CHALLENGE_RAISED: Kind = "challenge_raised"
CHALLENGE_DECIDED: Kind = "challenge_decided"
CARD_ADDED: Kind = "card_added"
CARD_EDITED: Kind = "card_edited"
CARD_MOVED: Kind = "card_moved"
CARD_CLAIMED: Kind = "card_claimed"
CARD_COMMENTED: Kind = "card_commented"
CARD_DELETED: Kind = "card_deleted"
# A card whose assignee lost the project, put back in To do with no assignee.
CARD_RETURNED: Kind = "card_returned"
# A project's own never-lock pattern; the entry's target is the pattern.
NEVER_LOCK_PATTERN_ADDED: Kind = "never_lock_pattern_added"
NEVER_LOCK_PATTERN_REMOVED: Kind = "never_lock_pattern_removed"
# An admin changed the server's rate limit; the entry's detail holds the limits now and the limits before.
RATE_LIMITS_CHANGED: Kind = "rate_limits_changed"
# An admin installed a license key; the entry's detail holds the company, member cap, expiry and key ID (never the key).
LICENSE_INSTALLED: Kind = "license_installed"
# A personal token was limited, at most once an hour; the entry's target is its member.
TOKEN_LIMITED: Kind = "token_limited"  # noqa: S105  # a name, not a secret
# An admin downloaded all of the company's data (spec #409); the entry's detail holds the archive's size in bytes.
COMPANY_EXPORTED: Kind = "team_exported"
# A later session's gate ended (ADR-0024): its wait passed with no answer, or its member said it is different work. The
# entry's actor is the later session's member, its target the earlier one's, and its detail holds the collision's score
# and cause, never a prompt.
GATE_TIMED_OUT: Kind = "gate_timed_out"
DIFFERENT_WORK: Kind = "different_work"
# An earlier session's member agreed to or refused a later session's gate on its work (#512). The entry's actor is the
# earlier session's member, its target the later one's, and its detail holds the collision's score and cause, never
# the answer's text.
GATE_AGREED: Kind = "gate_agreed"
GATE_REFUSED: Kind = "gate_refused"
# A later session sent an earlier session's member an urgent message on their collision (#513), which gates the earlier
# session until its member answers. The entry's actor is the later session's member, its target the earlier one's, and
# its detail holds the collision's score and cause, never the message's text.
URGENT_MESSAGE: Kind = "urgent_message"
# A lead or an admin changed a project's wait; the entry's detail holds the minutes now.
PROJECT_WAIT_CHANGED: Kind = "project_wait_changed"
# A department (ADR-0032); the entry's target is its department ID and its detail its name. A removed department's
# detail also lists the projects it left in no department.
DEPARTMENT_CREATED: Kind = "department_created"
DEPARTMENT_RENAMED: Kind = "department_renamed"
DEPARTMENT_REMOVED: Kind = "department_removed"
# A department's lead; the entry's target is the department ID and its detail names the member.
DEPARTMENT_LEAD_APPOINTED: Kind = "department_lead_appointed"
DEPARTMENT_LEAD_REMOVED: Kind = "department_lead_removed"
# A project moved into or out of a department; the entry's detail holds the department it is in now and the one it
# was in, either None for no department.
PROJECT_MOVED: Kind = "project_moved"
# A department closed to its access list or opened to the whole company again; the entry's target is its department ID
# and its detail its name.
DEPARTMENT_RESTRICTED: Kind = "department_restricted"
DEPARTMENT_OPENED: Kind = "department_opened"
# A member put on or taken off a department's access list; the entry's target is the department ID and its detail
# names the member.
DEPARTMENT_ACCESS_GRANTED: Kind = "department_access_granted"
DEPARTMENT_ACCESS_REVOKED: Kind = "department_access_revoked"


@dataclass(frozen=True)
class Event:
    id: int
    at: datetime
    actor: str
    kind: str
    project_id: str | None
    target: str | None
    detail: dict[str, Any]


@dataclass(frozen=True)
class Interviewed:
    """A memory promoted from an interview: where it went, the member who ran the interview, when, and the source."""

    path: str
    interviewer: str
    at: datetime
    source: str


@dataclass(frozen=True)
class Page:
    events: list[Event]
    next: int | None


class Audit:
    def __init__(self, db: Database, clock: Clock, identity: Identity) -> None:
        self._db = db
        self._clock = clock
        self._identity = identity

    def record(
        self,
        kind: str,
        *,
        member: Member | None = None,
        company_pk: int | None = None,
        actor: str | None = None,
        project_id: str | None = None,
        target: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Remember that something changed, alongside the change itself, so the two can't disagree."""
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO audit_events (at, team_id, actor_id, actor, kind, project_id, target, detail)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    self._clock(),
                    member.company_pk if member else company_pk,
                    member.pk if member else None,
                    actor or (member.member_id if member else "unknown"),
                    kind,
                    project_id,
                    target,
                    Jsonb(detail or {}),
                ),
            )

    def memory(self, caller: Caller, change: str, path: str, *, project_id: str | None = None, **detail: object) -> None:
        """Note a change to one memory: who changed it, in which project, and at which path.

        The project is the memory's own, or the one named; never the project the change was made from, whose leads
        need not reach the memory. Company and department memory belong to none. It records where the memory is,
        never what it says: the memory folder's git history holds that.
        """
        if caller.agent is not None:
            detail = {**detail, "agent": caller.agent}
        self.record(
            change,
            member=caller.member,
            project_id=project_id or project_in(path),
            target=path,
            detail=detail,
        )

    def has_imported_from(self, caller: Caller, repository: str) -> bool:
        """Whether the caller has ever promoted an import whose source is a file of this repository. The imports
        table forgets a memory once it moves, so the promotion's entry is what remembers who imported from where."""
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT 1 FROM audit_events WHERE team_id = %s AND kind = %s AND actor_id = %s"
                " AND split_part(detail->>'imported_from', ':', 1) = %s LIMIT 1",
                (caller.member.company_pk, MEMORY_PROMOTED, caller.member.pk, repository),
            ).fetchone()
        return row is not None

    def imports_in(self, company_pk: int, project_id: str) -> tuple[list[str], list[str]]:
        """The sources of a project's imports: one per import promoted, and one per import still waiting on the
        challenge its promotion raised, a challenge no decision has closed yet."""
        with self._db.transaction() as conn:
            promoted = conn.execute(
                "SELECT detail->>'imported_from' AS source FROM audit_events WHERE team_id = %s AND project_id = %s"
                " AND kind = %s AND detail ? 'imported_from'",
                (company_pk, project_id, MEMORY_PROMOTED),
            ).fetchall()
            waiting = conn.execute(
                "SELECT raised.detail->>'imported_from' AS source FROM audit_events raised"
                " WHERE raised.team_id = %s AND raised.project_id = %s AND raised.kind = %s"
                " AND raised.detail ? 'imported_from' AND NOT EXISTS (SELECT 1 FROM audit_events decided"
                " WHERE decided.team_id = raised.team_id AND decided.kind = %s"
                " AND decided.detail->>'challenge_id' = raised.detail->>'challenge_id')",
                (company_pk, project_id, CHALLENGE_RAISED, CHALLENGE_DECIDED),
            ).fetchall()
        return [row["source"] for row in promoted], [row["source"] for row in waiting]

    def interviews_of(self, member: Member) -> list[Interviewed]:
        """Each promotion that named this member as author with an interview as its source, newest first: what was
        written from their interview, by whom and when (ADR-0029)."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT target, actor, at, detail->>'imported_from' AS source FROM audit_events"
                " WHERE team_id = %s AND kind = %s AND detail->>'author' = %s"
                " AND detail->>'imported_from' LIKE 'interview:%%' ORDER BY id DESC",
                (member.company_pk, MEMORY_PROMOTED, member.member_id),
            ).fetchall()
        return [Interviewed(row["target"], row["actor"], row["at"], row["source"]) for row in rows]

    def card(self, caller: Caller, change: str, project_id: str, number: int, **detail: object) -> None:
        """Note a change to one card on a project's board: who changed it, and which card. A card has no history but
        these entries (ADR-0014)."""
        if caller.agent is not None:
            detail = {**detail, "agent": caller.agent}
        self.record(change, member=caller.member, project_id=project_id, target=f"card {number}", detail=detail)

    def read(
        self,
        reader: Member,
        *,
        limit: int = 50,
        before: int | None = None,
        member_id: str | None = None,
        kind: str | None = None,
        project_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Page:
        """The reader's company's log, newest first. One page, with where the next page starts.

        A project lead who doesn't run the company sees their own projects' events and nothing else, and of those
        none naming a memory or folder they can't reach.
        """
        self.require_reader(reader)
        limit = max(1, min(limit, 200))
        wheres = ["(e.team_id = %s OR e.team_id IS NULL)"]
        values: list[Any] = [reader.company_pk]
        reach = None
        if not _runs_the_company(reader):
            wheres = ["e.team_id = %s", "e.project_id = ANY(%s)"]
            values = [reader.company_pk, self._identity.leads_of(reader)]
            reach = self._identity.caller_in(reader, None)
        if before is not None:
            wheres.append("e.id < %s")
            values.append(before)
        if kind:
            wheres.append("e.kind = %s")
            values.append(kind)
        if project_id:
            wheres.append("e.project_id = %s")
            values.append(project_id)
        if since:
            wheres.append("e.at >= %s")
            values.append(since)
        if until:
            wheres.append("e.at <= %s")
            values.append(until)
        with self._db.transaction() as conn:
            if member_id:
                # An entry with a member is theirs by row id; one without, such as a refused sign-in, by its actor.
                found = self._identity.in_company(conn, reader.company_pk, [member_id]).get(member_id)
                wheres.append("(e.actor_id = %s OR (e.actor_id IS NULL AND e.actor = %s))")
                values += [found[0] if found else None, member_id]
            rows = conn.execute(
                "SELECT e.id, e.at, e.actor, e.actor_id, e.kind, e.project_id, e.target, e.detail FROM audit_events e"  # noqa: S608  # values are bound as parameters; only clauses the code builds are spliced in
                f" WHERE {' AND '.join(wheres)} ORDER BY e.id DESC LIMIT %s",
                (*values, limit + 1),
            ).fetchall()
            actors = self._identity.named_in(conn, (row["actor_id"] for row in rows if row["actor_id"] is not None))
        events = [
            Event(
                id=row["id"],
                at=row["at"],
                actor=actors[row["actor_id"]][0] if row["actor_id"] in actors else row["actor"],
                kind=row["kind"],
                project_id=row["project_id"],
                target=row["target"],
                detail=row["detail"],
            )
            for row in rows[:limit]
            if reach is None or all(reach.reaches(path) for path in _paths(row["target"], row["detail"]))
        ]
        # The next page starts after the last row read, even one left out, so leaving rows out never ends the log.
        return Page(events, rows[limit - 1]["id"] if len(rows) > limit else None)

    def _may_read(self, member: Member) -> bool:
        """The owner and the admins read the whole log; a project lead reads their own projects'."""
        return _runs_the_company(member) or bool(self._identity.leads_of(member))

    def require_reader(self, member: Member) -> None:
        if not self._may_read(member):
            raise Refused("Only the company's owner, its admins and a project's leads can read the audit log.")


def _runs_the_company(member: Member) -> bool:
    return member.is_owner or member.is_admin


def _paths(target: str | None, detail: dict[str, Any]) -> list[str]:
    """Every value of an entry that may name a memory or folder: its target and its detail's text."""
    return [value for value in [target, *detail.values()] if isinstance(value, str)]
