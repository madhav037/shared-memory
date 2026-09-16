"""Identity and access: teams, members, personal tokens, projects and repositories."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass

from shared_memory.clock import Clock
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class Member:
    pk: int
    team_pk: int
    team_code: str
    member_id: str
    name: str
    is_owner: bool


@dataclass(frozen=True)
class Project:
    project_id: str
    name: str


@dataclass(frozen=True)
class Caller:
    member: Member
    project: Project | None
    repository: str | None

    @property
    def team(self) -> str:
        return self.member.team_code

    def require_project(self) -> Project:
        if self.project is None:
            raise Refused(
                "This repository isn't connected to a project, so memory isn't available here. "
                "Create one with create_project, or set the project ID in the repository's settings."
            )
        return self.project


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def check_name(kind: str, value: str) -> str:
    if not NAME_PATTERN.match(value):
        raise Refused(
            f"{kind} {value!r} is not valid: use 1-64 letters, digits, dots, dashes or underscores, "
            "starting with a letter or digit."
        )
    return value


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40].strip("-") or "project"


class Identity:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def setup_team(self, team_code: str, owner_employee_id: str, owner_name: str) -> str:
        check_name("Team ID", team_code)
        check_name("Employee ID", owner_employee_id)
        now = self._clock()
        with self._db.transaction() as conn:
            if conn.execute("SELECT 1 FROM teams WHERE code = %s", (team_code,)).fetchone():
                raise Refused(f"Team {team_code!r} already exists.")
            team = conn.execute(
                "INSERT INTO teams (code, created_at) VALUES (%s, %s) RETURNING id", (team_code, now)
            ).fetchone()
            assert team is not None
            member = conn.execute(
                "INSERT INTO members (team_id, member_id, name, is_owner, created_at)"
                " VALUES (%s, %s, %s, TRUE, %s) RETURNING id",
                (team["id"], owner_employee_id, owner_name, now),
            ).fetchone()
            assert member is not None
            return self._issue_token(conn, member["id"])

    def _issue_token(self, conn: Conn, member_pk: int) -> str:
        token = "smt_" + secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO tokens (member_id, token_hash, created_at) VALUES (%s, %s, %s)",
            (member_pk, _hash(token), self._clock()),
        )
        return token

    def authenticate(self, token: str | None, project_id: str | None, repository: str | None) -> Caller:
        if not token:
            raise Refused("No personal token was sent. Enter your personal token in the Shared Memory plugin settings.")
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT m.id, m.team_id, t.code, m.member_id, m.name, m.is_owner, m.removed_at, k.revoked_at"
                " FROM tokens k JOIN members m ON m.id = k.member_id JOIN teams t ON t.id = m.team_id"
                " WHERE k.token_hash = %s",
                (_hash(token),),
            ).fetchone()
            if row is None:
                raise Refused(
                    "This personal token is not recognised. Check the token in the Shared Memory plugin settings."
                )
            if row["removed_at"] is not None:
                raise Refused("This personal token belongs to a member who has been removed from the team.")
            if row["revoked_at"] is not None:
                raise Refused("This personal token has been revoked. Ask your team's owner for a new one.")
            member = Member(row["id"], row["team_id"], row["code"], row["member_id"], row["name"], row["is_owner"])
            project = None
            if project_id:
                found = conn.execute(
                    "SELECT project_id, name FROM projects WHERE project_id = %s AND team_id = %s",
                    (project_id, member.team_pk),
                ).fetchone()
                if found is None:
                    raise Refused(f"Project {project_id!r} is not a project in your team.")
                project = Project(found["project_id"], found["name"])
                if repository:
                    check_name("Repository name", repository)
                    conn.execute(
                        "INSERT INTO repositories (project_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (project.project_id, repository),
                    )
            return Caller(member, project, repository or None)

    def _require_owner(self, caller: Caller) -> None:
        if not caller.member.is_owner:
            raise Refused("Only the team's owner can add or remove members and reissue personal tokens.")

    def _member_pk(self, conn: Conn, caller: Caller, employee_id: str) -> int:
        row = conn.execute(
            "SELECT id FROM members WHERE team_id = %s AND member_id = %s AND removed_at IS NULL",
            (caller.member.team_pk, employee_id),
        ).fetchone()
        if row is None:
            raise Refused(f"No member with employee ID {employee_id!r} in your team.")
        pk: int = row["id"]
        return pk

    def add_member(self, caller: Caller, employee_id: str, name: str) -> str:
        self._require_owner(caller)
        check_name("Employee ID", employee_id)
        if not name.strip():
            raise Refused("A member needs a name.")
        with self._db.transaction() as conn:
            existing = conn.execute(
                "SELECT removed_at FROM members WHERE team_id = %s AND member_id = %s",
                (caller.member.team_pk, employee_id),
            ).fetchone()
            if existing is not None:
                raise Refused(f"Employee ID {employee_id!r} is already a member of your team, or was one.")
            row = conn.execute(
                "INSERT INTO members (team_id, member_id, name, created_at) VALUES (%s, %s, %s, %s) RETURNING id",
                (caller.member.team_pk, employee_id, name.strip(), self._clock()),
            ).fetchone()
            assert row is not None
            return self._issue_token(conn, row["id"])

    def remove_member(self, caller: Caller, employee_id: str) -> None:
        self._require_owner(caller)
        if employee_id == caller.member.member_id:
            raise Refused("You cannot remove yourself: the team would have no owner.")
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, employee_id)
            now = self._clock()
            conn.execute("UPDATE members SET removed_at = %s WHERE id = %s", (now, pk))
            conn.execute("UPDATE tokens SET revoked_at = %s WHERE member_id = %s AND revoked_at IS NULL", (now, pk))

    def reissue_token(self, caller: Caller, employee_id: str) -> str:
        self._require_owner(caller)
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, employee_id)
            conn.execute(
                "UPDATE tokens SET revoked_at = %s WHERE member_id = %s AND revoked_at IS NULL", (self._clock(), pk)
            )
            return self._issue_token(conn, pk)

    def create_project(self, caller: Caller, name: str) -> Project:
        if not name.strip():
            raise Refused("A project needs a name.")
        project_id = f"{_slug(name)}-{secrets.token_hex(3)}"
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (project_id, team_id, name, created_at) VALUES (%s, %s, %s, %s)",
                (project_id, caller.member.team_pk, name.strip(), self._clock()),
            )
        return Project(project_id, name.strip())
