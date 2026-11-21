"""Challenges and news: who may decide a challenge, and what sessions are told about them."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Literal

from shared_memory.audit import CHALLENGE_RAISED, KEEPER_REMOVED, Audit
from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Conn, Database, moved_prefix
from shared_memory.departments import Departments
from shared_memory.errors import Refused
from shared_memory.identity import NAME_PATTERN, Caller, Identity, project_in
from shared_memory.memory import locate
from shared_memory.sessions import usable
from shared_memory.store import MemoryStore
from shared_memory.validation import refuse_secret

SCHEMA = """
CREATE TABLE IF NOT EXISTS challenges (
    id BIGSERIAL PRIMARY KEY,
    team TEXT NOT NULL,
    kind TEXT NOT NULL,
    target_path TEXT NOT NULL,
    target_author TEXT NOT NULL,
    challenger_path TEXT,
    level TEXT NOT NULL,
    raised_by TEXT NOT NULL,
    promoted_by TEXT,
    raised_at TIMESTAMPTZ NOT NULL,
    author_notified_at TIMESTAMPTZ,
    state TEXT NOT NULL,
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    explanation TEXT,
    reasoning TEXT,
    foundation TEXT
);
ALTER TABLE challenges ADD COLUMN IF NOT EXISTS promoted_by TEXT;
ALTER TABLE challenges ADD COLUMN IF NOT EXISTS reasoning TEXT;
ALTER TABLE challenges ADD COLUMN IF NOT EXISTS foundation TEXT;
-- The reason a doubt names (spec #502): misled or contradicts_code. Other kinds name none.
ALTER TABLE challenges ADD COLUMN IF NOT EXISTS reason TEXT;
-- The company memory a promotion into department memory contradicts (#634): accepting it raises a level contradiction.
ALTER TABLE challenges ADD COLUMN IF NOT EXISTS exception_to TEXT;
-- One open doubt per memory and reason, so a second raise joins it, even when two sessions raise it at once.
CREATE UNIQUE INDEX IF NOT EXISTS challenges_one_open_doubt ON challenges (team, target_path, reason)
    WHERE kind = 'doubt' AND state = 'open';

-- What each member who raised a doubt brought: the first raiser's is the first row, each +1 adds one.
CREATE TABLE IF NOT EXISTS challenge_evidence (
    id BIGSERIAL PRIMARY KEY,
    challenge_id BIGINT NOT NULL REFERENCES challenges (id),
    member_id TEXT NOT NULL,
    session_identifier TEXT,
    reasoning TEXT,
    code_reference TEXT,
    quoted_line TEXT,
    raised_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS challenge_evidence_by_challenge ON challenge_evidence (challenge_id);

CREATE TABLE IF NOT EXISTS notices (
    id BIGSERIAL PRIMARY KEY,
    team TEXT NOT NULL,
    member_id TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    delivered_at TIMESTAMPTZ
);
"""

# The challenge kind a session raises to doubt a memory, and the reasons a doubt names (CONTEXT.md: Reason).
DOUBT = "doubt"
Reason = Literal["misled", "contradicts_code"]
REASONS: tuple[Reason, ...] = ("misled", "contradicts_code")
# The challenge kind a promotion into department memory by anyone but its department leads raises (ADR-0033). It has
# no challenged memory: it stands against the department's folder, departments/<department ID>.
PROMOTE = "promote"
# A level contradiction (CONTEXT.md): the narrower memory, already promoted and holding where it applies, against the
# broader memory it contradicts. Its challenger_path is the narrower memory, its target_path the broader, its level the
# narrower level, whose leads decide: keep an exception, or follow.
LEVEL_CONTRADICTION = "level_contradiction"
# What a reason says, after "N say(s)".
_REASON_IN_WORDS: dict[str, str] = {"misled": "it misled them", "contradicts_code": "it contradicts the code"}
# The longest line of code a contradicts_code doubt may quote.
QUOTED_LINE_LIMIT = 300
_CODE_REFERENCE = re.compile(r"^(?P<repository>[^:\s]+):(?P<path>[^:\n]*[^:\s][^:\n]*):(?P<line>[1-9][0-9]*)$")


@dataclass(frozen=True)
class CodeReference:
    """Where the code a doubt quotes is, written repository:path:line, and the line as the code has it."""

    repository: str
    path: str
    line: int
    quoted_line: str

    def __str__(self) -> str:
        return f"{self.repository}:{self.path}:{self.line}"

    @classmethod
    def parse(cls, written: str | None, quoted_line: str | None) -> CodeReference:
        """The code reference a contradicts_code doubt gives, refused unless it names a repository, a file and a line
        and quotes that line."""
        match = _CODE_REFERENCE.match((written or "").strip())
        if match is None or not NAME_PATTERN.match(match["repository"]):
            raise Refused(
                "A doubt that contradicts the code says where: pass code_reference written repository:path:line, for "
                "example billing-api:src/tax.py:42, using the repository names from each repository's settings."
            )
        quoted = (quoted_line or "").strip()
        if not quoted or "\n" in quoted or len(quoted) > QUOTED_LINE_LIMIT:
            raise Refused(
                "A doubt that contradicts the code quotes the line: pass quoted_line, that one line as the code has "
                f"it, at most {QUOTED_LINE_LIMIT} characters."
            )
        refuse_secret(quoted, "The quoted line", "into a challenge")
        return cls(match["repository"], match["path"], int(match["line"]), quoted)

    @classmethod
    def stored(cls, written: str, quoted_line: str) -> CodeReference:
        """A code reference as it was kept, already checked when it was raised."""
        repository, _, rest = written.partition(":")
        path, _, line = rest.rpartition(":")
        return cls(repository, path, int(line), quoted_line)


@dataclass(frozen=True)
class Evidence:
    """What one member who raised a doubt brought: their reasoning and, for contradicts_code, the code they quote."""

    member_id: str
    session_identifier: str | None
    reasoning: str | None
    code_reference: CodeReference | None
    raised_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Evidence:
        written = row["code_reference"]
        reference = None if written is None else CodeReference.stored(written, row["quoted_line"] or "")
        return cls(row["member_id"], row["session_identifier"], row["reasoning"], reference, row["raised_at"])


@dataclass(frozen=True)
class Raised:
    """What raising a doubt answers: the challenge, whether the raise joined one already open, and how many have now
    raised it."""

    challenge_id: int
    joined: bool
    count: int


@dataclass(frozen=True)
class Challenge:
    id: int
    kind: str
    target_path: str
    target_author: str
    challenger_path: str | None
    level: str
    raised_by: str
    promoted_by: str | None
    raised_at: datetime
    reasoning: str | None
    # The foundation (ADR-0019) a challenge is about: a keeper of it or a lead of its project decides it. A kind "add"
    # challenge has no challenged memory, so its target_path is the foundation's folder.
    foundation: str | None = None
    # The reason a doubt names; None for every other kind.
    reason: Reason | None = None
    # For a promotion into department memory, the company memory it contradicts; None otherwise.
    exception_to: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Challenge:
        return cls(
            row["id"],
            row["kind"],
            row["target_path"],
            row["target_author"],
            row["challenger_path"],
            row["level"],
            row["raised_by"],
            row["promoted_by"],
            row["raised_at"],
            row["reasoning"],
            row.get("foundation"),
            row.get("reason"),
            row.get("exception_to"),
        )


@dataclass(frozen=True)
class Doubt:
    """An open challenge that names a reason, with every piece of evidence raised for it, the first raiser's first."""

    challenge: Challenge
    reason: Reason
    evidence: tuple[Evidence, ...]

    @property
    def members(self) -> tuple[str, ...]:
        """Every member who raised it, first raiser first, each once however many sessions they raised it from."""
        return _members(self.evidence)

    @property
    def count(self) -> int:
        """How many members have raised it: the first and each +1. A member raising it again adds evidence, not to
        the count."""
        return len(self.members)


@dataclass(frozen=True)
class ReasonRaised:
    """One reason a memory is in doubt for: how many members name it and, for contradicts_code, where the code is."""

    reason: Reason
    count: int
    # Each code reference quoted for it, written repository:path:line, first quoted first and each once.
    code_references: tuple[str, ...] = ()

    def in_words(self) -> str:
        """As the in-doubt line says it, e.g. "1 says it contradicts billing-api:src/tax.py:42"."""
        says = "says" if self.count == 1 else "say"
        if self.reason == "contradicts_code" and self.code_references:
            return f"{self.count} {says} it contradicts {', '.join(self.code_references)}"
        return f"{self.count} {says} {_REASON_IN_WORDS[self.reason]}"


@dataclass(frozen=True)
class InDoubt:
    """What marks a memory in doubt (CONTEXT.md) wherever it is shown: how many members doubt it, and for which
    reasons, in the order of `REASONS`."""

    reasons: tuple[ReasonRaised, ...]
    # How many members doubt it, for any reason: one who names both reasons is counted once.
    count: int

    @classmethod
    def of(cls, doubts: Iterable[Doubt]) -> InDoubt:
        listed = list(doubts)
        counts: dict[Reason, int] = {}
        references: dict[Reason, dict[str, None]] = {}
        for doubt in listed:
            # One open doubt per memory and reason, so a reason's count is its doubt's.
            counts[doubt.reason] = doubt.count
            quoted = references.setdefault(doubt.reason, {})
            for each in doubt.evidence:
                if each.code_reference is not None:
                    quoted[str(each.code_reference)] = None
        return cls(
            tuple(ReasonRaised(r, counts[r], tuple(references[r])) for r in REASONS if counts.get(r)),
            len(_members(each for doubt in listed for each in doubt.evidence)),
        )

    def line(self) -> str:
        """The in-doubt line, e.g. "In doubt: 3 say it misled them; 1 says it contradicts billing-api:src/tax.py:42"."""
        return "In doubt: " + "; ".join(each.in_words() for each in self.reasons)


def ranked(score: float, in_doubt: InDoubt | None, penalty: float) -> float:
    """A score as recall and search rank it: a memory in doubt's multiplied by the penalty, a down-rank, not a filter."""
    return score if in_doubt is None else score * penalty


# In what capacity a member decides a challenge: as the challenged memory's author, as a lead of its project, as one
# of the company's admins (the owner is one), because the fallback period has passed, or because its author has left;
# for a promotion into department memory, as one of the department's leads.
DecidesAs = Literal["author", "lead", "keeper", "admin", "fallback", "author_left", "department_lead"]


@dataclass(frozen=True)
class Waiting:
    """An open challenge a member may decide, and in what capacity it is theirs to decide."""

    challenge: Challenge
    decides_as: DecidesAs


def department_of(challenge: Challenge) -> str | None:
    """The department a promotion into department memory asks to join; None for every other kind."""
    if challenge.kind != PROMOTE:
        return None
    return PurePosixPath(challenge.target_path).name


def project_of(challenge: Challenge) -> str | None:
    """The project a challenge is about: the challenging memory's, or the challenged one's. Company memory has none."""
    for path in (challenge.challenger_path, challenge.target_path):
        if path is None:
            continue
        try:
            return locate(path).project_id
        except Refused:
            continue
    return None


class Challenges:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        store: MemoryStore,
        identity: Identity,
        audit: Audit,
        clock: Clock,
        departments: Departments,
    ) -> None:
        self._settings = settings
        self._departments = departments
        self._db = db
        self._store = store
        self._identity = identity
        self._audit = audit
        self._clock = clock
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)

    # Storing challenges

    def raise_challenge(
        self,
        caller: Caller,
        *,
        kind: str,
        target_path: str,
        target_author: str,
        level: str,
        challenger_path: str | None = None,
        promoted_by: str | None = None,
        reasoning: str | None = None,
        foundation: str | None = None,
        imported_from: str | None = None,
        exception_to: str | None = None,
        raised_by: str | None = None,
    ) -> int:
        """Open a challenge. imported_from is the source of an import whose promotion raised it, kept in the audit log
        so onboarding progress counts the import as waiting on a challenge. raised_by is the caller unless named."""
        with self._db.transaction() as conn:
            row = conn.execute(
                "INSERT INTO challenges (team, kind, target_path, target_author, challenger_path, level, raised_by,"
                " promoted_by, raised_at, state, reasoning, foundation, exception_to)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'open', %s, %s, %s) RETURNING id",
                (
                    caller.company, kind, target_path, target_author, challenger_path, level,
                    raised_by or caller.member_id, promoted_by, self._clock(), reasoning, foundation, exception_to,
                ),  # fmt: skip
            ).fetchone()
        assert row is not None
        challenge_id: int = row["id"]
        about = {} if foundation is None else {"foundation": foundation}
        if imported_from is not None:
            about["imported_from"] = imported_from
        if kind == LEVEL_CONTRADICTION and challenger_path is not None:
            about["narrower"] = challenger_path  # the memory that holds, as an exception, until it is decided
        self._audit.memory(
            caller, CHALLENGE_RAISED, target_path, challenge_id=challenge_id, challenge=kind, author=target_author,
            **about,
        )
        return challenge_id

    def doubt(
        self,
        caller: Caller,
        path: str,
        reason: str,
        *,
        reasoning: str | None = None,
        code_reference: str | None = None,
        quoted_line: str | None = None,
        session: str | None = None,
    ) -> Raised:
        """Doubt a memory the caller can read, at any level and their own included, naming a reason. A raise naming
        the same memory and reason as an open doubt joins it as a +1."""
        caller.require_project()
        caller.require_reach(path)  # before the memory is looked up, so a restricted project never says what it holds
        named = _reason(reason, code_reference, quoted_line)
        reference = CodeReference.parse(code_reference, quoted_line) if named == "contradicts_code" else None
        written = (reasoning or "").strip() or None
        if written is not None:
            refuse_secret(written, "This reasoning", "into a challenge")
        location = locate(path)
        memory = self._store.read(caller.company, location.path)
        if memory.status != "active":
            raise Refused(f"{location.path} is already {memory.status}, so there is nothing left to doubt.")
        evidence = Evidence(caller.member_id, usable(session), written, reference, self._clock())
        return self.raise_doubt(
            caller, target_path=str(location.path), target_author=memory.author, level=location.level, reason=named,
            evidence=evidence,
        )  # fmt: skip

    def raise_doubt(
        self, caller: Caller, *, target_path: str, target_author: str, level: str, reason: Reason, evidence: Evidence
    ) -> Raised:
        """Open a doubt, or join the open one naming the same memory and reason, and add the evidence, in one
        transaction: two sessions raising it at once give one challenge with both pieces of evidence. The count
        answered is how many members have raised it."""
        reference = evidence.code_reference
        with self._db.transaction() as conn:
            challenge_id, joined = self._open_or_join(conn, caller, target_path, target_author, level, reason)
            if joined:
                _show_the_author_again(conn, challenge_id)
            conn.execute(
                "INSERT INTO challenge_evidence (challenge_id, member_id, session_identifier, reasoning, code_reference,"
                " quoted_line, raised_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    challenge_id, evidence.member_id, evidence.session_identifier, evidence.reasoning,
                    None if reference is None else str(reference), None if reference is None else reference.quoted_line,
                    evidence.raised_at,
                ),  # fmt: skip
            )
            counted = conn.execute(
                "SELECT count(DISTINCT member_id) AS count FROM challenge_evidence WHERE challenge_id = %s",
                (challenge_id,),
            ).fetchone()
        assert counted is not None
        self._audit.memory(
            caller, CHALLENGE_RAISED, target_path, challenge_id=challenge_id, challenge=DOUBT, author=target_author,
            reason=reason, joined=joined,
        )  # fmt: skip
        return Raised(challenge_id, joined, int(counted["count"]))

    def _open_or_join(
        self, conn: Conn, caller: Caller, target_path: str, target_author: str, level: str, reason: Reason
    ) -> tuple[int, bool]:
        """The open doubt naming this memory and reason, opened now unless one already is, and whether it already
        was."""
        while True:
            opened = conn.execute(
                "INSERT INTO challenges (team, kind, target_path, target_author, level, raised_by, raised_at, state,"
                " reason) VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s) ON CONFLICT (team, target_path, reason)"
                " WHERE kind = 'doubt' AND state = 'open' DO NOTHING RETURNING id",
                (caller.company, DOUBT, target_path, target_author, level, caller.member_id, self._clock(), reason),
            ).fetchone()
            if opened is not None:
                return int(opened["id"]), False
            # Another raise holds it open. The insert waited for that raise to commit, so it is found here, unless it
            # was decided in between: then the loop opens a new one.
            # FOR UPDATE holds it open until this raise commits, so it isn't decided before its evidence lands.
            found = conn.execute(
                "SELECT id FROM challenges WHERE team = %s AND kind = 'doubt' AND state = 'open' AND target_path = %s"
                " AND reason = %s FOR UPDATE",
                (caller.company, target_path, reason),
            ).fetchone()
            if found is not None:
                return int(found["id"]), True

    def doubts_against(self, company: str, paths: Iterable[str]) -> dict[str, list[Doubt]]:
        """For each memory path, its open challenges that name a reason, each with all its evidence: what makes a
        memory in doubt (CONTEXT.md). A path with none maps to an empty list."""
        wanted = list(dict.fromkeys(paths))
        doubts: dict[str, list[Doubt]] = {path: [] for path in wanted}
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM challenges WHERE team = %s AND state = 'open' AND reason IS NOT NULL"
                " AND target_path = ANY(%s) ORDER BY id",
                (company, wanted),
            ).fetchall()
        evidence = self._evidence([row["id"] for row in rows])
        for row in rows:
            challenge = Challenge.from_row(row)
            assert challenge.reason is not None
            doubts[challenge.target_path].append(Doubt(challenge, challenge.reason, evidence.get(challenge.id, ())))
        return doubts

    def in_doubt(self, company: str, paths: Iterable[str]) -> dict[str, InDoubt]:
        """Those of these memories that are in doubt, each with what marks it so. One batch, however many paths."""
        wanted = list(paths)
        if not wanted:
            return {}
        return {path: InDoubt.of(doubts) for path, doubts in self.doubts_against(company, wanted).items() if doubts}

    def _evidence(self, challenge_ids: list[int]) -> dict[int, tuple[Evidence, ...]]:
        """Each challenge's evidence, first raised first."""
        if not challenge_ids:
            return {}
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM challenge_evidence WHERE challenge_id = ANY(%s) ORDER BY id", (challenge_ids,)
            ).fetchall()
        found: dict[int, list[Evidence]] = {}
        for row in rows:
            found.setdefault(row["challenge_id"], []).append(Evidence.from_row(row))
        return {challenge_id: tuple(each) for challenge_id, each in found.items()}

    def open_challenge(self, company: str, challenge_id: int) -> Challenge | None:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM challenges WHERE id = %s AND team = %s AND state = 'open'", (challenge_id, company)
            ).fetchone()
        return None if row is None else Challenge.from_row(row)

    def open_challenges(
        self, company: str, *, target_path: str | None = None, challenger_paths: Iterable[str] | None = None
    ) -> list[Challenge]:
        conditions: list[str] = ["team = %s", "state = 'open'"]
        params: list[Any] = [company]
        if target_path is not None:
            conditions.append("target_path = %s")
            params.append(target_path)
        if challenger_paths is not None:
            conditions.append("challenger_path = ANY(%s)")
            params.append(list(challenger_paths))
        with self._db.transaction() as conn:
            rows = conn.execute(
                f"SELECT * FROM challenges WHERE {' AND '.join(conditions)} ORDER BY target_path, id", params  # noqa: S608  # values are bound as parameters; only clauses the code builds are spliced in
            ).fetchall()
        return [Challenge.from_row(row) for row in rows]

    def decide(self, challenge: Challenge, state: str, decider: str, explanation: str | None = None) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE challenges SET state = %s, decided_by = %s, decided_at = %s, explanation = %s WHERE id = %s",
                (state, decider, self._clock(), explanation, challenge.id),
            )

    def close_all_against(self, company: str, target_path: str, decider: str, explanation: str) -> None:
        """Close every open challenge against a memory, telling each member who raised one why."""
        self._close(company, self.open_challenges(company, target_path=target_path), decider, explanation)

    def resolve_doubts(self, company: str, target_path: str, decider: str, explanation: str) -> None:
        """Close every open doubt against a memory as resolved, its author having put the memory right in a session,
        telling each member who added evidence how."""
        doubts = [one for one in self.open_challenges(company, target_path=target_path) if one.kind == DOUBT]
        self._close(company, doubts, decider, f"resolved, {explanation}")

    def _close(self, company: str, challenges: list[Challenge], decider: str, explanation: str) -> None:
        raisers = self.raisers(challenges)
        for challenge in challenges:
            self.decide(challenge, "closed", decider, explanation)
            self.tell_raisers(
                company,
                raisers[challenge.id],
                f"Your challenge {challenge.id} against {challenge.target_path} was closed: {explanation}",
            )

    def raisers(self, challenges: Iterable[Challenge]) -> dict[int, tuple[str, ...]]:
        """Who raised each challenge, first raiser first: for a doubt, every member who added evidence to it, each
        once; for any other kind, the member who raised it."""
        listed = list(challenges)
        raised: dict[int, tuple[str, ...]] = {one.id: (one.raised_by,) for one in listed}
        doubts = [one.id for one in listed if one.kind == DOUBT]
        if not doubts:
            return raised
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT challenge_id, member_id FROM challenge_evidence WHERE challenge_id = ANY(%s)"
                " GROUP BY challenge_id, member_id ORDER BY challenge_id, min(id)",
                (doubts,),
            ).fetchall()
        found: dict[int, list[str]] = {}
        for row in rows:
            found.setdefault(row["challenge_id"], []).append(row["member_id"])
        raised.update({challenge_id: tuple(members) for challenge_id, members in found.items()})
        return raised

    def tell_raisers(self, company: str, raisers: tuple[str, ...], text: str) -> None:
        """Tell every member who raised a challenge, each once: its `raisers`, for a doubt everyone who added evidence
        to it."""
        for member_id in raisers:
            self.tell(company, member_id, text)

    def tell(self, company: str, member_id: str, text: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO notices (team, member_id, text, created_at) VALUES (%s, %s, %s, %s)",
                (company, member_id, text, self._clock()),
            )

    def pending(self, company: str, paths: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
        """For each personal memory path, the open challenges it is waiting on."""
        wanted = list(paths)
        labels: dict[str, list[dict[str, Any]]] = {path: [] for path in wanted}
        for challenge in self.open_challenges(company, challenger_paths=wanted):
            assert challenge.challenger_path is not None
            labels[challenge.challenger_path].append(
                {"challenge_id": challenge.id, "kind": challenge.kind, "replaces": challenge.target_path}
            )
        return labels

    def against(self, caller: Caller, path: str) -> list[dict[str, Any]]:
        """Every open challenge against one memory, and whether this member may decide it and in what capacity."""
        listed = []
        challenges = self.open_challenges(caller.company, target_path=path)
        raisers = self.raisers(challenges)
        for c in challenges:
            decides_as = self.decides_as(caller, c, raisers[c.id])
            listed.append(
                {
                    "challenge_id": c.id,
                    "kind": c.kind,
                    "raised_by": c.raised_by,
                    "challenger_path": c.challenger_path,
                    "reason": c.reason,
                    "may_decide": decides_as is not None,
                    "decides_as": decides_as,
                }
            )
        return listed

    def waiting_for(self, caller: Caller) -> list[Waiting]:
        """Every open challenge this member may decide, in the projects they can reach, each with the capacity it is
        theirs in."""
        reachable = {project.project_id for project in self._identity.projects(caller.member)} | {None}
        waiting = []
        reached = [one for one in self.open_challenges(caller.company) if project_of(one) in reachable]
        raisers = self.raisers(reached)
        for challenge in reached:
            decides_as = self.decides_as(caller, challenge, raisers[challenge.id])
            if decides_as is not None:
                waiting.append(Waiting(challenge, decides_as))
        return waiting

    def raised_by(self, caller: Caller) -> list[dict[str, Any]]:
        """Every challenge this member raised, newest first, and how each one ended."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT id, kind, reason, target_path, challenger_path, raised_at, state, decided_by, decided_at,"
                " explanation, reasoning, foundation FROM challenges WHERE team = %s AND raised_by = %s ORDER BY id DESC",
                (caller.company, caller.member_id),
            ).fetchall()
        return [
            {
                "challenge_id": row["id"],
                "kind": row["kind"],
                "reason": row["reason"],
                "target_path": row["target_path"],
                "challenger_path": row["challenger_path"],
                "raised_at": row["raised_at"],
                "state": row["state"],
                "decided_by": row["decided_by"],
                "decided_at": row["decided_at"],
                "explanation": row["explanation"],
                "reasoning": row["reasoning"],
                "foundation": row["foundation"],
            }
            for row in rows
        ]

    def drop_keepers(self, conn: Conn, caller: Caller) -> Callable[[], None]:
        """Drop the keepers who can no longer reach their project: removed from the company, or shut out of a restricted
        project. Identity calls this inside the transaction of any change that may have cost a member a project
        (`Identity.on_access_lost`). What it gives back notes each drop in the audit log once that has committed."""
        dropped = self._identity.drop_keepers(conn, caller)

        def committed() -> None:
            for project_id, foundation, member_id in dropped:
                self._audit.record(
                    KEEPER_REMOVED,
                    member=caller.member,
                    project_id=project_id,
                    target=member_id,
                    detail={"foundation": foundation, "dropped": True},
                )

        return committed

    # Who decides

    def decides_as(self, caller: Caller, challenge: Challenge, raisers: tuple[str, ...]) -> DecidesAs | None:
        """In what capacity this member may decide a challenge, or None when they may not (ADR-0017).

        The challenged memory's author decides. So may a lead of the project the challenged memory is in, and one of
        the company's admins, unless they raised the challenge themselves (for a doubt, added evidence to it); company
        memory has no project, so only admins stand there. Once the author has left, or after the fallback period,
        any member may. `raisers` is the challenge's, from `raisers`, fetched once however many are decided.

        A foundation challenge is the exception: only a lead of the project it is in, or a keeper of that foundation,
        decides it, and never whoever raised it. No author, admin or fallback standing applies. So is a promotion into
        department memory: only the department's leads decide it, or the company's admins once it has no lead left.
        """
        if challenge.kind == LEVEL_CONTRADICTION:
            return self._decides_level_contradiction(caller, challenge)
        department_id = department_of(challenge)
        if department_id is not None:
            if challenge.raised_by == caller.member_id:
                return None
            if self._departments.leads(caller.member, department_id):
                return "department_lead"
            if (caller.member.is_owner or caller.member.is_admin) and not self._departments.has_leads(department_id):
                return "admin"
            return None
        if challenge.foundation is not None:
            if challenge.raised_by == caller.member_id:
                return None
            if self._leads_the_challenged(caller, challenge):
                return "lead"
            project_id = project_in(challenge.target_path)
            if project_id is not None and self._identity.keeps(caller.member, project_id, challenge.foundation):
                return "keeper"
            return None
        if challenge.target_author == caller.member_id:
            return "author"
        if caller.member_id not in raisers:
            if self._leads_the_challenged(caller, challenge):
                return "lead"
            if caller.member.is_owner or caller.member.is_admin:
                return "admin"
        if self._identity.is_removed(caller.company, challenge.target_author):
            return "author_left"
        if self._clock() - challenge.raised_at >= timedelta(days=self._settings.challenge_fallback_days):
            return "fallback"
        return None

    def _decides_level_contradiction(self, caller: Caller, challenge: Challenge) -> DecidesAs | None:
        """Only the narrower level's leads decide a level contradiction: its project's leads, or its department's,
        and the company's admins once a department has no lead left."""
        assert challenge.challenger_path is not None
        narrower = locate(challenge.challenger_path)
        if narrower.department_id is not None:
            if self._departments.leads(caller.member, narrower.department_id):
                return "department_lead"
            if (caller.member.is_owner or caller.member.is_admin) and not self._departments.has_leads(
                narrower.department_id
            ):
                return "admin"
            return None
        return "lead" if narrower.project_id in self._identity.leads_of(caller.member) else None

    def _leads_the_challenged(self, caller: Caller, challenge: Challenge) -> bool:
        """Whether the member leads the project the challenged memory is in. The challenging memory's project gives
        nobody standing."""
        project_id = project_in(challenge.target_path)
        return project_id is not None and project_id in self._identity.leads_of(caller.member)

    def require_decider(self, caller: Caller, challenge: Challenge, raisers: tuple[str, ...]) -> DecidesAs:
        """The capacity this member decides the challenge in, given who raised it; refused when it isn't theirs to
        decide."""
        decides_as = self.decides_as(caller, challenge, raisers)
        if decides_as is not None:
            return decides_as
        if challenge.kind == LEVEL_CONTRADICTION:
            whose = "the department, or an admin once it has no lead left" if challenge.level == "department" else "the project"
            raise Refused(f"Only a lead of {whose} whose memory it is decides level contradiction {challenge.id}.")
        if department_of(challenge) is not None:
            raise Refused(
                f"Only a department lead decides challenge {challenge.id}, a promotion into its department memory: not "
                "the member who raised it, and an admin only once the department has no lead left."
            )
        if challenge.foundation is not None:
            if challenge.raised_by == caller.member_id:
                raise Refused(
                    f"You raised challenge {challenge.id}, so you can't decide it. A lead of the project or a keeper of "
                    f"the {challenge.foundation} foundation decides a challenge to it."
                )
            raise Refused(
                f"Only a lead of the project or a keeper of the {challenge.foundation} foundation decides a challenge to "
                "it: not its author, not an admin who isn't a lead, and not any member however long it has been open."
            )
        days = self._settings.challenge_fallback_days
        in_project = project_in(challenge.target_path) is not None
        if caller.member_id in raisers and (
            caller.member.is_owner or caller.member.is_admin or self._leads_the_challenged(caller, challenge)
        ):
            raise Refused(
                f"You raised challenge {challenge.id}, so you can't decide it as a project lead or an admin. "
                f"{challenge.target_author}, the author of the challenged memory, "
                f"{'another project lead or an admin' if in_project else 'or another admin'} can; "
                f"anyone may once it has been open for {days} days."
            )
        others = "a lead of its project and the company's admins" if in_project else "and the company's admins"
        raise Refused(
            f"Only {challenge.target_author}, the author of the challenged memory, {others} can decide this challenge "
            f"until it has been open for {days} days."
        )

    def tell_author(
        self, caller: Caller, challenge: Challenge, raisers: tuple[str, ...], decides_as: DecidesAs, decision: str
    ) -> None:
        """Tell the challenged memory's author that someone else decided a challenge against it, and in what
        capacity. An author who decided it themselves, or who has left, is told nothing, and nor is one among its
        `raisers`, who is told as a raiser."""
        if decides_as in ("author", "author_left") or challenge.target_author in raisers:
            return
        if challenge.kind == LEVEL_CONTRADICTION:
            return  # the broader memory stays as it is, whichever way it is decided
        if decision == "rejected":
            outcome = "your memory stands as it is"
        else:
            outcome = "your memory is now retired" if challenge.challenger_path is None else "your memory is now superseded"
        self.tell(
            caller.company,
            challenge.target_author,
            f"Challenge {challenge.id} by {challenge.raised_by} against your memory {challenge.target_path} was "
            f"{decision} by {caller.member_id}, deciding {self._capacity(decides_as)}: {outcome}.",
        )

    def _capacity(self, decides_as: DecidesAs) -> str:
        """The capacity in words, to follow "decide" or "deciding"."""
        if decides_as == "fallback":
            return f"as any member may after {self._settings.challenge_fallback_days} days"
        return {
            "author": "as its author",
            "lead": "as a project lead",
            "keeper": "as a keeper of the foundation",
            "admin": "as an admin",
            "author_left": "as any member may once its author has left the company",
            "department_lead": "as a department lead",
        }[decides_as]

    # What sessions are told

    def briefing_notices(self, caller: Caller) -> list[str]:
        """Every open challenge the member can decide, and news not yet delivered."""
        return [part for part in (self._render(caller, self.waiting_for(caller)), self._news(caller)) if part]

    def prompt_notices(self, caller: Caller) -> str | None:
        """Challenges against the member's memories not yet shown on a prompt (with the others against the same
        memory), and news not yet delivered."""
        mine = [
            c
            for c in self.open_challenges(caller.company)
            if c.target_author == caller.member_id and c.foundation is None and c.kind not in (PROMOTE, LEVEL_CONTRADICTION)
        ]
        with self._db.transaction() as conn:
            fresh_targets = {
                row["target_path"]
                for row in conn.execute(
                    "SELECT target_path FROM challenges WHERE id = ANY(%s) AND author_notified_at IS NULL",
                    ([c.id for c in mine],),
                )
            }
            shown = [c for c in mine if c.target_path in fresh_targets]
            if shown:
                conn.execute(
                    "UPDATE challenges SET author_notified_at = %s WHERE id = ANY(%s)", (self._clock(), [c.id for c in shown])
                )
        told = [Waiting(c, "author") for c in shown]
        text = "\n\n".join(part for part in (self._render(caller, told), self._news(caller)) if part)
        return f"<shared-memory-notices>\n{text}\n</shared-memory-notices>" if text else None

    def _render(self, caller: Caller, waiting: list[Waiting]) -> str | None:
        ordinary = [
            one
            for one in waiting
            if one.challenge.foundation is None and one.challenge.kind not in (PROMOTE, LEVEL_CONTRADICTION)
        ]
        foundations = [one for one in waiting if one.challenge.foundation is not None]
        departments = [one for one in waiting if one.challenge.kind == PROMOTE]
        levels = [one.challenge for one in waiting if one.challenge.kind == LEVEL_CONTRADICTION]
        parts = [
            self._render_group(caller, ordinary, "[challenges waiting for your decision]"),
            self._render_group(caller, foundations, "[foundation challenges waiting for your decision]"),
            self._render_group(caller, departments, "[department challenges waiting for your decision]"),
            self._render_levels(caller, levels),
        ]
        return "\n\n".join(part for part in parts if part) or None

    def _render_group(self, caller: Caller, waiting: list[Waiting], heading: str) -> str | None:
        if not waiting:
            return None
        lines = [heading]
        evidence = self._evidence([one.challenge.id for one in waiting if one.challenge.kind == DOUBT])
        for target_path in dict.fromkeys(one.challenge.target_path for one in waiting):
            first = next(one.challenge for one in waiting if one.challenge.target_path == target_path)
            if first.foundation is not None and first.kind == "add":
                lines.append(f"The {first.foundation} foundation ({target_path}):")
            elif first.kind == PROMOTE:
                lines.append(f"{self.department_name(first)} department memory ({target_path}):")
            elif first.foundation is not None:
                lines.append(f"{self._title(caller.company, target_path)} ({target_path}), in the {first.foundation} foundation:")
            else:
                lines.append(f"{self._title(caller.company, target_path)} ({target_path}):")
            for one in (one for one in waiting if one.challenge.target_path == target_path):
                c = one.challenge
                # A challenge against the member's own memory needs no reason; any other says why it is theirs.
                whose = "" if one.decides_as == "author" else f", yours to decide {self._capacity(one.decides_as)}"
                if c.kind == DOUBT:
                    lines.extend(_doubt_lines(c, whose, evidence.get(c.id, ())))
                    continue
                if c.kind == "add":
                    line = f"- Challenge {c.id} by {c.raised_by}{whose}: add {self._replacement(caller, c)} to the {c.foundation} foundation"
                    line += f" — reasoning: {c.reasoning}" if c.reasoning else "."
                elif c.kind == PROMOTE:
                    line = f"- Challenge {c.id} by {c.raised_by}{whose}: promote {self._replacement(caller, c)}"
                    line += f" — reasoning: {c.reasoning}" if c.reasoning else "."
                elif c.challenger_path is None:
                    line = f"- Challenge {c.id} by {c.raised_by}{whose}: retire it"
                    line += f" — reasoning: {c.reasoning}" if c.reasoning else "."
                else:
                    line = f"- Challenge {c.id} by {c.raised_by}{whose}: supersede it with {self._replacement(caller, c)}"
                    if c.reasoning:
                        line += f" — reasoning: {c.reasoning}"
                lines.append(line)
        lines.append(
            "Show these to the member and record their decision with decide_challenge (accept or reject). "
            "At most one challenge per memory can be accepted. Where the memory is another member's, its author is "
            "told who decided and in what capacity."
        )
        if evidence:
            lines.append(
                "A doubt says the memory may be wrong: check it against the code with the member. Where they disagree, "
                "the code holds."
            )
        return "\n".join(lines)

    def _render_levels(self, caller: Caller, waiting: list[Challenge]) -> str | None:
        """Each waiting level contradiction with its age, as a reminder: present only while one waits."""
        if not waiting:
            return None
        lines = ["[level contradictions waiting for your decision]"]
        for c in waiting:
            assert c.challenger_path is not None
            days = (self._clock() - c.raised_at).days
            age = "today" if days < 1 else "1 day" if days == 1 else f"{days} days"
            narrower, broader = locate(c.challenger_path).level, locate(c.target_path).level
            lines.append(
                f'- Level contradiction {c.id}, waiting {age}: "{self._title(caller.company, c.challenger_path)}" '
                f'({c.challenger_path}, {narrower} memory) holds over "{self._title(caller.company, c.target_path)}" '
                f"({c.target_path}, {broader} memory)."
            )
        lines.append("Show the member both. decide_challenge: keep_exception with a reason, or follow (retires the narrower).")
        return "\n".join(lines)

    def _replacement(self, caller: Caller, challenge: Challenge) -> str:

        """The challenging memory, titled and summarised when it can still be read."""
        assert challenge.challenger_path is not None
        try:
            challenger = self._store.read(caller.company, PurePosixPath(challenge.challenger_path))
        except Refused:
            return challenge.challenger_path
        return f'"{challenger.title}" ({challenge.challenger_path}): {challenger.summary}'

    def department_name(self, challenge: Challenge) -> str:
        """The name of the department a promotion into department memory asks to join, or its ID once removed."""
        department_id = department_of(challenge) or challenge.target_path
        found = self._departments.named(department_id)
        return department_id if found is None else found.name

    def _title(self, company: str, path: str) -> str:
        try:
            return self._store.read(company, PurePosixPath(path)).title
        except Refused:
            return path

    def _news(self, caller: Caller) -> str | None:
        with self._db.transaction() as conn:
            rows = conn.execute(
                "UPDATE notices SET delivered_at = %s WHERE team = %s AND member_id = %s AND delivered_at IS NULL"
                " RETURNING id, text",
                (self._clock(), caller.company, caller.member_id),
            ).fetchall()
        texts = [row["text"] for row in sorted(rows, key=lambda row: row["id"])]
        return "[shared memory news]\n" + "\n".join(f"- {text}" for text in texts) if texts else None

    def told(self, caller: Caller, *, days: int, limit: int) -> list[dict[str, Any]]:
        """What this member has been told, newest first, for the console: every notice still waiting for their next
        session, and those of the last `days` days that a session has already had. Only a read: a notice shown here
        still waits to be delivered, so the member's coding agent is told too."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT id, text, created_at FROM notices WHERE team = %s AND member_id = %s"
                " AND (delivered_at IS NULL OR created_at >= %s) ORDER BY id DESC LIMIT %s",
                (caller.company, caller.member_id, self._clock() - timedelta(days=days), limit),
            ).fetchall()
        return [{"notice_id": row["id"], "text": row["text"], "created_at": row["created_at"]} for row in rows]


def _reason(reason: str, code_reference: str | None, quoted_line: str | None) -> Reason:
    """The reason a doubt names, refused unless it is one of the two; only contradicts_code quotes code."""
    for named in REASONS:
        if reason == named:
            if named == "misled" and (code_reference or quoted_line):
                raise Refused("Only a doubt with the reason contradicts_code quotes code; misled takes none.")
            return named
    raise Refused(f"A doubt names its reason: {' or '.join(REASONS)}.")


def _doubt_lines(challenge: Challenge, whose: str, evidence: tuple[Evidence, ...]) -> list[str]:
    """A doubt as a briefing or prompt shows it: its reason and how many members raised it, then each piece of
    evidence."""
    count = len(_members(evidence))
    says = "says" if count == 1 else "say"
    lines = [f"- Challenge {challenge.id}, a doubt{whose}: {count} {says} {_REASON_IN_WORDS[challenge.reason or '']}."]
    for each in evidence:
        line = f"  - {each.member_id}"
        if each.code_reference is not None:
            line += f" quotes {each.code_reference}: {each.code_reference.quoted_line}"
        line += f" — reasoning: {each.reasoning}" if each.reasoning else ("" if each.code_reference else ".")
        lines.append(line)
    return lines


def _members(evidence: Iterable[Evidence]) -> tuple[str, ...]:
    """The members this evidence came from, first raiser first, each once."""
    return tuple(dict.fromkeys(each.member_id for each in evidence))


def _show_the_author_again(conn: Conn, challenge_id: int) -> None:
    """Ask the author's next prompt to show a doubt again, a raise having joined it with new evidence."""
    conn.execute("UPDATE challenges SET author_notified_at = NULL WHERE id = %s", (challenge_id,))


def move_paths(conn: Conn, old: str, new: str) -> None:
    """Keep the challenges to and from the memories under the folder `old` on them at the folder `new`, where they
    moved (`company_move.py`)."""
    moved = moved_prefix(old, new)
    conn.execute("UPDATE challenges SET target_path = %(new)s || substr(target_path, %(after)s) WHERE target_path LIKE %(old)s", moved)
    conn.execute(
        "UPDATE challenges SET challenger_path = %(new)s || substr(challenger_path, %(after)s)"
        " WHERE challenger_path LIKE %(old)s",
        moved,
    )


def rename_level(conn: Conn, old: str, new: str) -> None:
    """Say the level `old` as `new` in the challenges: company memory's level was `team` before the
    rename (`company_move.py`)."""
    conn.execute("UPDATE challenges SET level = %s WHERE level = %s", (new, old))
