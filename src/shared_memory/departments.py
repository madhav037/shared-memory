"""Departments (ADR-0032): named groups of a company's projects, one level deep, and the department leads who look
after them.

A project sits in at most one department; a project in none reads company memory only, so a company that never makes
a department sees no change. The company's owner and admins create, rename and remove departments and name their
leads. A department lead names another lead and moves projects into and out of their department. Department memory
lives under `departments/<department ID>/` in the memory store (`memory.py`); nothing here touches it.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from psycopg.errors import UniqueViolation

from shared_memory.clock import Clock
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity, Member, Project
from shared_memory.memory import slugify

DEPARTMENT_ID_ATTEMPTS = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments (
    department_id TEXT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES teams(id),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
-- Two departments of one company are never called the same, whatever the case.
CREATE UNIQUE INDEX IF NOT EXISTS departments_one_name_per_company ON departments (company_id, lower(name));

CREATE TABLE IF NOT EXISTS department_leads (
    department_id TEXT NOT NULL REFERENCES departments(department_id) ON DELETE CASCADE,
    member_id BIGINT NOT NULL REFERENCES members(id),
    appointed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (department_id, member_id)
);

-- The project is the key: a project sits in at most one department.
CREATE TABLE IF NOT EXISTS department_projects (
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id),
    department_id TEXT NOT NULL REFERENCES departments(department_id) ON DELETE CASCADE,
    moved_in_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS department_projects_by_department ON department_projects (department_id);
"""


@dataclass(frozen=True)
class Department:
    department_id: str
    name: str


@dataclass(frozen=True)
class Lead:
    member_id: str
    name: str


@dataclass(frozen=True)
class DepartmentView:
    """A department as one member sees it: its leads, the projects in it they can reach, and what they may change."""

    department: Department
    leads: list[Lead]
    projects: list[Project]
    you_lead: bool
    you_may_change: bool


def _runs_the_company(member: Member) -> bool:
    return member.is_owner or member.is_admin


