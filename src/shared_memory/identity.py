"""Identity and access: teams, members, personal tokens, projects and repositories."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Any

from shared_memory.clock import Clock
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.memory import slugify

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class Member:
    pk: int
    team_pk: int
    team_code: str
    member_id: str
    name: str
    is_owner: bool
    is_admin: bool = False

    @property
    def role(self) -> str:
        """owner, admin or member."""
        if self.is_owner:
            return "owner"
        return "admin" if self.is_admin else "member"


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

    @property
    def member_id(self) -> str:
        return self.member.member_id

    def require_project(self) -> Project:
        if self.project is None:
            raise Refused(
                "This repository isn't connected to a project, so memory isn't available here. "
                "Create one with create_project, or set the project ID in the repository's settings."
            )
        return self.project


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _github_login(login: str | None) -> str | None:
    cleaned = (login or "").strip().lstrip("@")
    return cleaned or None


def check_name(kind: str, value: str) -> str:
    if not NAME_PATTERN.match(value):
        raise Refused(
            f"{kind} {value!r} is not valid: use 1-64 letters, digits, dots, dashes or underscores, "
            "starting with a letter or digit."
        )
    return value


class Identity:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def setup_team(self, team_code: str, owner_employee_id: str, owner_name: str, owner_github: str | None = None) -> str:
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
                "INSERT INTO members (team_id, member_id, name, is_owner, github_login, created_at)"
                " VALUES (%s, %s, %s, TRUE, %s, %s) RETURNING id",
                (team["id"], owner_employee_id, owner_name, _github_login(owner_github), now),
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
                "SELECT m.id, m.team_id, t.code, m.member_id, m.name, m.is_owner, m.is_admin, m.removed_at,"
                " k.revoked_at"
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
            member = Member(
                row["id"], row["team_id"], row["code"], row["member_id"], row["name"], row["is_owner"],
                row["is_admin"],
            )  # fmt: skip
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

    def _require_admin(self, caller: Caller) -> None:
        if not (caller.member.is_owner or caller.member.is_admin):
            raise Refused("Only the team's owner and its admins can manage members and personal tokens.")

    def _require_owner(self, caller: Caller) -> None:
        if not caller.member.is_owner:
            raise Refused("Only the team's owner can grant admin, take it away, or hand over ownership.")

    def _member_pk(self, conn: Conn, caller: Caller, employee_id: str) -> int:
        row = conn.execute(
            "SELECT id FROM members WHERE team_id = %s AND member_id = %s AND removed_at IS NULL",
            (caller.member.team_pk, employee_id),
        ).fetchone()
        if row is None:
            raise Refused(f"No member with employee ID {employee_id!r} in your team.")
        pk: int = row["id"]
        return pk

    def add_member(
        self, caller: Caller, employee_id: str, name: str, team: str | None = None, github: str | None = None
    ) -> str:
        self._require_admin(caller)
        if team is not None and team != caller.team:
            raise Refused(f"You can only add members to your own team ({caller.team}).")
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
            login = _github_login(github)
            if login is not None:
                self._github_free(conn, caller.member.team_pk, login, None)
            row = conn.execute(
                "INSERT INTO members (team_id, member_id, name, github_login, created_at)"
                " VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (caller.member.team_pk, employee_id, name.strip(), login, self._clock()),
            ).fetchone()
            assert row is not None
            return self._issue_token(conn, row["id"])

    def remove_member(self, caller: Caller, employee_id: str) -> None:
        self._require_admin(caller)
        if employee_id == caller.member_id:
            raise Refused("You cannot remove yourself.")
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, employee_id)
            self._only_the_owner_touches_admins(conn, caller, pk, "removed", "remove")
            now = self._clock()
            conn.execute("UPDATE members SET removed_at = %s WHERE id = %s", (now, pk))
            conn.execute("UPDATE tokens SET revoked_at = %s WHERE member_id = %s AND revoked_at IS NULL", (now, pk))

    def reissue_token(self, caller: Caller, employee_id: str) -> str:
        self._require_admin(caller)
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, employee_id)
            conn.execute(
                "UPDATE tokens SET revoked_at = %s WHERE member_id = %s AND revoked_at IS NULL", (self._clock(), pk)
            )
            return self._issue_token(conn, pk)

    def link_github(self, team_code: str, employee_id: str, github_login: str) -> None:
        """Link a GitHub account to a member who already exists, so they can sign in to the console."""
        login = _github_login(github_login)
        if login is None:
            raise Refused("A GitHub username is needed.")
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT m.id FROM members m JOIN teams t ON t.id = m.team_id"
                " WHERE t.code = %s AND m.member_id = %s AND m.removed_at IS NULL",
                (team_code, employee_id),
            ).fetchone()
            if row is None:
                raise Refused(f"No member with employee ID {employee_id!r} in team {team_code!r}.")
            taken = conn.execute(
                "SELECT m.member_id FROM members m JOIN teams t ON t.id = m.team_id"
                " WHERE t.code = %s AND lower(m.github_login) = lower(%s) AND m.id <> %s",
                (team_code, login, row["id"]),
            ).fetchone()
            if taken is not None:
                raise Refused(f"GitHub account @{login} is already linked to {taken['member_id']!r} in this team.")
            # Clearing the account id makes the next sign-in bind this login to whichever account signs in with it.
            conn.execute(
                "UPDATE members SET github_login = %s, github_user_id = NULL WHERE id = %s", (login, row["id"])
            )

    def member_for_github(self, account_id: int, login: str) -> Member:
        """The member a GitHub account belongs to, remembering the account's id the first time it signs in."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT m.id, m.team_id, t.code, m.member_id, m.name, m.is_owner, m.is_admin, m.removed_at,"
                " m.github_user_id"
                " FROM members m JOIN teams t ON t.id = m.team_id"
                " WHERE m.github_user_id = %s OR (m.github_user_id IS NULL AND lower(m.github_login) = lower(%s))",
                (account_id, login),
            ).fetchall()
            if not rows:
                raise Refused(
                    f"The GitHub account @{login} isn't linked to a member. Ask an admin to link it to you."
                )
            if len(rows) > 1:
                raise Refused(f"The GitHub account @{login} is linked to members in more than one team. Ask an admin.")
            row = rows[0]
            if row["removed_at"] is not None:
                raise Refused("You have been removed from this team, so you can no longer sign in.")
            conn.execute(
                "UPDATE members SET github_user_id = %s, github_login = %s WHERE id = %s",
                (account_id, login, row["id"]),
            )
            return Member(row["id"], row["team_id"], row["code"], row["member_id"], row["name"], row["is_owner"])

    def reissue_own_token(self, member: Member) -> str:
        """A member replaces their own personal token; the one they had stops working."""
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE tokens SET revoked_at = %s WHERE member_id = %s AND revoked_at IS NULL",
                (self._clock(), member.pk),
            )
            return self._issue_token(conn, member.pk)

    def _github_free(self, conn: Conn, team_pk: int, login: str, except_pk: int | None) -> None:
        taken = conn.execute(
            "SELECT member_id FROM members WHERE team_id = %s AND lower(github_login) = lower(%s)"
            " AND (%s::bigint IS NULL OR id <> %s)",
            (team_pk, login, except_pk, except_pk),
        ).fetchone()
        if taken is not None:
            raise Refused(f"GitHub account @{login} is already linked to {taken['member_id']!r} in this team.")

    def _only_the_owner_touches_admins(self, conn: Conn, caller: Caller, pk: int, done: str, verb: str) -> None:
        row = conn.execute("SELECT is_owner, is_admin FROM members WHERE id = %s", (pk,)).fetchone()
        assert row is not None
        if row["is_owner"]:
            raise Refused(f"The team's owner can't be {done}. Hand ownership over first.")
        if row["is_admin"] and not caller.member.is_owner:
            raise Refused(f"Only the team's owner can {verb} an admin.")

    def members(self, member: Member) -> list[dict[str, Any]]:
        """Everyone in this member's team, with their role and the GitHub account they sign in with."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT member_id, name, is_owner, is_admin, github_login, removed_at FROM members"
                " WHERE team_id = %s ORDER BY is_owner DESC, is_admin DESC, member_id",
                (member.team_pk,),
            ).fetchall()
        return [
            {
                "employee_id": row["member_id"],
                "name": row["name"],
                "role": "owner" if row["is_owner"] else "admin" if row["is_admin"] else "member",
                "github_login": row["github_login"],
                "removed": row["removed_at"] is not None,
            }
            for row in rows
        ]

    def change_member(self, caller: Caller, employee_id: str, name: str | None, github: str | None) -> None:
        """Correct a member's name, or the GitHub account they sign in with."""
        self._require_admin(caller)
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, employee_id)
            if name is not None:
                if not name.strip():
                    raise Refused("A member needs a name.")
                conn.execute("UPDATE members SET name = %s WHERE id = %s", (name.strip(), pk))
            if github is not None:
                login = _github_login(github)
                if login is not None:
                    self._github_free(conn, caller.member.team_pk, login, pk)
                # Clearing the account id lets the next sign-in bind this login to whoever signs in with it.
                conn.execute("UPDATE members SET github_login = %s, github_user_id = NULL WHERE id = %s", (login, pk))

    def set_admin(self, caller: Caller, employee_id: str, admin: bool) -> None:
        """Grant admin to a member, or take it away. Only the owner can."""
        self._require_owner(caller)
        if employee_id == caller.member_id:
            raise Refused("You are the owner: you have everything an admin has.")
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, employee_id)
            conn.execute("UPDATE members SET is_admin = %s WHERE id = %s", (admin, pk))

    def hand_over_ownership(self, caller: Caller, employee_id: str) -> None:
        """Make another member the team's owner. The member handing it over stays an admin."""
        self._require_owner(caller)
        if employee_id == caller.member_id:
            raise Refused("You are already the owner.")
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, employee_id)
            conn.execute("UPDATE members SET is_owner = FALSE, is_admin = TRUE WHERE id = %s", (caller.member.pk,))
            conn.execute("UPDATE members SET is_owner = TRUE, is_admin = TRUE WHERE id = %s", (pk,))

    def is_removed(self, team_code: str, member_id: str) -> bool:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT m.removed_at FROM members m JOIN teams t ON t.id = m.team_id WHERE t.code = %s AND m.member_id = %s",
                (team_code, member_id),
            ).fetchone()
        return row is not None and row["removed_at"] is not None

    def projects(self, member: Member) -> list[Project]:
        """The projects this member can reach. Restricted projects narrow this in #34."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT project_id, name FROM projects WHERE team_id = %s ORDER BY name", (member.team_pk,)
            ).fetchall()
        return [Project(row["project_id"], row["name"]) for row in rows]

    def caller_in(self, member: Member, project_id: str | None) -> Caller:
        """The member as a caller of the memory services, working in one of their team's projects."""
        if project_id is None:
            return Caller(member, None, None)
        with self._db.transaction() as conn:
            found = conn.execute(
                "SELECT project_id, name FROM projects WHERE project_id = %s AND team_id = %s",
                (project_id, member.team_pk),
            ).fetchone()
        if found is None:
            raise Refused(f"Project {project_id!r} is not a project in your team.")
        return Caller(member, Project(found["project_id"], found["name"]), None)

    def create_project(self, caller: Caller, name: str) -> Project:
        if not name.strip():
            raise Refused("A project needs a name.")
        project_id = f"{slugify(name)[:40].strip('-')}-{secrets.token_hex(3)}"
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (project_id, team_id, name, created_at) VALUES (%s, %s, %s, %s)",
                (project_id, caller.member.team_pk, name.strip(), self._clock()),
            )
        return Project(project_id, name.strip())
