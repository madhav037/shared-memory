"""The memory folder: memory files on disk, the source of truth, with every change committed to git (ADR-0002, ADR-0003)."""

from __future__ import annotations

import os
import re
import subprocess
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

from shared_memory.errors import Refused
from shared_memory.memory import INDEX_NAME, Memory, slugify


@dataclass(frozen=True)
class Committer:
    member_id: str
    name: str


@dataclass
class Change:
    """A set of file changes in one team's folder that lands as a single commit."""

    store: MemoryStore
    team: str
    writes: dict[PurePosixPath, Memory] = field(default_factory=dict)
    deletes: set[PurePosixPath] = field(default_factory=set)

    def write(self, path: PurePosixPath, memory: Memory) -> None:
        self.deletes.discard(path)
        self.writes[path] = memory

    def delete(self, path: PurePosixPath) -> None:
        self.writes.pop(path, None)
        self.deletes.add(path)

    def new_path(self, folder: PurePosixPath, title: str) -> PurePosixPath:
        base = slugify(title)
        if base == "index":
            base = "index-memory"
        candidate = folder / f"{base}.md"
        number = 2
        while candidate in self.writes or self.store.exists(self.team, candidate):
            candidate = folder / f"{base}-{number}.md"
            number += 1
        return candidate


class ChangeListener(Protocol):
    def on_change(self, team: str, writes: dict[PurePosixPath, Memory], deletes: Iterable[PurePosixPath]) -> None: ...


@dataclass(frozen=True)
class Version:
    """One version of a memory in the memory folder's history."""

    commit: str
    at: datetime
    author: str
    name: str
    message: str


