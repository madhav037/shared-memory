"""Departments (ADR-0032): named groups of a company's projects, one level deep, and the department leads who look
after them.

A project sits in at most one department; a project in none reads company memory only, so a company that never makes
a department sees no change. The company's owner and admins create, rename and remove departments and name their
leads. A department lead names another lead and moves projects into and out of their department. Department memory
lives under `departments/<department ID>/` in the memory store (`memory.py`); nothing here touches it.

A department is open to the whole company unless one of its leads, or an admin, restricts it to an access list
(extending ADR-0006). A restricted department's department memory and projects are then invisible to every member
outside it: off its access list, not one of its leads and not an admin. Identity asks this module who a department
keeps out (`DepartmentWall`), so the same single refusal holds wherever a restricted project's does.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field

from psycopg.errors import UniqueViolation

from shared_memory.audit import Audit
from shared_memory.clock import Clock
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.identity import Caller, Identity, Member, Project, ShutOut
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

-- A restricted department is reached only by its access list, its leads and the company's admins (ADR-0032).
ALTER TABLE departments ADD COLUMN IF NOT EXISTS restricted BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS department_access (
    department_id TEXT NOT NULL REFERENCES departments(department_id) ON DELETE CASCADE,
    member_id BIGINT NOT NULL REFERENCES members(id),
    granted_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (department_id, member_id)
);

-- Who a restricted department keeps out is asked on every authenticated call, so it reads one company's restricted
-- departments by index.
CREATE INDEX IF NOT EXISTS departments_restricted ON departments (company_id) WHERE restricted;

-- A removed department's memory stays, retired, and only the company's owner and admins reach it.
CREATE TABLE IF NOT EXISTS removed_departments (
    department_id TEXT PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES teams(id),
    removed_at TIMESTAMPTZ NOT NULL
);
"""

# The members a restricted department lets in, besides the company's owner and admins: its leads and its access list.
_LETS_IN = (
    "(EXISTS (SELECT 1 FROM department_leads l WHERE l.department_id = d.department_id AND l.member_id = {member})"
    " OR EXISTS (SELECT 1 FROM department_access a WHERE a.department_id = d.department_id AND a.member_id = {member}))"
)


@dataclass(frozen=True)
class Department:
    department_id: str
    name: str
    # Closed to its access list (ADR-0032); only `of_projects` says, everything else leaves it False.
    restricted: bool = False


@dataclass(frozen=True)
class Lead:
    member_id: str
    name: str


@dataclass(frozen=True)
class DepartmentView:
    """A department as one member sees it: its leads, the projects in it they can reach, whether it is restricted and
    who is on its access list, and what they may change."""

    department: Department
    leads: list[Lead]
    projects: list[Project]
    you_lead: bool
    you_may_change: bool
    restricted: bool = False
    access: list[Lead] = field(default_factory=list)


def _runs_the_company(member: Member) -> bool:
    return member.is_owner or member.is_admin


