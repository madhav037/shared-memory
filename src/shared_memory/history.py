"""What a memory said before: reading the memory folder's git history (ADR-0003).

Every question here is answered by parsing `git log` and `git show` output, so its failure modes are git's, not the
filesystem's. `store.py` writes the files; this reads what the writing left behind, and following a memory back
through promotion — when its file moved from a member's folder to the shared one — is the delicate part.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from shared_memory.errors import Refused
from shared_memory.store import confine


@dataclass(frozen=True)
class Version:
    """One version of a memory in the memory folder's history."""

    commit: str
    at: datetime
    author: str
    name: str
    message: str
    agent: str | None = None


def _check_commit(commit: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{7,64}", commit):
        raise Refused(f"{commit!r} is not a version of anything.")


class MemoryHistory:
    """Every version of a memory, read out of the memory folder's git repository."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self._root), *args], env=dict(os.environ), capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout

    def versions(self, team: str, path: PurePosixPath) -> list[Version]:
        """Every version of one memory, newest first: who wrote it, when, and what the change was called.

        It follows the memory back through promotion, when its file moved from a member's folder to the shared one,
        so the trail starts where the memory was first written rather than where it now lives.
        """
        return [version for version, _ in self._trail(team, path)]

    def _trail(self, team: str, path: PurePosixPath) -> list[tuple[Version, str]]:
        """Each version of a memory with the path its file had at that version.

        Promotion moves a memory's file to another folder under the same name, in one commit. So where a file came
        into being in a commit that also removed a file of the same name from the team's folder, that file is where
        the memory was before, and its history continues there. Git's own rename guessing is not used: memory files
        are short and alike, and it would join the histories of different memories.
        """
        trail: list[tuple[Version, str]] = []
        where: str | None = self._inside_team(team, path)
        until: str | None = None
        while where is not None:
            revision = [f"{until}^"] if until else []
            printed = self._git(
                "log", *revision, "--no-renames", "--name-status",
                "--format=%x1e%H%x1f%aI%x1f%ae%x1f%an%x1f%s%x1f%(trailers:key=Coding-Agent,valueonly,separator=%x2C)",
                "--", where,
            )  # fmt: skip
            born: str | None = None
            for record in printed.split("\x1e"):
                lines = [line for line in record.splitlines() if line.strip()]
                if not lines:
                    continue
                commit, at, email, name, message, agent = lines[0].split("\x1f")
                version = Version(
                    commit=commit,
                    at=datetime.fromisoformat(at),
                    author=email.split("@")[0],
                    name=name,
                    message=message,
                    agent=agent.strip() or None,
                )
                trail.append((version, where))
                if any(line.startswith("A\t") for line in lines[1:]):
                    born = commit
                    break
            if born is None:
                break
            where, until = self._moved_from(team, born, where), born
        return trail

    def _moved_from(self, team: str, commit: str, where: str) -> str | None:
        """The file a memory was moved from when this commit created it, if it was moved rather than written."""
        name = PurePosixPath(where).name
        changes = self._git("show", "--no-renames", "--name-status", "--format=", commit)
        for line in changes.splitlines():
            status, _, changed = line.partition("\t")
            if status == "D" and changed.startswith(f"{team}/") and PurePosixPath(changed).name == name:
                return changed
        return None

    def _where_then(self, team: str, path: PurePosixPath, commit: str) -> str:
        """The path this memory's file had at one version, which is not where it lives now once it was promoted."""
        for version, where in self._trail(team, path):
            if version.commit.startswith(commit):
                return where
        return self._inside_team(team, path)

    def text_at(self, team: str, path: PurePosixPath, commit: str) -> str:
        """The memory's text as it was at one version."""
        _check_commit(commit)
        where = self._where_then(team, path, commit)
        try:
            return self._git("show", f"{commit}:{where}")
        except RuntimeError:
            raise Refused(f"There is no version {commit!r} of {str(path)!r}.") from None

    def _inside_team(self, team: str, path: PurePosixPath) -> str:
        """The path git knows this memory by, confined to the team's own folder."""
        confine(self._root, team, path)  # refuses anything outside the team's folder
        return str(PurePosixPath(team) / path)