def _check_commit(commit: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{7,64}", commit):
        raise Refused(f"{commit!r} is not a version of anything.")


class MemoryStore:
    def __init__(self, root: Path, listeners: Iterable[ChangeListener] = ()) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._listeners = list(listeners)
        if not (self._root / ".git").exists():
            self._git("init", "-q", "-b", "main")
            self._git("config", "core.autocrlf", "false")
            self._git("config", "core.quotepath", "false")

    def _git(self, *args: str, committer: Committer | None = None) -> str:
        env = dict(os.environ)
        env.update(
            GIT_COMMITTER_NAME="Shared Memory",
            GIT_COMMITTER_EMAIL="server@shared-memory.invalid",
            GIT_AUTHOR_NAME=committer.name if committer else "Shared Memory",
            GIT_AUTHOR_EMAIL=f"{committer.member_id}@members.shared-memory.invalid"
            if committer
            else "server@shared-memory.invalid",
        )
        result = subprocess.run(
            ["git", "-C", str(self._root), *args], env=env, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout

    def _file(self, team: str, path: PurePosixPath) -> Path:
        team_dir = (self._root / team).resolve()
        target = (team_dir / Path(*path.parts)).resolve() if path.parts else team_dir
        if target != team_dir and team_dir not in target.parents:
            raise Refused(f"{str(path)!r} is outside your team's memory.")
        return target

    def exists(self, team: str, path: PurePosixPath) -> bool:
        return self._file(team, path).is_file()

    def list_folder(
        self, team: str, folder: PurePosixPath
    ) -> tuple[list[tuple[PurePosixPath, Memory]], list[PurePosixPath]]:
        """The memories directly in a folder (sorted by title) and its subfolders."""
        directory = self._file(team, folder)
        if not directory.is_dir():
            return [], []
        memories: list[tuple[PurePosixPath, Memory]] = []
        for file in directory.glob("*.md"):
            if file.name == INDEX_NAME:
                continue
            try:
                memories.append((folder / file.name, Memory.from_text(file.read_text(encoding="utf-8"))))
            except Refused:
                continue
        memories.sort(key=lambda item: (item[1].title.lower(), str(item[0])))
        folders = sorted(folder / d.name for d in directory.iterdir() if d.is_dir() and not d.name.startswith("."))
        return memories, folders

    def walk(self, team: str, root: PurePosixPath) -> Iterator[tuple[PurePosixPath, list[tuple[PurePosixPath, Memory]]]]:
        """Every folder under root, depth first in path order, with the memories directly in it."""
        memories, folders = self.list_folder(team, root)
        yield root, memories
        for folder in folders:
            yield from self.walk(team, folder)

    def _write_index(self, team: str, folder: PurePosixPath) -> None:
        directory = self._file(team, folder)
        index = directory / INDEX_NAME
        memories, folders = self.list_folder(team, folder)
        if not memories and not folders:
            if index.exists():
                index.unlink()
            if folder.parts and directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
            return
        lines = [f"# {folder if folder.parts else 'Memory'}", ""]
        if memories:
            lines += ["## Memories", ""]
            lines += [f"- [{memory.title}]({path.name}): {memory.summary}" for path, memory in memories]
            lines.append("")
        if folders:
            lines += ["## Folders", ""]
            lines += [f"- [{sub.name}/]({sub.name}/{INDEX_NAME})" for sub in folders]
            lines.append("")
        directory.mkdir(parents=True, exist_ok=True)
        index.write_text("\n".join(lines), encoding="utf-8", newline="\n")

    def history(self, team: str, path: PurePosixPath) -> list[Version]:
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
                "--format=%x1e%H%x1f%aI%x1f%ae%x1f%an%x1f%s", "--", where,
            )  # fmt: skip
            born: str | None = None
            for record in printed.split("\x1e"):
                lines = [line for line in record.splitlines() if line.strip()]
                if not lines:
                    continue
                commit, at, email, name, message = lines[0].split("\x1f")
                version = Version(
                    commit=commit, at=datetime.fromisoformat(at), author=email.split("@")[0], name=name, message=message
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

    def version(self, team: str, path: PurePosixPath, commit: str) -> str:
        """The memory's text as it was at one version."""
        _check_commit(commit)
        where = self._where_then(team, path, commit)
        try:
            return self._git("show", f"{commit}:{where}")
        except RuntimeError:
            raise Refused(f"There is no version {commit!r} of {str(path)!r}.") from None

    def difference(self, team: str, path: PurePosixPath, before: str, after: str) -> str:
        """What changed in this memory between two versions, as a unified difference."""
        _check_commit(before)
        _check_commit(after)
        then = self._where_then(team, path, before)
        now = self._where_then(team, path, after)
        try:
            if then == now:
                return self._git("diff", "--unified=3", before, after, "--", now)
            return self._git("diff", "--unified=3", f"{before}:{then}", f"{after}:{now}")
        except RuntimeError:
            raise Refused("Those versions can't be compared.") from None

    def _inside_team(self, team: str, path: PurePosixPath) -> str:
        """The path git knows this memory by, confined to the team's own folder."""
        self._file(team, path)  # refuses anything outside the team's folder
        return str(PurePosixPath(team) / path)

    def text(self, team: str, path: PurePosixPath) -> str:
        """The memory file exactly as it is on disk: its header and its body, as every Claude reads it."""
        file = self._file(team, path)
        if not file.is_file():
            raise Refused(f"There is no memory at {str(path)!r}.")
        return file.read_text(encoding="utf-8")

    def extent(self, team: str, folder: PurePosixPath) -> tuple[int, datetime | None]:
        """How many memories a folder holds at any depth, and when the newest of them last changed."""
        directory = self._file(team, folder)
        if not directory.is_dir():
            return 0, None
        files = [file for file in directory.rglob("*.md") if file.name != INDEX_NAME]
        if not files:
            return 0, None
        newest = max(file.stat().st_mtime for file in files)
        return len(files), datetime.fromtimestamp(newest).astimezone()

    def changed(self, team: str, path: PurePosixPath) -> datetime | None:
        """When one memory file last changed on disk."""
        file = self._file(team, path)
        return datetime.fromtimestamp(file.stat().st_mtime).astimezone() if file.is_file() else None

    def read(self, team: str, path: PurePosixPath) -> Memory:
        file = self._file(team, path)
        if not file.is_file():
            raise Refused(f"There is no memory at {str(path)!r}.")
        return Memory.from_text(file.read_text(encoding="utf-8"))

    @contextmanager
    def change(self, team: str, committer: Committer, message: str) -> Iterator[Change]:
        with self._lock:
            change = Change(self, team)
            yield change
            folders: set[PurePosixPath] = set()
            for path, memory in change.writes.items():
                file = self._file(team, path)
                if file.name == INDEX_NAME:
                    raise Refused(f"{INDEX_NAME} is reserved for folder indexes.")
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(memory.to_text(), encoding="utf-8", newline="\n")
                folders.update(path.parents)
            for path in change.deletes:
                file = self._file(team, path)
                if file.is_file():
                    file.unlink()
                folders.update(path.parents)
            if not folders:
                return
            for folder in sorted(folders, key=lambda f: len(f.parts), reverse=True):
                self._write_index(team, folder)
            self._git("add", "-A", "--", str(self._file(team, PurePosixPath())))
            if self._git_has_staged_changes():
                self._git("commit", "-q", "-m", message, committer=committer)
            for listener in self._listeners:
                listener.on_change(team, dict(change.writes), set(change.deletes))

    def subscribe(self, listener: ChangeListener) -> None:
        self._listeners.append(listener)

    def teams(self) -> list[str]:
        return sorted(d.name for d in self._root.iterdir() if d.is_dir() and not d.name.startswith("."))

    def _git_has_staged_changes(self) -> bool:
        result = subprocess.run(["git", "-C", str(self._root), "diff", "--cached", "--quiet"], check=False)
        return result.returncode == 1
