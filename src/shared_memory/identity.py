"""Identity and access: teams, members, personal tokens, projects and repositories."""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from shared_memory.clock import Clock
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.memory import slugify

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# What another module does when a member may have lost a project. It is called inside the transaction making the
# change, with whoever made it, so its writes commit with the change or not at all; what it gives back is called once
# that transaction has committed, for whatever has to wait until then.
AccessLost = Callable[[Conn, "Caller"], Callable[[], None]]


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
    # The restricted projects this member isn't allowed into, worked out when the call was authenticated.
    unreachable: frozenset[str] = frozenset()
    # The coding agent the session runs in, as it reported itself; None for changes made from the console.
    agent: str | None = None

    def require_reach(self, path: str | None) -> None:
        """Refuse a memory or folder inside a restricted project this member isn't allowed into.

        A session is authenticated for the project it works in, but a path can point into any project, so every
        call that takes one checks it too.
        """
        project_id = project_in(path) if path else None
        if project_id is not None and project_id in self.unreachable:
            raise restricted_project(project_id)

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
                "Create one with create_project and commit the files it returns, or, if the product already has a "
                "project, commit its connection files from the console's project settings."
            )
        return self.project


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _github_login(login: str | None) -> str | None:
    cleaned = (login or "").strip().lstrip("@")
    return cleaned or None


def project_in(path: str) -> str | None:
    """The project a memory path or folder is inside, or nothing for team memory."""
    parts = PurePosixPath(path.replace("\\", "/").strip("/")).parts
    return parts[1] if len(parts) >= 2 and parts[0] == "projects" else None


def restricted_project(project_id: str) -> Refused:
    """The one refusal a member gets for a restricted project, wherever they meet it."""
    return Refused(
        f"Project {project_id!r} is restricted, so it isn't open to the whole team. "
        "Ask one of its project leads or a team admin to add you to its access list."
    )


def check_name(kind: str, value: str) -> str:
    if not NAME_PATTERN.match(value):
        raise Refused(
            f"{kind} {value!r} is not valid: use 1-64 letters, digits, dots, dashes or underscores, "
            "starting with a letter or digit."
        )
    return value


