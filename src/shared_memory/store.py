"""The memory folder: memory files on disk, the source of truth, with every change committed to git (ADR-0002, ADR-0003)."""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

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


class MemoryStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
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

    def _git_has_staged_changes(self) -> bool:
        result = subprocess.run(["git", "-C", str(self._root), "diff", "--cached", "--quiet"], check=False)
        return result.returncode == 1
