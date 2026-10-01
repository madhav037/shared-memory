"""How memory changes level: promoting, superseding, exceptions, retiring, and deciding challenges."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any

from shared_memory.audit import (
    CHALLENGE_DECIDED,
    MEMORY_PROMOTED,
    MEMORY_RETIRED,
    MEMORY_SUPERSEDED,
    Audit,
)
from shared_memory.challenges import Challenge, Challenges, project_of
from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.identity import NAME_PATTERN, Caller, Identity, Project
from shared_memory.index import SearchIndex
from shared_memory.memory import Area, Level, Location, Memory, area_of, level_folder, locate
from shared_memory.service import committer, describe
from shared_memory.store import Change, MemoryStore
from shared_memory.validation import refuse_secret

SCHEMA = """
CREATE TABLE IF NOT EXISTS promotions (
    reference TEXT PRIMARY KEY,
    team TEXT NOT NULL,
    member_id TEXT NOT NULL,
    path TEXT NOT NULL,
    level TEXT NOT NULL,
    similar_paths TEXT[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS imports (
    team TEXT NOT NULL,
    path TEXT NOT NULL,
    author TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (team, path)
);
"""

RESOLUTIONS = ("supersede", "keep_both", "cancel")
SOURCE_LIMIT = 300


@dataclass(frozen=True)
class Imported:
    """What an imported memory is promoted with (ADR-0016): the member who wrote the passage it was cut from, who
    becomes its author, and its source, written repository:path. It is kept by the personal memory's path from
    promote's first call until the memory moves, so it holds through the similar-memory check and a challenge."""

    author: str
    source: str


class Lifecycle:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        store: MemoryStore,
        index: SearchIndex,
        identity: Identity,
        challenges: Challenges,
        audit: Audit,
        clock: Clock,
    ) -> None:
        self._settings = settings
        self._db = db
        self._store = store
        self._index = index
        self._identity = identity
        self._challenges = challenges
        self._audit = audit
        self._clock = clock
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)

    # Promoting

    def promote(
        self,
        caller: Caller,
        path: str,
        level: str,
        reference: str | None = None,
        resolutions: dict[str, str] | None = None,
        reasoning: str | None = None,
        author: str | None = None,
        imported_from: str | None = None,
    ) -> dict[str, Any]:
        location, target, promoted_by, project = self._promotable(caller, path, level)
        self._keep_import(caller, location, project, author, imported_from, first_call=reference is None)
        if reference is None:
            proposal = self._similar(caller, path, location, level, project)
            if proposal is None:
                return self._move(caller, location, target, promoted_by=promoted_by)
            return proposal

        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT similar_paths FROM promotions WHERE reference = %s AND team = %s AND member_id = %s"
                " AND path = %s AND level = %s",
                (reference, caller.team, caller.member_id, path, level),
            ).fetchone()
        if row is None:
            raise Refused("Unknown promotion reference for this memory. Call promote again without a reference.")
        chosen = dict(resolutions or {})
        if set(chosen) != set(row["similar_paths"]):
            raise Refused(
                "Give a resolution for every similar memory (supersede, keep_both or cancel): "
                + ", ".join(row["similar_paths"])
            )
        unknown = sorted({value for value in chosen.values() if value not in RESOLUTIONS})
        if unknown:
            raise Refused(f"Unknown resolution {unknown[0]!r}: use supersede, keep_both or cancel.")
        if "cancel" in chosen.values():
            self._forget(reference)
            self._forget_import(caller.team, location.path)
            return {"status": "cancelled", "path": path}
        supersede: str | None = None
        exception_to: str | None = None
        challenged: tuple[str, Memory] | None = None
        for similar_path in sorted(p for p, resolution in chosen.items() if resolution == "supersede"):
            similar_location = locate(similar_path)
            other = self._store.read(caller.team, similar_location.path)
            if other.status != "active":
                raise Refused(f"{similar_path} is no longer active. Call promote again without a reference.")
            if target == "project" and similar_location.level == "team":
                if exception_to is not None:
                    raise Refused("A project memory can be an exception to only one team memory.")
                exception_to = similar_path
            elif other.author == caller.member_id:
                if supersede is not None:
                    raise Refused("A promotion can supersede only one memory. Retire the others first.")
                supersede = similar_path
            else:
                if challenged is not None:
                    raise Refused("A promotion can challenge only one memory at a time.")
                challenged = (similar_path, other)
        if challenged is not None and (supersede is not None or exception_to is not None):
            raise Refused(
                "A promotion that challenges another author's memory can't also supersede or be an exception. "
                "Challenge first; once it's accepted, promote the rest."
            )
        self._forget(reference)
        if challenged is not None:
            challenge_id = self._challenges.raise_challenge(
                caller,
                kind="supersede",
                target_path=challenged[0],
                target_author=challenged[1].author,
                level=target,
                challenger_path=str(location.path),
                promoted_by=promoted_by,
                reasoning=reasoning,
            )
            return self._challenge_raised(challenge_id, challenged[0], challenged[1].author)
        result = self._move(
            caller, location, target, supersede=supersede, exception_to=exception_to, promoted_by=promoted_by
        )
        if supersede is not None:
            self._challenges.close_all_against(
                caller.team, supersede, caller.member_id, f"its author superseded it with {result['path']}."
            )
        return result

    def similar_before_promoting(
        self, caller: Caller, path: str, level: str, author: str | None = None, imported_from: str | None = None
    ) -> dict[str, Any] | None:
        """Promote's first call up to the move: the similar memories to judge, or None when there are none.

        It saves no memory, only a pending promotion, so it need not wait a turn among saves. A caller given None
        promotes with no reference, which searches again and moves the memory in its turn.
        """
        location, _, _, project = self._promotable(caller, path, level)
        self._keep_import(caller, location, project, author, imported_from, first_call=True)
        return self._similar(caller, path, location, level, project)

    # Promoting an imported memory in its writer's name

    def _keep_import(
        self,
        caller: Caller,
        location: Location,
        project: Project,
        author: str | None,
        imported_from: str | None,
        *,
        first_call: bool,
    ) -> None:
        """Keep the author and source a promotion names until its memory moves. A promotion starting again without
        them forgets what an earlier one kept, so a memory is never promoted in a name its last promote didn't give."""
        if author is None and imported_from is None:
            if first_call:
                self._forget_import(caller.team, location.path)
            return
        imported = self._imported(caller, location, project, author, imported_from)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO imports (team, path, author, source, created_at) VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (team, path) DO UPDATE SET author = EXCLUDED.author, source = EXCLUDED.source,"
                " created_at = EXCLUDED.created_at",
                (caller.team, str(location.path), imported.author, imported.source, self._clock()),
            )

    def _imported(
        self, caller: Caller, location: Location, project: Project, author: str | None, imported_from: str | None
    ) -> Imported:
        """Refuse an author who can't be named; otherwise the member to name and the source to record."""
        if author is None or imported_from is None:
            raise Refused(
                "An imported memory is promoted with both author, the member who wrote the passage it was cut from, "
                "and imported_from, the file it came from. Pass both, or neither to stay its author yourself."
            )
        if location.member_id != caller.member_id:
            raise Refused("Only a memory you imported yourself can be promoted in its writer's name.")
        source = imported_from.strip()
        repository, _, file = source.partition(":")
        if not NAME_PATTERN.match(repository) or not file.strip() or "\n" in source or len(source) > SOURCE_LIMIT:
            raise Refused(
                f"imported_from {imported_from!r} must be one file written as repository:path, for example "
                "billing-api:CLAUDE.md."
            )
        refuse_secret(source, "imported_from")
        named = author.strip()
        if named.startswith("@"):
            member_id = self._identity.member_with_github(caller, named)
            if member_id is None:
                raise Refused(
                    f"No member of your team signs in with the GitHub account {named}, so they can't be the author. "
                    "Promote without author and imported_from, and name the original writer in the memory's body."
                )
        else:
            member_id = named
        if member_id == caller.member_id:
            raise Refused("You are already its author: promote it without author and imported_from.")
        self._identity.member_reaching(caller, project.project_id, member_id)
        return Imported(member_id, source)

    def _kept_import(self, team: str, path: PurePosixPath) -> Imported | None:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT author, source FROM imports WHERE team = %s AND path = %s", (team, str(path))
            ).fetchone()
        return None if row is None else Imported(row["author"], row["source"])

    def _forget_import(self, team: str, path: PurePosixPath) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM imports WHERE team = %s AND path = %s", (team, str(path)))

    def _tell_author(self, team: str, imported: Imported, importer: str, title: str, path: PurePosixPath, level: Level) -> None:
        """Tell a member, in their next briefing, that a memory now stands in their name."""
        self._challenges.tell(
            team,
            imported.author,
            f'{importer} promoted a memory in your name: "{title}" ({path}), imported from {imported.source}, is now '
            f"{level} memory and you are its author. If it is wrong, retire it or supersede it.",
        )

    def _promotable(self, caller: Caller, path: str, level: str) -> tuple[Location, Level, str | None, Project]:
        """Refuse a promotion that can't happen; otherwise where the memory is, its new level and who promotes it."""
        project = caller.require_project()
        if level not in ("project", "team"):
            raise Refused(f"Promote into 'project' or 'team' memory, not {level!r}.")
        location = locate(path)
        self._store.read(caller.team, location.path)  # refuses a memory that isn't there
        if location.level != "personal":
            raise Refused(f"This is already {location.level} memory. Only personal memory can be promoted.")
        promoted_by: str | None = None
        if location.member_id != caller.member_id:
            if location.member_id is None or not self._identity.is_removed(caller.team, location.member_id):
                raise Refused(
                    "You can only promote your own personal memory, or the personal memory of a member who has "
                    "been removed from the team."
                )
            promoted_by = caller.member_id
        if location.project_id != project.project_id:
            raise Refused("This memory belongs to another project. Promote it from a session in that project.")
        waiting = self._challenges.open_challenges(caller.team, challenger_paths=[str(location.path)])
        if waiting:
            raise Refused(f"This memory is waiting on challenge {waiting[0].id}. Wait for it to be decided.")
        target: Level = "team" if level == "team" else "project"
        return location, target, promoted_by, project

    def _similar(
        self, caller: Caller, path: str, location: Location, level: str, project: Project
    ) -> dict[str, Any] | None:
        similar = self._index.similar(
            caller.team, location.path, project_id=project.project_id, threshold=self._settings.similar_threshold
        )
        if not similar:
            return None
        reference = secrets.token_urlsafe(12)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO promotions (reference, team, member_id, path, level, similar_paths, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (reference, caller.team, caller.member_id, path, level, [p for p, _ in similar], self._clock()),
            )
        return {
            "status": "similar_memories",
            "reference": reference,
            "similar": [
                {**describe(PurePosixPath(p), self._store.read(caller.team, PurePosixPath(p))), "similarity": round(s, 3)}
                for p, s in similar
            ],
            "next": "Judge whether each similar memory contradicts this one, ask the member, then call promote "
            "again with this reference and a resolution (supersede, keep_both or cancel) for every similar memory.",
        }

    def _forget(self, reference: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM promotions WHERE reference = %s", (reference,))

    def _move(
        self,
        caller: Caller,
        location: Location,
        target: Level,
        *,
        supersede: str | None = None,
        exception_to: str | None = None,
        promoted_by: str | None = None,
        reason: str = "Promote",
    ) -> dict[str, Any]:
        """Move a personal memory into project or team memory, reading it in the same save that moves it.

        A memory moved or deleted by a save that went first is refused here, so it is never promoted twice. An imported
        memory whose promotion named its writer moves in that member's name, with its importer and source recorded.
        """
        imported = self._kept_import(caller.team, location.path)
        # Every area the move touches, known before it takes a turn: where the memory is, where it goes, and the
        # memories it supersedes or is an exception to.
        areas = {area_of(location.path), Area(target, location.project_id if target == "project" else None)}
        areas |= {area_of(PurePosixPath(path)) for path in (supersede, exception_to) if path is not None}
        with self._store.change(caller.team, committer(caller), areas=[a for a in areas if a is not None]) as change:
            memory = change.read(location.path)
            change.message = f"{reason}: {memory.title}"
            folder = level_folder(target, memory.type, location.project_id)
            if location.topic:
                folder = folder / location.topic
            new_path = change.new_path(folder, location.path.stem)
            change.delete(location.path)
            moved = replace(
                memory, replaces=supersede, exception_to=exception_to, promoted_by=promoted_by or memory.promoted_by
            )
            names: dict[str, str] = {}
            if imported is not None:
                names = {"author": imported.author, "imported_by": memory.author, "imported_from": imported.source}
                moved = replace(moved, author=imported.author, imported_by=memory.author, imported_from=imported.source)
            change.write(new_path, moved)
            if supersede is not None:
                old = PurePosixPath(supersede)
                change.write(old, replace(self._active(change, old), status="superseded", superseded_by=str(new_path)))

            def audited() -> None:
                where = location.project_id
                self._audit.memory(
                    caller, MEMORY_PROMOTED, str(new_path), project_id=where, level=target, was=str(location.path),
                    **names,
                )  # fmt: skip
                if supersede is not None:
                    self._audit.memory(caller, MEMORY_SUPERSEDED, supersede, project_id=where, by=str(new_path))

            def credited() -> None:
                if imported is not None:
                    self._tell_author(caller.team, imported, memory.author, memory.title, new_path, target)
                    self._forget_import(caller.team, location.path)

            change.also(audited)
            change.also(credited)
        return {"status": "promoted", "path": str(new_path)}

    @staticmethod
    def _active(change: Change, path: PurePosixPath) -> Memory:
        """A memory about to change, refused if a save that went first has already retired or superseded it."""
        memory = change.read(path)
        if memory.status != "active":
            raise Refused(f"{path} is already {memory.status}.")
        return memory

    @staticmethod
    def _challenge_raised(challenge_id: int, target_path: str, author: str) -> dict[str, Any]:
        return {
            "status": "challenge_raised",
            "challenge_id": challenge_id,
            "challenges": target_path,
            "author": author,
            "next": f"{author} decides. Until then the challenged memory stays active.",
        }

    # Retiring

    def retire(self, caller: Caller, path: str, reasoning: str | None = None) -> dict[str, Any]:
        caller.require_project()
        caller.require_reach(path)
        location = locate(path)
        memory = self._store.read(caller.team, location.path)
        if location.level == "personal":
            raise Refused("Personal memory isn't retired. If it's yours and no longer true, remove it with delete_memory.")
        if memory.status != "active":
            raise Refused(f"This memory is already {memory.status}.")
        areas = [area for area in [area_of(location.path)] if area is not None]
        if memory.author != caller.member_id:
            challenge_id = self._challenges.raise_challenge(
                caller,
                kind="retire",
                target_path=str(location.path),
                target_author=memory.author,
                level=location.level,
                reasoning=reasoning,
            )
            return self._challenge_raised(challenge_id, str(location.path), memory.author)
        with self._store.change(caller.team, committer(caller), f"Retire: {memory.title}", areas=areas) as change:
            change.write(location.path, replace(self._active(change, location.path), status="retired"))
            change.also(lambda: self._audit.memory(caller, MEMORY_RETIRED, str(location.path)))
        self._challenges.close_all_against(caller.team, str(location.path), caller.member_id, "its author retired it.")
        return {"status": "retired", "path": str(location.path)}

    def retire_fixed(self, caller: Caller, path: str, reasoning: str) -> dict[str, Any] | None:
        """Retire a known issue whose card is done, as retire does: at once when the caller wrote it, as a challenge
        to its author otherwise. None when it is already retired or superseded, or gone: there is nothing to do.
        A challenge the caller already raised to retire it, still open, is given back rather than raised again."""
        location = locate(path)
        if not self._store.exists(caller.team, location.path):
            return None
        memory = self._store.read(caller.team, location.path)
        if memory.status != "active":
            return None
        for challenge in self._challenges.open_challenges(caller.team, target_path=str(location.path)):
            if challenge.kind == "retire" and challenge.raised_by == caller.member_id:
                return self._challenge_raised(challenge.id, str(location.path), memory.author)
        try:
            return self.retire(caller, path, reasoning)
        except Refused:
            # A save that went first retired or superseded it after it was read: nothing is left to do.
            if self._store.read(caller.team, location.path).status != "active":
                return None
            raise

    # Deciding challenges

    def decide_challenge(self, caller: Caller, challenge_id: int, decision: str) -> dict[str, Any]:
        caller.require_project()
        if decision not in ("accept", "reject"):
            raise Refused("Decide a challenge with 'accept' or 'reject'.")
        challenge = self._challenges.open_challenge(caller.team, challenge_id)
        if challenge is None:
            raise Refused(f"There is no open challenge {challenge_id} in your team.")
        caller.require_reach(challenge.target_path)
        caller.require_reach(challenge.challenger_path)
        self._challenges.require_decider(caller, challenge)
        decider = caller.member_id

        if decision == "reject":
            self._challenges.decide(challenge, "rejected", decider)
            self._decided(caller, challenge, "rejected")
            self._challenges.tell(
                caller.team,
                challenge.raised_by,
                f"Your challenge {challenge.id} against {challenge.target_path} was rejected by {decider}. "
                "Your memory stays personal memory.",
            )
            return {"status": "rejected", "challenge_id": challenge.id}

        target_path = PurePosixPath(challenge.target_path)
        target = self._store.read(caller.team, target_path)
        if target.status != "active":
            raise Refused(f"{challenge.target_path} is no longer active, so this challenge can't be accepted.")
        if challenge.challenger_path is None:
            result, outcome = self._accept_retire(caller, challenge, target_path, target)
        else:
            result, outcome = self._accept_supersede(caller, challenge, challenge.challenger_path)
        self._challenges.decide(challenge, "accepted", decider)
        self._decided(caller, challenge, "accepted")
        self._challenges.tell(caller.team, challenge.raised_by, outcome)
        self._challenges.close_all_against(
            caller.team,
            challenge.target_path,
            decider,
            f"challenge {challenge.id} by {challenge.raised_by} was accepted instead.",
        )
        return result

    def _decided(self, caller: Caller, challenge: Challenge, decision: str) -> None:
        self._audit.memory(
            caller, CHALLENGE_DECIDED, challenge.target_path, project_id=project_of(challenge),
            challenge_id=challenge.id, decision=decision, challenge=challenge.kind,
        )  # fmt: skip

    def _accept_supersede(self, caller: Caller, challenge: Challenge, challenger_path: str) -> tuple[dict[str, Any], str]:
        challenger_location = locate(challenger_path)
        if not self._store.exists(caller.team, challenger_location.path):
            self._challenges.decide(challenge, "withdrawn", caller.member_id, "The challenging memory was deleted.")
            raise Refused("The challenging memory no longer exists, so the challenge has been withdrawn.")
        level: Level = "team" if challenge.level == "team" else "project"
        moved = self._move(
            caller,
            challenger_location,
            level,
            supersede=challenge.target_path,
            promoted_by=challenge.promoted_by,
            reason=f"Accept challenge {challenge.id}",
        )
        outcome = (
            f"Your challenge {challenge.id} was accepted by {caller.member_id}: "
            f"your memory is now {level} memory at {moved['path']}."
        )
        return {"status": "accepted", "challenge_id": challenge.id, "path": moved["path"]}, outcome

    def _accept_retire(
        self, caller: Caller, challenge: Challenge, target_path: PurePosixPath, target: Memory
    ) -> tuple[dict[str, Any], str]:
        message = f"Accept challenge {challenge.id}: retire {target.title}"
        areas = [area for area in [area_of(target_path)] if area is not None]
        with self._store.change(caller.team, committer(caller), message, areas=areas) as change:
            change.write(target_path, replace(self._active(change, target_path), status="retired"))
            where = project_of(challenge)
            change.also(
                lambda: self._audit.memory(
                    caller, MEMORY_RETIRED, str(target_path), project_id=where, challenge_id=challenge.id
                )
            )
        outcome = f"Your challenge {challenge.id} was accepted by {caller.member_id}: {challenge.target_path} is retired."
        return {"status": "accepted", "challenge_id": challenge.id, "retired": challenge.target_path}, outcome