class Identity:
    def __init__(self, db: Database, clock: Clock) -> None:
        # Called when a member may have lost a project: removed from the team, taken off an access list or a lead, no
        # longer an admin, or a project restricted.
        self._access_lost: list[AccessLost] = []
        self._db = db
        self._clock = clock

    def setup_team(self, team_code: str, owner_member_id: str, owner_name: str, owner_github: str | None = None) -> str:
        check_name("Team ID", team_code)
        check_name("Member ID", owner_member_id)
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
                (team["id"], owner_member_id, owner_name, _github_login(owner_github), now),
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
            raise Refused(
                "No personal token was sent. Set your personal token in the SHARED_MEMORY_TOKEN environment variable "
                "(in Claude Code, in the Shared Memory settings), then start a new session."
            )
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
                    "This personal token is not recognised. Check SHARED_MEMORY_TOKEN (in Claude Code, the Shared "
                    "Memory settings), or issue yourself a new token from the console."
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
                project = self._reachable(conn, member, project_id)
                if repository:
                    check_name("Repository name", repository)
                    conn.execute(
                        "INSERT INTO repositories (project_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (project.project_id, repository),
                    )
            return Caller(member, project, repository or None, self._unreachable(conn, member))

    def on_access_lost(self, listener: AccessLost) -> None:
        self._access_lost.append(listener)

    def _lost_access(self, conn: Conn, caller: Caller) -> Callable[[], None]:
        """Have the listeners do their writes in the transaction that cost a member a project, so a listener that
        fails undoes the change too. Call what this returns once that transaction has committed."""
        afterwards = [listener(conn, caller) for listener in self._access_lost]

        def committed() -> None:
            for after in afterwards:
                after()

        return committed

    def _require_admin(self, caller: Caller) -> None:
        if not (caller.member.is_owner or caller.member.is_admin):
            raise Refused("Only the team's owner and its admins can manage members and personal tokens.")

    def _require_owner(self, caller: Caller) -> None:
        if not caller.member.is_owner:
            raise Refused("Only the team's owner can grant admin, take it away, or hand over ownership.")

    def looks_after(self, member: Member, project_id: str) -> bool:
        """Whether this member looks after the project: its leads do, and so do the team's owner and admins, because
        they have to be able to repair it."""
        if member.is_owner or member.is_admin:
            return True
        with self._db.transaction() as conn:
            return self._leads_it(conn, member.pk, project_id)

    def _require_lead(self, caller: Caller, project_id: str) -> None:
        if not self.looks_after(caller.member, project_id):
            raise Refused("Only this project's leads and the team's admins can change it.")

    @staticmethod
    def _leads_it(conn: Conn, member_pk: int, project_id: str) -> bool:
        found = conn.execute(
            "SELECT 1 FROM project_leads WHERE project_id = %s AND member_id = %s", (project_id, member_pk)
        ).fetchone()
        return found is not None

    def _member_pk(self, conn: Conn, caller: Caller, member_id: str) -> int:
        row = conn.execute(
            "SELECT id FROM members WHERE team_id = %s AND member_id = %s AND removed_at IS NULL",
            (caller.member.team_pk, member_id),
        ).fetchone()
        if row is None:
            raise Refused(f"No member with member ID {member_id!r} in your team.")
        pk: int = row["id"]
        return pk

    def add_member(
        self, caller: Caller, member_id: str, name: str, team: str | None = None, github: str | None = None
    ) -> str:
        self._require_admin(caller)
        if team is not None and team != caller.team:
            raise Refused(f"You can only add members to your own team ({caller.team}).")
        check_name("Member ID", member_id)
        if not name.strip():
            raise Refused("A member needs a name.")
        with self._db.transaction() as conn:
            existing = conn.execute(
                "SELECT removed_at FROM members WHERE team_id = %s AND member_id = %s",
                (caller.member.team_pk, member_id),
            ).fetchone()
            if existing is not None:
                raise Refused(f"Member ID {member_id!r} is already a member of your team, or was one.")
            login = _github_login(github)
            if login is not None:
                self._github_free(conn, caller.member.team_pk, login, None)
            row = conn.execute(
                "INSERT INTO members (team_id, member_id, name, github_login, created_at)"
                " VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (caller.member.team_pk, member_id, name.strip(), login, self._clock()),
            ).fetchone()
            assert row is not None
            return self._issue_token(conn, row["id"])

    def remove_member(self, caller: Caller, member_id: str) -> None:
        self._require_admin(caller)
        if member_id == caller.member_id:
            raise Refused("You cannot remove yourself.")
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, member_id)
            self._only_the_owner_touches_admins(conn, caller, pk, "removed", "remove")
            now = self._clock()
            conn.execute("UPDATE members SET removed_at = %s WHERE id = %s", (now, pk))
            conn.execute("UPDATE tokens SET revoked_at = %s WHERE member_id = %s AND revoked_at IS NULL", (now, pk))
            committed = self._lost_access(conn, caller)
        committed()

    def reissue_token(self, caller: Caller, member_id: str) -> str:
        self._require_admin(caller)
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, member_id)
            conn.execute(
                "UPDATE tokens SET revoked_at = %s WHERE member_id = %s AND revoked_at IS NULL", (self._clock(), pk)
            )
            return self._issue_token(conn, pk)

    def link_github(self, team_code: str, member_id: str, github_login: str) -> None:
        """Link a GitHub account to a member who already exists, so they can sign in to the console."""
        login = _github_login(github_login)
        if login is None:
            raise Refused("A GitHub username is needed.")
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT m.id FROM members m JOIN teams t ON t.id = m.team_id"
                " WHERE t.code = %s AND m.member_id = %s AND m.removed_at IS NULL",
                (team_code, member_id),
            ).fetchone()
            if row is None:
                raise Refused(f"No member with member ID {member_id!r} in team {team_code!r}.")
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
            return Member(
                row["id"], row["team_id"], row["code"], row["member_id"], row["name"], row["is_owner"],
                row["is_admin"],
            )  # fmt: skip

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
                "member_id": row["member_id"],
                "name": row["name"],
                "role": "owner" if row["is_owner"] else "admin" if row["is_admin"] else "member",
                "github_login": row["github_login"],
                "removed": row["removed_at"] is not None,
            }
            for row in rows
        ]

    def change_member(self, caller: Caller, member_id: str, name: str | None, github: str | None) -> None:
        """Correct a member's name, or the GitHub account they sign in with."""
        self._require_admin(caller)
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, member_id)
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

    def set_admin(self, caller: Caller, member_id: str, admin: bool) -> None:
        """Grant admin to a member, or take it away. Only the owner can."""
        self._require_owner(caller)
        if member_id == caller.member_id:
            raise Refused("You are the owner: you have everything an admin has.")
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, member_id)
            conn.execute("UPDATE members SET is_admin = %s WHERE id = %s", (admin, pk))
            committed = None if admin else self._lost_access(conn, caller)
        if committed is not None:
            committed()

    def hand_over_ownership(self, caller: Caller, member_id: str) -> None:
        """Make another member the team's owner. The member handing it over stays an admin."""
        self._require_owner(caller)
        if member_id == caller.member_id:
            raise Refused("You are already the owner.")
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, member_id)
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
        """The projects this member can reach: every open one, and the restricted ones they are allowed into."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT p.project_id, p.name FROM projects p WHERE p.team_id = %s AND (NOT p.restricted OR %s"
                " OR EXISTS (SELECT 1 FROM project_leads l WHERE l.project_id = p.project_id AND l.member_id = %s)"
                " OR EXISTS (SELECT 1 FROM project_access a WHERE a.project_id = p.project_id AND a.member_id = %s))"
                " ORDER BY p.name",
                (member.team_pk, member.is_owner or member.is_admin, member.pk, member.pk),
            ).fetchall()
        return [Project(row["project_id"], row["name"]) for row in rows]

    def _reachable(self, conn: Conn, member: Member, project_id: str) -> Project:
        """One of this member's team's projects, refused if it is restricted and they are not allowed into it."""
        found = conn.execute(
            "SELECT project_id, name, restricted FROM projects WHERE project_id = %s AND team_id = %s",
            (project_id, member.team_pk),
        ).fetchone()
        if found is None:
            raise Refused(f"Project {project_id!r} is not a project in your team.")
        if found["restricted"] and not self._allowed_in(conn, member, project_id):
            raise restricted_project(project_id)
        return Project(found["project_id"], found["name"])

    @staticmethod
    def _unreachable(conn: Conn, member: Member) -> frozenset[str]:
        """The restricted projects of this member's team that they aren't allowed into."""
        if member.is_owner or member.is_admin:
            return frozenset()
        rows = conn.execute(
            "SELECT p.project_id FROM projects p WHERE p.team_id = %s AND p.restricted"
            " AND NOT EXISTS (SELECT 1 FROM project_leads l WHERE l.project_id = p.project_id AND l.member_id = %s)"
            " AND NOT EXISTS (SELECT 1 FROM project_access a WHERE a.project_id = p.project_id AND a.member_id = %s)",
            (member.team_pk, member.pk, member.pk),
        ).fetchall()
        return frozenset(row["project_id"] for row in rows)

    def _allowed_in(self, conn: Conn, member: Member, project_id: str) -> bool:
        """Who a restricted project lets in: the team's owner and admins, its leads, and its access list."""
        if member.is_owner or member.is_admin or self._leads_it(conn, member.pk, project_id):
            return True
        found = conn.execute(
            "SELECT 1 FROM project_access WHERE project_id = %s AND member_id = %s", (project_id, member.pk)
        ).fetchone()
        return found is not None

    def member_reaching(self, caller: Caller, project_id: str, member_id: str) -> int:
        """A member of the caller's team who can reach this project, such as a card's assignee; refused otherwise."""
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, member_id)
            row = conn.execute(
                "SELECT NOT p.restricted OR m.is_owner OR m.is_admin"
                " OR EXISTS (SELECT 1 FROM project_leads l WHERE l.project_id = p.project_id AND l.member_id = m.id)"
                " OR EXISTS (SELECT 1 FROM project_access a WHERE a.project_id = p.project_id AND a.member_id = m.id)"
                " AS reaches FROM projects p, members m WHERE p.project_id = %s AND m.id = %s",
                (project_id, pk),
            ).fetchone()
        if row is None or not row["reaches"]:
            raise Refused(
                f"{member_id!r} can't reach project {project_id!r}: it is restricted and they aren't on its access list."
            )
        return pk

    def member_with_github(self, caller: Caller, login: str) -> str | None:
        """The member ID of the member of the caller's team who signs in with this GitHub account, if there is one."""
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT member_id FROM members WHERE team_id = %s AND lower(github_login) = lower(%s)"
                " AND removed_at IS NULL",
                (caller.member.team_pk, _github_login(login) or ""),
            ).fetchone()
        return None if row is None else str(row["member_id"])

    def caller_in(self, member: Member, project_id: str | None) -> Caller:
        """The member as a caller of the memory services, working in one of their team's projects."""
        with self._db.transaction() as conn:
            unreachable = self._unreachable(conn, member)
            if project_id is None:
                return Caller(member, None, None, unreachable)
            return Caller(member, self._reachable(conn, member, project_id), None, unreachable)

    def create_project(self, caller: Caller, name: str) -> Project:
        """Create a project. Whoever creates it is its first project lead."""
        if not name.strip():
            raise Refused("A project needs a name.")
        project_id = f"{slugify(name)[:40].strip('-')}-{secrets.token_hex(3)}"
        now = self._clock()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (project_id, team_id, name, created_at) VALUES (%s, %s, %s, %s)",
                (project_id, caller.member.team_pk, name.strip(), now),
            )
            conn.execute(
                "INSERT INTO project_leads (project_id, member_id, appointed_at) VALUES (%s, %s, %s)",
                (project_id, caller.member.pk, now),
            )
        return Project(project_id, name.strip())

    def rename_project(self, caller: Caller, project_id: str, name: str) -> None:
        """Change a project's name. Its project ID never changes: repositories are committed with it."""
        if not name.strip():
            raise Refused("A project needs a name.")
        self._require_lead(caller, project_id)
        with self._db.transaction() as conn:
            self._project_name(conn, caller.member, project_id)
            conn.execute("UPDATE projects SET name = %s WHERE project_id = %s", (name.strip(), project_id))

    def leads_of(self, member: Member) -> list[str]:
        """The projects this member leads."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT l.project_id FROM project_leads l JOIN projects p ON p.project_id = l.project_id"
                " WHERE l.member_id = %s AND p.team_id = %s ORDER BY l.project_id",
                (member.pk, member.team_pk),
            ).fetchall()
        return [row["project_id"] for row in rows]

    @staticmethod
    def _project_name(conn: Conn, member: Member, project_id: str) -> str:
        """The project's name, if it is one of this member's team's projects."""
        row = conn.execute(
            "SELECT name FROM projects WHERE project_id = %s AND team_id = %s", (project_id, member.team_pk)
        ).fetchone()
        if row is None:
            raise Refused(f"Project {project_id!r} is not a project in your team.")
        name: str = row["name"]
        return name

    @staticmethod
    def _leads_listed(conn: Conn, project_ids: list[str]) -> dict[str, list[dict[str, str]]]:
        rows = conn.execute(
            "SELECT l.project_id, m.member_id, m.name FROM project_leads l JOIN members m ON m.id = l.member_id"
            " WHERE l.project_id = ANY(%s) AND m.removed_at IS NULL ORDER BY m.member_id",
            (project_ids,),
        ).fetchall()
        listed: dict[str, list[dict[str, str]]] = {project_id: [] for project_id in project_ids}
        for row in rows:
            listed[row["project_id"]].append({"member_id": row["member_id"], "name": row["name"]})
        return listed

    def project_summaries(self, member: Member) -> list[dict[str, Any]]:
        """Every project this member can reach, with the members who lead it."""
        projects = self.projects(member)
        ids = [project.project_id for project in projects]
        with self._db.transaction() as conn:
            leads = self._leads_listed(conn, ids)
            closed = {
                row["project_id"]
                for row in conn.execute(
                    "SELECT project_id FROM projects WHERE project_id = ANY(%s) AND restricted", (ids,)
                ).fetchall()
            }
        return [
            {
                "project_id": project.project_id,
                "name": project.name,
                "restricted": project.project_id in closed,
                "leads": leads[project.project_id],
                "you_lead": any(one["member_id"] == member.member_id for one in leads[project.project_id]),
            }
            for project in projects
        ]

    def project_detail(self, member: Member, project_id: str) -> dict[str, Any]:
        """One project: its name, its leads, its repositories and, if it is restricted, who is allowed in."""
        with self._db.transaction() as conn:
            project = self._reachable(conn, member, project_id)
            row = conn.execute("SELECT restricted FROM projects WHERE project_id = %s", (project_id,)).fetchone()
            assert row is not None
            leads = self._leads_listed(conn, [project_id])[project_id]
            repositories = conn.execute(
                "SELECT name FROM repositories WHERE project_id = %s ORDER BY name", (project_id,)
            ).fetchall()
            access = conn.execute(
                "SELECT m.member_id, m.name FROM project_access a JOIN members m ON m.id = a.member_id"
                " WHERE a.project_id = %s AND m.removed_at IS NULL ORDER BY m.member_id",
                (project_id,),
            ).fetchall()
            you_lead = self._leads_it(conn, member.pk, project_id)
        return {
            "project_id": project_id,
            "name": project.name,
            "restricted": row["restricted"],
            "leads": leads,
            "access": [{"member_id": one["member_id"], "name": one["name"]} for one in access],
            "repositories": [row["name"] for row in repositories],
            "you_lead": you_lead,
            "you_may_change": you_lead or member.is_owner or member.is_admin,
        }

    def restrict(self, caller: Caller, project_id: str, restricted: bool) -> None:
        """Close a project to its access list, or open it to the whole team again.

        Unrestricting keeps the access list, so restricting it again lets the same members straight back in.
        """
        self._require_lead(caller, project_id)
        with self._db.transaction() as conn:
            self._project_name(conn, caller.member, project_id)
            conn.execute("UPDATE projects SET restricted = %s WHERE project_id = %s", (restricted, project_id))
            committed = self._lost_access(conn, caller) if restricted else None
        if committed is not None:
            committed()

    def grant_access(self, caller: Caller, project_id: str, member_id: str) -> None:
        """Let a member into this project. It takes effect on their next call."""
        self._require_lead(caller, project_id)
        with self._db.transaction() as conn:
            self._project_name(conn, caller.member, project_id)
            pk = self._member_pk(conn, caller, member_id)
            conn.execute(
                "INSERT INTO project_access (project_id, member_id, granted_at) VALUES (%s, %s, %s)"
                " ON CONFLICT DO NOTHING",
                (project_id, pk, self._clock()),
            )

    def revoke_access(self, caller: Caller, project_id: str, member_id: str) -> None:
        """Take a member off this project's access list. They lose it on their next call."""
        self._require_lead(caller, project_id)
        with self._db.transaction() as conn:
            self._project_name(conn, caller.member, project_id)
            pk = self._member_pk(conn, caller, member_id)
            gone = conn.execute(
                "DELETE FROM project_access WHERE project_id = %s AND member_id = %s RETURNING member_id",
                (project_id, pk),
            ).fetchone()
            if gone is None:
                raise Refused(f"{member_id!r} is not on this project's access list.")
            committed = self._lost_access(conn, caller)
        committed()

    def appoint_lead(self, caller: Caller, project_id: str, member_id: str) -> None:
        """Make a member a lead of this project. A lead can appoint another lead; so can an admin."""
        self._require_lead(caller, project_id)
        with self._db.transaction() as conn:
            self._project_name(conn, caller.member, project_id)
            pk = self._member_pk(conn, caller, member_id)
            conn.execute(
                "INSERT INTO project_leads (project_id, member_id, appointed_at) VALUES (%s, %s, %s)"
                " ON CONFLICT DO NOTHING",
                (project_id, pk, self._clock()),
            )

    def remove_lead(self, caller: Caller, project_id: str, member_id: str) -> None:
        """Take a lead off a project. Only the team's admins can, so one lead can't unseat another."""
        if not (caller.member.is_owner or caller.member.is_admin):
            raise Refused("Only the team's owner and its admins can take a lead off a project.")
        with self._db.transaction() as conn:
            self._project_name(conn, caller.member, project_id)
            pk = self._member_pk(conn, caller, member_id)
            removed = conn.execute(
                "DELETE FROM project_leads WHERE project_id = %s AND member_id = %s RETURNING member_id",
                (project_id, pk),
            ).fetchone()
            if removed is None:
                raise Refused(f"{member_id!r} does not lead this project.")
            committed = self._lost_access(conn, caller)
        committed()

    def add_repository(self, caller: Caller, project_id: str, repository: str) -> None:
        """Note a repository of this project, so its settings can be shown before anyone works in it."""
        check_name("Repository name", repository)
        self._require_lead(caller, project_id)
        with self._db.transaction() as conn:
            self._project_name(conn, caller.member, project_id)
            conn.execute(
                "INSERT INTO repositories (project_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (project_id, repository),
            )

    def remove_repository(self, caller: Caller, project_id: str, repository: str) -> None:
        """Forget a repository. A session connecting from it again puts it back."""
        self._require_lead(caller, project_id)
        with self._db.transaction() as conn:
            self._project_name(conn, caller.member, project_id)
            removed = conn.execute(
                "DELETE FROM repositories WHERE project_id = %s AND name = %s RETURNING name",
                (project_id, repository),
            ).fetchone()
        if removed is None:
            raise Refused(f"Repository {repository!r} is not one of this project's repositories.")