class Departments:
    def __init__(self, db: Database, identity: Identity, clock: Clock) -> None:
        self._db = db
        self._identity = identity
        self._clock = clock
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)

    # --- reading ---

    def of_project(self, project_id: str) -> Department | None:
        """The department a project is in, or None for a project in none."""
        return self.of_projects([project_id]).get(project_id)

    def of_projects(self, project_ids: list[str]) -> dict[str, Department]:
        """The department each of these projects is in, by project ID; a project in none is left out."""
        if not project_ids:
            return {}
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT p.project_id, d.department_id, d.name FROM department_projects p"
                " JOIN departments d ON d.department_id = p.department_id WHERE p.project_id = ANY(%s)",
                (project_ids,),
            ).fetchall()
        return {row["project_id"]: Department(row["department_id"], row["name"]) for row in rows}

    def exists(self, department_id: str) -> bool:
        """Whether a department with this ID exists; a removed one doesn't."""
        with self._db.transaction() as conn:
            found = conn.execute("SELECT 1 FROM departments WHERE department_id = %s", (department_id,)).fetchone()
        return found is not None

    def leads(self, member: Member, department_id: str) -> bool:
        """Whether this member is one of the department's leads."""
        with self._db.transaction() as conn:
            found = conn.execute(
                "SELECT 1 FROM department_leads WHERE department_id = %s AND member_id = %s", (department_id, member.pk)
            ).fetchone()
        return found is not None

    def listed(self, member: Member) -> list[DepartmentView]:
        """Every department of the member's company by name, each with the projects in it this member can reach."""
        reachable = {project.project_id: project for project in self._identity.projects(member)}
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT department_id, name FROM departments WHERE company_id = %s ORDER BY lower(name)",
                (member.company_pk,),
            ).fetchall()
            ids = [row["department_id"] for row in rows]
            lead_rows = conn.execute(
                "SELECT department_id, member_id FROM department_leads WHERE department_id = ANY(%s)", (ids,)
            ).fetchall()
            project_rows = conn.execute(
                "SELECT department_id, project_id FROM department_projects WHERE department_id = ANY(%s)", (ids,)
            ).fetchall()
            present = {
                row["member_id"] for row in lead_rows if self._identity.present(conn, row["member_id"]) is not None
            }
            names = self._identity.named_in(conn, present)
        views = []
        for row in rows:
            department_id = row["department_id"]
            lead_pks = {one["member_id"] for one in lead_rows if one["department_id"] == department_id} & present
            you_lead = member.pk in lead_pks
            views.append(
                DepartmentView(
                    department=Department(department_id, row["name"]),
                    leads=sorted((Lead(*names[pk]) for pk in lead_pks), key=lambda lead: lead.member_id),
                    projects=sorted(
                        (
                            reachable[one["project_id"]]
                            for one in project_rows
                            if one["department_id"] == department_id and one["project_id"] in reachable
                        ),
                        key=lambda project: project.name.lower(),
                    ),
                    you_lead=you_lead,
                    you_may_change=you_lead or _runs_the_company(member),
                )
            )
        return views

    # --- changing, for the company's owner and admins ---

    def create(self, caller: Caller, name: str) -> Department:
        """Make a department with no leads and no projects."""
        self._require_admin(caller, "create a department")
        name = self._checked_name(name)
        for attempt in range(DEPARTMENT_ID_ATTEMPTS):
            department_id = f"{slugify(name)[:40].strip('-')}-{secrets.token_hex(4)}"
            try:
                with self._db.transaction() as conn:
                    self._name_free(conn, caller.member.company_pk, name, None)
                    conn.execute(
                        "INSERT INTO departments (department_id, company_id, name, created_at) VALUES (%s, %s, %s, %s)",
                        (department_id, caller.member.company_pk, name, self._clock()),
                    )
            except UniqueViolation:
                if attempt == DEPARTMENT_ID_ATTEMPTS - 1:
                    raise
                continue
            return Department(department_id, name)
        raise AssertionError("unreachable")  # pragma: no cover

    def rename(self, caller: Caller, department_id: str, name: str) -> Department:
        """Change a department's name. Its department ID stays as it is."""
        self._require_admin(caller, "rename a department")
        name = self._checked_name(name)
        with self._db.transaction() as conn:
            self._found(conn, caller, department_id)
            self._name_free(conn, caller.member.company_pk, name, department_id)
            conn.execute("UPDATE departments SET name = %s WHERE department_id = %s", (name, department_id))
        return Department(department_id, name)

    def remove(self, caller: Caller, department_id: str) -> tuple[Department, list[str]]:
        """Remove a department. Its projects are left in no department; its leads lead nothing. Returns the department
        and the project IDs that were in it."""
        self._require_admin(caller, "remove a department")
        with self._db.transaction() as conn:
            department = self._found(conn, caller, department_id)
            left = conn.execute(
                "DELETE FROM department_projects WHERE department_id = %s RETURNING project_id", (department_id,)
            ).fetchall()
            conn.execute("DELETE FROM department_leads WHERE department_id = %s", (department_id,))
            conn.execute("DELETE FROM departments WHERE department_id = %s", (department_id,))
        return department, sorted(row["project_id"] for row in left)

    def remove_lead(self, caller: Caller, department_id: str, member_id: str) -> None:
        """Take a lead off a department. Only the company's admins can, so one lead can't unseat another."""
        self._require_admin(caller, "take a lead off a department")
        with self._db.transaction() as conn:
            self._found(conn, caller, department_id)
            pk = self._identity.present_member(conn, caller.member.company_pk, member_id)
            gone = conn.execute(
                "DELETE FROM department_leads WHERE department_id = %s AND member_id = %s RETURNING member_id",
                (department_id, pk),
            ).fetchone()
            if gone is None:
                raise Refused(f"{member_id!r} does not lead this department.")

    # --- changing, for a department's leads too ---

    def appoint_lead(self, caller: Caller, department_id: str, member_id: str) -> None:
        """Make a member a lead of this department. A department lead can appoint another; so can an admin."""
        with self._db.transaction() as conn:
            self._found(conn, caller, department_id)
            self._require_lead(conn, caller, department_id)
            pk = self._identity.present_member(conn, caller.member.company_pk, member_id)
            conn.execute(
                "INSERT INTO department_leads (department_id, member_id, appointed_at) VALUES (%s, %s, %s)"
                " ON CONFLICT DO NOTHING",
                (department_id, pk, self._clock()),
            )

    def move_in(self, caller: Caller, department_id: str, project_id: str) -> None:
        """Put a project in no department into this one. A project already in a department is refused: it has to be
        moved out of that one first, by someone who may change it."""
        project = self._identity.caller_in(caller.member, project_id).require_project()
        with self._db.transaction() as conn:
            self._found(conn, caller, department_id)
            self._require_lead(conn, caller, department_id)
            current = conn.execute(
                "SELECT d.department_id, d.name FROM department_projects p"
                " JOIN departments d ON d.department_id = p.department_id WHERE p.project_id = %s",
                (project.project_id,),
            ).fetchone()
            if current is not None and current["department_id"] == department_id:
                raise Refused(f"Project {project.name!r} is already in this department.")
            if current is not None:
                raise Refused(
                    f"Project {project.name!r} is already in the department {current['name']!r}, and a project sits in "
                    "at most one department. Move it out of that one first."
                )
            conn.execute(
                "INSERT INTO department_projects (project_id, department_id, moved_in_at) VALUES (%s, %s, %s)",
                (project.project_id, department_id, self._clock()),
            )

    def move_out(self, caller: Caller, department_id: str, project_id: str) -> None:
        """Take a project out of this department, leaving it in no department."""
        project = self._identity.caller_in(caller.member, project_id).require_project()
        with self._db.transaction() as conn:
            self._found(conn, caller, department_id)
            self._require_lead(conn, caller, department_id)
            gone = conn.execute(
                "DELETE FROM department_projects WHERE project_id = %s AND department_id = %s RETURNING project_id",
                (project.project_id, department_id),
            ).fetchone()
            if gone is None:
                raise Refused(f"Project {project.name!r} is not in this department.")

    # --- guards ---

    @staticmethod
    def _require_admin(caller: Caller, doing: str) -> None:
        if not _runs_the_company(caller.member):
            raise Refused(f"Only the company's owner and its admins can {doing}.")

    @staticmethod
    def _require_lead(conn: Conn, caller: Caller, department_id: str) -> None:
        if _runs_the_company(caller.member):
            return
        leads = conn.execute(
            "SELECT 1 FROM department_leads WHERE department_id = %s AND member_id = %s",
            (department_id, caller.member.pk),
        ).fetchone()
        if leads is None:
            raise Refused("Only this department's leads and the company's admins can change it.")

    @staticmethod
    def _found(conn: Conn, caller: Caller, department_id: str) -> Department:
        row = conn.execute(
            "SELECT department_id, name FROM departments WHERE department_id = %s AND company_id = %s",
            (department_id, caller.member.company_pk),
        ).fetchone()
        if row is None:
            raise Refused(f"{department_id!r} is not a department in your company.")
        return Department(row["department_id"], row["name"])

    @staticmethod
    def _checked_name(name: str) -> str:
        if not name.strip():
            raise Refused("A department needs a name.")
        return name.strip()

    @staticmethod
    def _name_free(conn: Conn, company_pk: int, name: str, except_id: str | None) -> None:
        taken = conn.execute(
            "SELECT name FROM departments WHERE company_id = %s AND lower(name) = lower(%s)"
            " AND department_id IS DISTINCT FROM %s",
            (company_pk, name, except_id),
        ).fetchone()
        if taken is not None:
            raise Refused(f"There is already a department called {taken['name']!r} in your company.")
