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
            touched: list[Path] = []
            for path, memory in change.writes.items():
                file = self._file(team, path)
                if file.name == INDEX_NAME:
                    raise Refused(f"{INDEX_NAME} is reserved for folder indexes.")
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(memory.to_text(), encoding="utf-8", newline="\n")
                touched.append(file)
            for path in change.deletes:
                file = self._file(team, path)
                if file.is_file():
                    file.unlink()
                touched.append(file)
            if not touched:
                return
            self._git("add", "-A", "--", *(str(file) for file in touched))
            self._git("commit", "-q", "-m", message, committer=committer)
