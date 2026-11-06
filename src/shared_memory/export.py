"""An admin's export of all the team's data, as one zip archive (spec #409).

It holds the memory folder's git repository with its full history as a git bundle, and JSON of the members, projects
(with their repositories, leads and access), the cards of every board and the audit log. It only reads, so it is
consistent with ADR-0009: the console governs memory and never writes it.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from shared_memory.audit import Audit
from shared_memory.board import Board
from shared_memory.config import Settings
from shared_memory.errors import Refused
from shared_memory.identity import Identity, Member
from shared_memory.store import memory_folder, ordinary

#: The audit log is read a page at a time; this is the most the log allows.
AUDIT_PAGE = 200


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)


class TeamExport:
    """Everything one admin may take away, built from the services that own each table."""

    def __init__(self, settings: Settings, identity: Identity, board: Board, audit: Audit) -> None:
        self._settings = settings
        self._identity = identity
        self._board = board
        self._audit = audit

    def build(self, member: Member) -> bytes:
        """The archive for this member's team, or a refusal when the member is not an admin."""
        if not (member.is_owner or member.is_admin):
            raise Refused("Only the team's owner and its admins can download all of the team's data.")
        projects = [
            self._identity.project_detail(member, project.project_id) for project in self._identity.projects(member)
        ]
        files = {
            "members.json": _json(self._identity.members(member)),
            "projects.json": _json(projects),
            "cards.json": _json({one["project_id"]: self._cards(member, one["project_id"]) for one in projects}),
            "audit-log.json": _json(self._audit_log(member)),
        }
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as zipped:
            for name, text in files.items():
                zipped.writestr(name, text)
            bundle = self._memory_bundle()
            if bundle is not None:
                zipped.writestr("memory.bundle", bundle)
        return package.getvalue()

    def _cards(self, member: Member, project_id: str) -> dict[str, Any]:
        caller = self._identity.caller_in(member, project_id)
        board = self._board.read(caller)
        return {"columns": board["columns"], "archive": self._board.read(caller, archive=True)["archive"]}

    def _audit_log(self, member: Member) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        before: int | None = None
        while True:
            page = self._audit.read(member, limit=AUDIT_PAGE, before=before)
            events += [asdict(event) for event in page.events]
            if page.next is None:
                return events
            before = page.next

    def _memory_bundle(self) -> bytes | None:
        """The memory folder's repository with every branch and version, or None while it holds no version yet."""
        folder = ordinary(memory_folder(self._settings.memory_root))
        if self._git(folder, "rev-parse", "--verify", "HEAD").returncode != 0:
            return None
        with tempfile.TemporaryDirectory() as scratch:
            bundle = Path(scratch) / "memory.bundle"
            made = self._git(folder, "bundle", "create", str(bundle), "--all")
            if made.returncode != 0:
                raise RuntimeError(f"git bundle failed: {made.stderr.strip()}")
            return bundle.read_bytes()

    @staticmethod
    def _git(folder: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603  # an argument list, never a shell
            ["git", "-C", folder, *args],  # noqa: S607  # git from the PATH the image installs it on
            env=dict(os.environ),
            capture_output=True,
            text=True,
            check=False,
        )