class Departments:
    def __init__(self, db: Database, identity: Identity, clock: Clock, audit: Audit) -> None:
        self._db = db
        self._identity = identity
        self._clock = clock
        if db.sets_up:
            with db.transaction() as conn:
                found = conn.execute("SELECT to_regclass('removed_departments') IS NOT NULL AS kept").fetchone()
            # Departments removed before removals were kept here are found in the audit log, once: when the table is made.
            earlier = [] if found is not None and found["kept"] else audit.departments_removed()
            with db.transaction() as conn:
                conn.execute(SCHEMA)
                conn.execute(
                    "INSERT INTO removed_departments (department_id, company_id, removed_at)"
                    " SELECT x.department_id, x.company_id, x.removed_at"
                    " FROM unnest(%s::text[], %s::bigint[], %s::timestamptz[]) AS x(department_id, company_id, removed_at)"
                    " WHERE NOT EXISTS (SELECT 1 FROM departments d WHERE d.department_id = x.department_id)"
                    " ON CONFLICT DO NOTHING",
                    ([one[0] for one in earlier], [one[1] for one in earlier], [one[2] for one in earlier]),
                )

    # --- who a restricted department keeps out (identity.DepartmentWall) ---

    def shut_out(self, conn: Conn, member: Member) -> ShutOut:
        """The restricted departments of the member's company they are outside of, and the projects in them; and every
        removed department, whose memory only the company's owner and admins reach."""
        rows = conn.execute(
            "SELECT d.department_id, p.project_id FROM departments d"  # noqa: S608  # only the member's row id is bound
            " LEFT JOIN department_projects p ON p.department_id = d.department_id"
            f" WHERE d.company_id = %(company)s AND d.restricted AND NOT {_LETS_IN.format(member='%(member)s')}"
            " UNION ALL SELECT department_id, NULL FROM removed_departments WHERE company_id = %(company)s",
            {"company": member.company_pk, "member": member.pk},
        ).fetchall()
        return ShutOut(
            departments=frozenset(row["department_id"] for row in rows),
            projects=frozenset(row["project_id"] for row in rows if row["project_id"] is not None),
        )

    def shut_pairs(self, conn: Conn, pairs: Sequence[tuple[int, str]]) -> set[tuple[int, str]]:
        """Of these members (by row id) each in a project, those the project's restricted department keeps out."""
        if not pairs:
            return set()
        rows = conn.execute(
            "SELECT x.member_id, x.project_id"  # noqa: S608  # the clause spliced in is the code's own
            " FROM unnest(%s::bigint[], %s::text[]) AS x(member_id, project_id)"
            " JOIN department_projects p ON p.project_id = x.project_id"
            " JOIN departments d ON d.department_id = p.department_id"
            f" WHERE d.restricted AND NOT {_LETS_IN.format(member='x.member_id')}",
            ([pk for pk, _ in pairs], [project_id for _, project_id in pairs]),
        ).fetchall()
        return {(row["member_id"], row["project_id"]) for row in rows}

    def restricted_department_of(self, conn: Conn, project_id: str) -> str | None:
        """The name of the restricted department a project is in, or None when it is in none or in an open one."""
        row = conn.execute(
            "SELECT d.name FROM department_projects p JOIN departments d ON d.department_id = p.department_id"
            " WHERE p.project_id = %s AND d.restricted",
            (project_id,),
        ).fetchone()
        return None if row is None else str(row["name"])

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
                "SELECT p.project_id, d.department_id, d.name, d.restricted FROM department_projects p"
                " JOIN departments d ON d.department_id = p.department_id WHERE p.project_id = ANY(%s)",
                (project_ids,),
            ).fetchall()
        return {
            row["project_id"]: Department(row["department_id"], row["name"], row["restricted"]) for row in rows
        }

    def projects_in(self, department_id: str) -> list[str]:
        """The IDs of the projects in a department."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT project_id FROM department_projects WHERE department_id = %s ORDER BY project_id", (department_id,)
            ).fetchall()
        return [row["project_id"] for row in rows]

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

    def named(self, department_id: str) -> Department | None:
        """The department with this ID, or None once it has been removed."""
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT department_id, name FROM departments WHERE department_id = %s", (department_id,)
            ).fetchone()
        return None if row is None else Department(row["department_id"], row["name"])

    def has_leads(self, department_id: str) -> bool:
        """Whether any member still in the company leads this department. One with none left is decided for by the
        company's admins (ADR-0033)."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT member_id FROM department_leads WHERE department_id = %s", (department_id,)
            ).fetchall()
            return any(self._identity.present(conn, row["member_id"]) is not None for row in rows)

    def listed(self, member: Member) -> list[DepartmentView]:
        """Every department of the member's company they can reach, by name, each with the projects in it this member
        can reach. A restricted department they are outside of isn't listed at all."""
        reachable = {project.project_id: project for project in self._identity.projects(member)}
        with self._db.transaction() as conn:
            kept_out = set() if _runs_the_company(member) else self.shut_out(conn, member).departments
            rows = [
                row
                for row in conn.execute(
                    "SELECT department_id, name, restricted FROM departments WHERE company_id = %s"
                    " ORDER BY lower(name)",
                    (member.company_pk,),
                ).fetchall()
                if row["department_id"] not in kept_out
            ]
            ids = [row["department_id"] for row in rows]
            access_rows = conn.execute(
                "SELECT department_id, member_id FROM department_access WHERE department_id = ANY(%s)", (ids,)
            ).fetchall()
            lead_rows = conn.execute(
                "SELECT department_id, member_id FROM department_leads WHERE department_id = ANY(%s)", (ids,)
            ).fetchall()
            project_rows = conn.execute(
                "SELECT department_id, project_id FROM department_projects WHERE department_id = ANY(%s)", (ids,)
            ).fetchall()
            present = {
                row["member_id"]
                for row in [*lead_rows, *access_rows]
                if self._identity.present(conn, row["member_id"]) is not None
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
                    restricted=row["restricted"],
                    access=sorted(
                        (
                            Lead(*names[one["member_id"]])
                            for one in access_rows
                            if one["department_id"] == department_id and one["member_id"] in present
                        ),
                        key=lambda allowed: allowed.member_id,
                    ),
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
        """Remove a department. Its projects are left in no department; its leads lead nothing; its memory is reached
        by the company's owner and admins only from now on. A restricted department still holding projects is refused,
        so none of them opens to the whole company without someone moving it out. Returns the department and the
        project IDs that were in it."""
        self._require_admin(caller, "remove a department")
        with self._db.transaction() as conn:
            department = self._found(conn, caller, department_id)
            held = conn.execute(
                "SELECT 1 FROM department_projects p JOIN departments d ON d.department_id = p.department_id"
                " WHERE d.department_id = %s AND d.restricted LIMIT 1",
                (department_id,),
            ).fetchone()
            if held is not None:
                raise Refused(
                    f"{department.name!r} is restricted and still holds projects, which would open to the whole company "
                    "once it is gone. Move its projects out first."
                )
            left = conn.execute(
                "DELETE FROM department_projects WHERE department_id = %s RETURNING project_id", (department_id,)
            ).fetchall()
            conn.execute("DELETE FROM department_leads WHERE department_id = %s", (department_id,))
            conn.execute("DELETE FROM departments WHERE department_id = %s", (department_id,))
            conn.execute(
                "INSERT INTO removed_departments (department_id, company_id, removed_at) VALUES (%s, %s, %s)",
                (department_id, caller.member.company_pk, self._clock()),
            )
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
            committed = self._identity.lost_access(conn, caller)
        committed()

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
            # Into a restricted department, the project is hidden from everyone outside it from now on.
            committed = self._identity.lost_access(conn, caller)
        committed()

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

    def restrict(self, caller: Caller, department_id: str, restricted: bool) -> Department:
        """Close a department to its access list, or open it to the whole company again. Opening it keeps the access
        list, so restricting it again lets the same members straight back in."""
        with self._db.transaction() as conn:
            department = self._found(conn, caller, department_id)
            self._require_lead(conn, caller, department_id)
            conn.execute("UPDATE departments SET restricted = %s WHERE department_id = %s", (restricted, department_id))
            committed = self._identity.lost_access(conn, caller) if restricted else None
        if committed is not None:
            committed()
        return department

    def grant_access(self, caller: Caller, department_id: str, member_id: str) -> Department:
        """Put a member on this department's access list. It takes effect on their next call."""
        with self._db.transaction() as conn:
            department = self._found(conn, caller, department_id)
            self._require_lead(conn, caller, department_id)
            pk = self._identity.present_member(conn, caller.member.company_pk, member_id)
            conn.execute(
                "INSERT INTO department_access (department_id, member_id, granted_at) VALUES (%s, %s, %s)"
                " ON CONFLICT DO NOTHING",
                (department_id, pk, self._clock()),
            )
        return department

    def revoke_access(self, caller: Caller, department_id: str, member_id: str) -> Department:
        """Take a member off this department's access list. They lose it on their next call."""
        with self._db.transaction() as conn:
            department = self._found(conn, caller, department_id)
            self._require_lead(conn, caller, department_id)
            pk = self._identity.present_member(conn, caller.member.company_pk, member_id)
            gone = conn.execute(
                "DELETE FROM department_access WHERE department_id = %s AND member_id = %s RETURNING member_id",
                (department_id, pk),
            ).fetchone()
            if gone is None:
                raise Refused(f"{member_id!r} is not on this department's access list.")
            committed = self._identity.lost_access(conn, caller)
        committed()
        return department

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
