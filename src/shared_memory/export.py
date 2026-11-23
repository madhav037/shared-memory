"""An admin's export of all the company's data, as one zip archive (spec #409).

It holds this company's folder of the memory repository, with its full history, as a git bundle, and JSON of the
members, projects (with their repositories, leads and access), the departments (with their leads and projects), the
cards of every board and the audit log. It only reads, so it is consistent with ADR-0009: the console governs memory
and never writes it.
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
from shared_memory.departments import Departments
from shared_memory.errors import Refused
from shared_memory.identity import Identity, Member
from shared_memory.memory import DEPARTMENTS_FOLDER
from shared_memory.store import memory_folder, ordinary

#: The audit log is read a page at a time; this is the most the log allows.
AUDIT_PAGE = 200


def _json(value: object) -> str:
    return json.dumps(value, indent=2, default=str)


class CompanyExport:
    """Everything one admin may take away, built from the services that own each table."""

    def __init__(
        self, settings: Settings, identity: Identity, board: Board, audit: Audit, departments: Departments
    ) -> None:
        self._settings = settings
        self._departments = departments
        self._identity = identity
        self._board = board
        self._audit = audit

    def build(self, member: Member) -> bytes:
        """The archive for this member's company, or a refusal when the member is not an admin."""
        if not (member.is_owner or member.is_admin):
            raise Refused("Only the company's owner and its admins can download all of the company's data.")
        projects = [
            self._identity.project_detail(member, project.project_id) for project in self._identity.projects(member)
        ]
        files = {
            "members.json": _json(self._identity.members(member)),
            "projects.json": _json(projects),
            "cards.json": _json({one["project_id"]: self._cards(member, one["project_id"]) for one in projects}),
            "departments.json": _json(self._departments_of(member)),
            "audit-log.json": _json(self._audit_log(member)),
        }
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as zipped:
            for name, text in files.items():
                zipped.writestr(name, text)
            bundle = self._memory_bundle(member.company_code)
            if bundle is not None:
                zipped.writestr("memory.bundle", bundle)
        return package.getvalue()

    def _departments_of(self, member: Member) -> list[dict[str, Any]]:
        """Every department with its leads and projects, by ID. Department memory itself is in the memory bundle, under
        departments/<department ID>/."""
        return [
            {
                "department_id": view.department.department_id,
                "name": view.department.name,
                "leads": [lead.member_id for lead in view.leads],
                "projects": [project.project_id for project in view.projects],
                "memory_folder": f"{DEPARTMENTS_FOLDER}/{view.department.department_id}",
            }
            for view in self._departments.listed(member)
        ]

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

    def _memory_bundle(self, company: str) -> bytes | None:
        """This company's folder of the memory repository, with every version of it, or None while it has none.

        The repository holds every company on the server, so its history is first copied with only this company's
        folder in it (`git fast-export` limited to the folder, into a new repository) and that copy is bundled: no other
        company's file, path or version is in the archive."""
        folder = ordinary(memory_folder(self._settings.memory_root))
        if self._git(folder, "rev-parse", "--verify", "HEAD").returncode != 0:
            return None
        # A literal pathspec: fast-export checks a plain path against the working tree, so a company whose folder isn't
        # there now would be refused, and nothing in the company's code is read as a pattern.
        exported = subprocess.run(  # noqa: S603  # an argument list, never a shell
            ["git", "-C", folder, "fast-export", "--all", "--reencode=yes", "--signed-tags=strip",  # noqa: S607
             "--tag-of-filtered-object=drop", "--", f":(literal){company}/"],
            env=dict(os.environ),
            capture_output=True,
            check=False,
        )  # fmt: skip
        if exported.returncode != 0:
            raise RuntimeError(f"git fast-export failed: {exported.stderr.decode(errors='replace').strip()}")
        with tempfile.TemporaryDirectory() as scratch:
            copy = str(Path(scratch) / "company.git")
            self._git(scratch, "init", "-q", "--bare", copy)
            imported = subprocess.run(  # noqa: S603  # an argument list, never a shell
                ["git", "-C", copy, "fast-import", "--quiet"],  # noqa: S607
                input=exported.stdout,
                env=dict(os.environ),
                capture_output=True,
                check=False,
            )
            if imported.returncode != 0:
                raise RuntimeError(f"git fast-import failed: {imported.stderr.decode(errors='replace').strip()}")
            if not self._git(copy, "for-each-ref", "--format=%(refname)").stdout.strip():
                return None
            # The copy's default branch is the repository's, so a clone of the bundle checks it out.
            branch = self._git(folder, "symbolic-ref", "-q", "HEAD").stdout.strip()
            if branch:
                self._git(copy, "symbolic-ref", "HEAD", branch)
            bundle = Path(scratch) / "memory.bundle"
            made = self._git(copy, "bundle", "create", str(bundle), "--all")
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
