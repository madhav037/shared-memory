"""The memory file contract: a header of stable details plus a Markdown body, and where memories live."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from pathlib import PurePosixPath
from typing import Any, Literal

import yaml

from shared_memory.errors import Refused

TYPE_FOLDERS = {"convention": "conventions", "decision": "decisions", "architecture": "architecture", "gotcha": "gotchas"}
FOLDER_TYPES = {folder: kind for kind, folder in TYPE_FOLDERS.items()}
INDEX_NAME = "index.md"

Level = Literal["team", "project", "personal"]


@dataclass
class Memory:
    title: str
    summary: str
    type: str
    author: str
    body: str
    status: str = "active"
    replaces: str | None = None
    superseded_by: str | None = None
    exception_to: str | None = None
    related_files: list[str] = field(default_factory=list)
    promoted_by: str | None = None

    def to_text(self) -> str:
        header: dict[str, Any] = {}
        for f in fields(self):
            if f.name == "body":
                continue
            value = getattr(self, f.name)
            if value in (None, []):
                continue
            header[f.name] = value
        rendered = yaml.safe_dump(header, sort_keys=False, allow_unicode=True, width=1000)
        return f"---\n{rendered}---\n{self.body.strip()}\n"

    @classmethod
    def from_text(cls, text: str) -> Memory:
        match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text.replace("\r\n", "\n"), re.DOTALL)
        if not match:
            raise Refused("This file has no memory header.")
        header = yaml.safe_load(match.group(1)) or {}
        known = {f.name for f in fields(cls)}
        values = {key: value for key, value in header.items() if key in known}
        values["body"] = match.group(2).strip()
        values.setdefault("related_files", [])
        return cls(**values)


@dataclass(frozen=True)
class Location:
    """Where a memory sits, decoded from its path relative to the team's folder."""

    path: PurePosixPath
    level: Level
    type: str
    project_id: str | None
    member_id: str | None
    topic: str | None = None


def locate(path: str) -> Location:
    pure = PurePosixPath(path.replace("\\", "/"))
    parts = pure.parts
    if pure.is_absolute() or ".." in parts or not parts or pure.suffix != ".md" or pure.name == INDEX_NAME:
        raise Refused(f"{path!r} is not a memory path.")
    if parts[0] == "team" and len(parts) in (3, 4):
        level: Level = "team"
        project_id = member_id = None
        type_index = 1
    elif parts[0] == "projects" and len(parts) in (5, 6) and parts[2] == "shared":
        level, project_id, member_id, type_index = "project", parts[1], None, 3
    elif parts[0] == "projects" and len(parts) in (6, 7) and parts[2] == "people":
        level, project_id, member_id, type_index = "personal", parts[1], parts[3], 4
    else:
        raise Refused(f"{path!r} is not a memory path.")
    if parts[type_index] not in FOLDER_TYPES:
        raise Refused(f"{path!r} is not a memory path.")
    topic = parts[type_index + 1] if len(parts) == type_index + 3 else None
    return Location(pure, level, FOLDER_TYPES[parts[type_index]], project_id, member_id, topic)


_LEVEL_ORDER: dict[Level, int] = {"team": 0, "project": 1, "personal": 2}


@dataclass(frozen=True)
class Area:
    """The memory one save can change without waiting on others (CONTEXT.md): the team memory, one project's project
    memory, or one member's personal memory in one project. Saves take turns per area (ADR-0012)."""

    level: Level
    project_id: str | None = None
    member_id: str | None = None

    @property
    def folder(self) -> PurePosixPath:
        """The folder holding the whole area, its own index included."""
        if self.level == "team":
            return PurePosixPath("team")
        assert self.project_id is not None
        if self.level == "project":
            return PurePosixPath("projects", self.project_id, "shared")
        assert self.member_id is not None
        return PurePosixPath("projects", self.project_id, "people", self.member_id)

    def order(self) -> tuple[int, str, str]:
        """The order a save takes its areas' turns in: team, then project memory, then personal memory, each by id."""
        return _LEVEL_ORDER[self.level], self.project_id or "", self.member_id or ""


def area_of(path: PurePosixPath) -> Area | None:
    """The area a memory, a folder or a folder's index lies in; None for the folders above the areas, which they share."""
    parts = path.parts
    if parts[:1] == ("team",):
        return Area("team")
    if len(parts) >= 3 and parts[0] == "projects" and parts[2] == "shared":
        return Area("project", parts[1])
    if len(parts) >= 4 and parts[0] == "projects" and parts[2] == "people" and parts[3] != INDEX_NAME:
        return Area("personal", parts[1], parts[3])
    return None


def level_folder(level: Level, kind: str, project_id: str | None = None, member_id: str | None = None) -> PurePosixPath:
    """The type folder a memory of this level and type lives in."""
    if level == "team":
        return PurePosixPath("team", type_folder(kind))
    assert project_id is not None
    if level == "project":
        return PurePosixPath("projects", project_id, "shared", type_folder(kind))
    assert member_id is not None
    return PurePosixPath("projects", project_id, "people", member_id, type_folder(kind))


def type_folder(kind: str) -> str:
    if kind not in TYPE_FOLDERS:
        raise Refused(f"Unknown memory type {kind!r}: use convention, decision, architecture or gotcha.")
    return TYPE_FOLDERS[kind]


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].strip("-") or "memory"
