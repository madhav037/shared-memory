"""The audit log: who changed what, and when.

It answers "who did this" for changes that leave no memory file behind — signing in, members, roles, access and tokens —
alongside the memory changes themselves. It is append-only and holds no memory content: it points at paths, and the
memory folder's git history holds what they said.

A sign-in that no member can be found for belongs to no team; those entries are shown to every team's readers, because a
server holds one team in practice and nobody else could otherwise see that someone tried.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from shared_memory.clock import Clock
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity, Member

SIGNED_IN = "signed_in"
SIGN_IN_REFUSED = "sign_in_refused"
TOKEN_ISSUED = "token_issued"
MEMBER_ADDED = "member_added"
MEMBER_REMOVED = "member_removed"
MEMBER_CHANGED = "member_changed"
ADMIN_GRANTED = "admin_granted"
ADMIN_REVOKED = "admin_revoked"
OWNERSHIP_HANDED_OVER = "ownership_handed_over"
PROJECT_CREATED = "project_created"
PROJECT_RENAMED = "project_renamed"
LEAD_APPOINTED = "lead_appointed"
LEAD_REMOVED = "lead_removed"
REPOSITORY_ADDED = "repository_added"
REPOSITORY_REMOVED = "repository_removed"
PROJECT_RESTRICTED = "project_restricted"
PROJECT_OPENED = "project_opened"
ACCESS_GRANTED = "access_granted"
ACCESS_REVOKED = "access_revoked"
MEMORY_SAVED = "memory_saved"
MEMORY_EDITED = "memory_edited"
MEMORY_DELETED = "memory_deleted"
MEMORY_PROMOTED = "memory_promoted"
MEMORY_SUPERSEDED = "memory_superseded"
MEMORY_RETIRED = "memory_retired"
MEMORY_PINNED = "memory_pinned"
MEMORY_UNPINNED = "memory_unpinned"
CHALLENGE_RAISED = "challenge_raised"
CHALLENGE_DECIDED = "challenge_decided"


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
        team_pk: int | None = None,
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
                    member.team_pk if member else team_pk,
                    member.pk if member else None,
                    actor or (member.member_id if member else "unknown"),
                    kind,
                    project_id,
                    target,
                    Jsonb(detail or {}),
                ),
            )

    def memory(self, caller: Caller, change: str, path: str, **detail: Any) -> None:
        """Note a change to one memory: who changed it, in which project, and at which path.

        It records where the memory is, never what it says: the memory folder's git history holds that.
        """
        self.record(
            change,
            member=caller.member,
            project_id=caller.project.project_id if caller.project else None,
            target=path,
            detail=detail,
        )

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
        """The reader's team's log, newest first. One page, with where the next page starts.

        A project lead who doesn't run the team sees their own projects' events and nothing else.
        """
        self.require_reader(reader)
        limit = max(1, min(limit, 200))
        wheres = ["(e.team_id = %s OR e.team_id IS NULL)"]
        values: list[Any] = [reader.team_pk]
        if not _runs_the_team(reader):
            wheres = ["e.team_id = %s", "e.project_id = ANY(%s)"]
            values = [reader.team_pk, self._identity.leads_of(reader)]
        if before is not None:
            wheres.append("e.id < %s")
            values.append(before)
        if member_id:
            wheres.append("(m.member_id = %s OR (e.actor_id IS NULL AND e.actor = %s))")
            values += [member_id, member_id]
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
            rows = conn.execute(
                "SELECT e.id, e.at, e.actor, e.kind, e.project_id, e.target, e.detail, m.member_id"
                " FROM audit_events e LEFT JOIN members m ON m.id = e.actor_id"
                f" WHERE {' AND '.join(wheres)} ORDER BY e.id DESC LIMIT %s",
                (*values, limit + 1),
            ).fetchall()
        events = [
            Event(
                id=row["id"],
                at=row["at"],
                actor=row["member_id"] or row["actor"],
                kind=row["kind"],
                project_id=row["project_id"],
                target=row["target"],
                detail=row["detail"],
            )
            for row in rows[:limit]
        ]
        return Page(events, events[-1].id if len(rows) > limit and events else None)

    def may_read(self, member: Member) -> bool:
        """The owner and the admins read the whole log; a project lead reads their own projects'."""
        return _runs_the_team(member) or bool(self._identity.leads_of(member))

    def require_reader(self, member: Member) -> None:
        if not self.may_read(member):
            raise Refused("Only the team's owner, its admins and a project's leads can read the audit log.")


def _runs_the_team(member: Member) -> bool:
    return member.is_owner or member.is_admin
