"""Identity and access: companies, members, personal tokens, projects and repositories."""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol

from psycopg.errors import UniqueViolation

from shared_memory.clock import Clock
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.memory import CORE_FOUNDATIONS, foundation_title, slugify
from shared_memory.store import signable
from shared_memory.time_zone import MemberTimeZone, checked

NAME_LIMIT = 64
MEMBER_NAME_LIMIT = 100
# The longest an email address may be (RFC 5321): the one place the limit is named.
EMAIL_LIMIT = 254
PROJECT_ID_ATTEMPTS = 5
# \Z, not $: a $ would also take a name followed by a line break.
NAME_PATTERN = re.compile(rf"^[A-Za-z0-9][A-Za-z0-9._-]{{0,{NAME_LIMIT - 1}}}\Z")

# What another module does when a member may have lost a project. It is called inside the transaction making the
# change, with whoever made it, so its writes commit with the change or not at all; what it gives back is called once
# that transaction has committed, for whatever has to wait until then.
AccessLost = Callable[[Conn, "Caller"], Callable[[], None]]
# What another module does when a member's GitHub account is moved to another one or taken away: called inside the
# transaction making the change, with the member's key, so whatever the old account still holds ends with it.
LinkMoved = Callable[[Conn, int], None]


@dataclass(frozen=True)
class Member:
    pk: int
    company_pk: int
    company_code: str
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
class SignedIn:
    """Who a sign-in was for, and whether it linked their GitHub account just now, through the email they proved."""

    member: Member
    linked: bool = False


@dataclass(frozen=True)
class GitHubAccount:
    account_id: int
    login: str


@dataclass(frozen=True)
class ProvenSignIn:
    """What a sign-in method proved about whoever is signing in, which is all the matcher is told."""

    github: GitHubAccount
    # The email the method vouched for, trimmed, or None where it vouched for none.
    verified_email: str | None = None

    @property
    def matchable_email(self) -> str | None:
        """The email to match and keep: emails are ASCII, so one that is not is ignored, whichever method proved it."""
        email = self.verified_email
        return email if email is not None and email.isascii() else None

    @property
    def described(self) -> str:
        """What was proven, as a refusal names it."""
        return f"The GitHub account @{self.github.login}"

    @property
    def actor(self) -> str:
        """Who the audit log says tried, when no member was found."""
        return f"@{self.github.login}"

    @property
    def audited(self) -> dict[str, str]:
        """What the audit log keeps of a sign-in by this proven."""
        return {"github": self.github.login}


@dataclass(frozen=True)
class Project:
    project_id: str
    name: str


@dataclass(frozen=True)
class ShutOut:
    """What a member can't reach beyond restricted projects' own access lists: the restricted departments they are
    outside of, and the projects inside those departments (ADR-0032)."""

    departments: frozenset[str] = frozenset()
    projects: frozenset[str] = frozenset()


class DepartmentWall(Protocol):
    """Who a restricted department keeps out (ADR-0032, extending ADR-0006). Departments are kept by their own module;
    Identity asks it through this, inside the transaction it is already in, and only ever about members who are
    neither the company's owner nor an admin, since those reach everything."""

    def shut_out(self, conn: Conn, member: Member) -> ShutOut:
        """The restricted departments of the member's company they are outside of, and the projects in them."""
        ...

    def shut_pairs(self, conn: Conn, pairs: Sequence[tuple[int, str]]) -> set[tuple[int, str]]:
        """Of these members (by row id) each in a project, those the project's restricted department keeps out."""
        ...

    def restricted_department_of(self, conn: Conn, project_id: str) -> str | None:
        """The name of the restricted department a project is in, or None when it is in none or in an open one."""
        ...


class _NoWall:
    """No departments: nothing beyond a project's own access list keeps anyone out."""

    def shut_out(self, conn: Conn, member: Member) -> ShutOut:
        return ShutOut()

    def shut_pairs(self, conn: Conn, pairs: Sequence[tuple[int, str]]) -> set[tuple[int, str]]:
        return set()

    def restricted_department_of(self, conn: Conn, project_id: str) -> str | None:
        return None


@dataclass(frozen=True)
class Caller:
    member: Member
    project: Project | None
    repository: str | None
    # The restricted projects this member isn't allowed into, worked out when the call was authenticated; it includes
    # every project in a restricted department they are outside of.
    unreachable: frozenset[str] = frozenset()
    # The coding agent the session runs in, as it reported itself; None for changes made from the console.
    agent: str | None = None
    # The restricted departments this member is outside of, worked out with `unreachable` (ADR-0032).
    unreachable_departments: frozenset[str] = frozenset()

    def require_reach(self, path: str | None) -> None:
        """Refuse a memory or folder inside a restricted project or restricted department this member isn't allowed
        into.

        A session is authenticated for the project it works in, but a path can point into any project or department,
        so every call that takes one checks it too.
        """
        project_id = project_in(path) if path else None
        if project_id is not None and project_id in self.unreachable:
            raise restricted_project(project_id)
        department_id = department_in(path) if path else None
        if department_id is not None and department_id in self.unreachable_departments:
            raise restricted_department(department_id)

    def reaches(self, path: str | None) -> bool:
        """Whether `require_reach` lets this path through."""
        try:
            self.require_reach(path)
        except Refused:
            return False
        return True

    @property
    def company(self) -> str:
        return self.member.company_code

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
    """The project a memory path or folder is inside, or nothing for company memory."""
    parts = PurePosixPath(path.replace("\\", "/").strip("/")).parts
    return parts[1] if len(parts) >= 2 and parts[0] == "projects" else None


def department_in(path: str) -> str | None:
    """The department a memory path or folder is inside, or nothing outside department memory."""
    parts = PurePosixPath(path.replace("\\", "/").strip("/")).parts
    return parts[1] if len(parts) >= 2 and parts[0] == "departments" else None


def restricted_project(project_id: str) -> Refused:
    """The one refusal a member gets for a restricted project, wherever they meet it."""
    return Refused(
        f"Project {project_id!r} is restricted, so it isn't open to the whole company. "
        "Ask one of its project leads or a company admin to add you to its access list."
    )


def restricted_department(department_id: str) -> Refused:
    """The same refusal for a restricted department's memory, wherever a member outside it meets it."""
    return Refused(
        f"Department {department_id!r} is restricted, so it isn't open to the whole company. "
        "Ask one of its department leads or a company admin to add you to its access list."
    )


def _runs_the_company(member: Member) -> bool:
    return member.is_owner or member.is_admin


def checked_email(value: str) -> str:
    """An email as the company keeps it: trimmed, at most EMAIL_LIMIT characters, exactly one @ with something either
    side, a dot in the domain, and no whitespace or control character. Refused otherwise, without echoing it."""
    cleaned = value.strip()
    local, _, domain = cleaned.partition("@")
    if (
        len(cleaned) > EMAIL_LIMIT
        or cleaned.count("@") != 1
        or not local
        or "." not in domain
        or not cleaned.isascii()
        or any(each.isspace() or unicodedata.category(each) == "Cc" for each in cleaned)
    ):
        raise Refused("That doesn't look like an email address.")
    return cleaned


def check_name(kind: str, value: str) -> str:
    if not NAME_PATTERN.match(value):
        raise Refused(
            f"{kind} {value!r} is not valid: use 1-{NAME_LIMIT} letters, digits, dots, dashes or underscores, "
            "starting with a letter or digit."
        )
    return value


def checked_member_name(name: str) -> str:
    """A member's name as it is stored and signs their saves: one line with a letter or digit, and no < or >."""
    cleaned = name.strip()
    if not any(each.isalnum() for each in cleaned) or len(cleaned) > MEMBER_NAME_LIMIT or signable(cleaned) != cleaned:
        raise Refused(
            f"A member's name is one line of up to {MEMBER_NAME_LIMIT} characters, with a letter or digit and no < or >."
        )
    return cleaned


def checked_project_name(name: str) -> str:
    """A project's name as it is stored and written into the files its repositories commit: one line, as a member's
    name is, with a letter or digit and no < or >."""
    cleaned = name.strip()
    if not cleaned:
        raise Refused("A project needs a name.")
    if not any(each.isalnum() for each in cleaned) or len(cleaned) > MEMBER_NAME_LIMIT or signable(cleaned) != cleaned:
        raise Refused(
            f"A project's name is one line of up to {MEMBER_NAME_LIMIT} characters, with a letter or digit and no < or >."
        )
    return cleaned


def unknown_foundation(slug: str, slugs: list[str]) -> Refused:
    return Refused(f"This project has no {slug!r} foundation. Its foundations are {', '.join(slugs)}.")


# What the matcher reads of a member, to be given a WHERE.
_SIGNING_IN_COLUMNS = (
    "SELECT m.id, m.team_id, t.code, m.member_id, m.name, m.is_owner, m.is_admin, m.removed_at, m.github_login,"
    " m.github_user_id FROM members m JOIN teams t ON t.id = m.team_id"
)
# Whoever holds an email, compared ignoring case, but only among stored values that are ASCII, as emails are.
_HOLDS_ASCII = (
    "(lower(m.added_email) = lower(%s) AND octet_length(m.added_email) = char_length(m.added_email))"
    " OR (lower(m.verified_email) = lower(%s) AND octet_length(m.verified_email) = char_length(m.verified_email))"
)
REMOVED_SIGNING_IN = "You have been removed from this company, so you can no longer sign in."


class Identity:
    def __init__(self, db: Database, clock: Clock, member_cap: Callable[[], int | None] = lambda: None) -> None:
        # The member cap (CONTEXT.md): how many members the server may have at once, or None for no cap. A function,
        # so the cap can come from somewhere that changes while the server runs.
        self.member_cap = member_cap
        # Called when a member may have lost a project: removed from the company, taken off an access list or a lead, no
        # longer an admin, or a project restricted.
        self._access_lost: list[AccessLost] = []
        # Called when a member's GitHub account is moved or taken away, by an admin or on the server.
        self._link_moved: list[LinkMoved] = []
        # Restricted departments keep members out of their projects too; Departments puts its wall up (`walled_by`).
        self._wall: DepartmentWall = _NoWall()
        self._db = db
        self._clock = clock

    def setup_company(
        self,
        company_code: str,
        owner_member_id: str,
        owner_name: str,
        owner_github: str | None = None,
        owner_email: str | None = None,
    ) -> str:
        check_name("Company ID", company_code)
        check_name("Member ID", owner_member_id)
        owner_name = checked_member_name(owner_name)
        email = self._one_way_in(owner_github, owner_email)
        now = self._clock()
        with self._db.transaction() as conn:
            if conn.execute("SELECT 1 FROM teams WHERE code = %s", (company_code,)).fetchone():
                raise Refused(f"Company {company_code!r} already exists.")
            company = conn.execute(
                "INSERT INTO teams (code, created_at) VALUES (%s, %s) RETURNING id", (company_code, now)
            ).fetchone()
            assert company is not None
            member = conn.execute(
                "INSERT INTO members (team_id, member_id, name, is_owner, github_login, added_email, created_at)"
                " VALUES (%s, %s, %s, TRUE, %s, %s, %s) RETURNING id",
                (company["id"], owner_member_id, owner_name, _github_login(owner_github), email, now),
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
                raise Refused("This personal token belongs to a member who has been removed from the company.")
            if row["revoked_at"] is not None:
                raise Refused("This personal token has been revoked. Ask your company's owner for a new one.")
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
            return self._caller(conn, member, project, repository or None)

    def token_id(self, token: str) -> int | None:
        """Which personal token this is, by the number the server keeps it under, or None when it is not one the
        server issued. Revoked tokens and those of removed members are still known: a call is counted against them."""
        with self._db.transaction() as conn:
            found = conn.execute("SELECT id FROM tokens WHERE token_hash = %s", (_hash(token),)).fetchone()
        return found["id"] if found else None

    def token_member(self, token_id: int) -> Member | None:
        """The member a personal token belongs to, by the number the server keeps it under."""
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT m.id, m.team_id, t.code, m.member_id, m.name, m.is_owner, m.is_admin"
                " FROM tokens k JOIN members m ON m.id = k.member_id JOIN teams t ON t.id = m.team_id"
                " WHERE k.id = %s",
                (token_id,),
            ).fetchone()
        if row is None:
            return None
        return Member(
            row["id"], row["team_id"], row["code"], row["member_id"], row["name"], row["is_owner"], row["is_admin"]
        )

    def on_access_lost(self, listener: AccessLost) -> None:
        self._access_lost.append(listener)

    def on_link_moved(self, listener: LinkMoved) -> None:
        self._link_moved.append(listener)

    def _moved_link(self, conn: Conn, member_pk: int, before: str | None, after: str | None) -> None:
        """Tell the listeners when a GitHub link went to another account or none: the same login again, in any case,
        is the same account and moves nothing."""
        if (before or "").lower() != (after or "").lower():
            for listener in self._link_moved:
                listener(conn, member_pk)

    def walled_by(self, wall: DepartmentWall) -> None:
        """Have restricted departments keep members out of their projects (ADR-0032)."""
        self._wall = wall

    def lost_access(self, conn: Conn, caller: Caller) -> Callable[[], None]:
        """`_lost_access`, for a change another module makes that may cost a member a project, such as restricting a
        department."""
        return self._lost_access(conn, caller)

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
            raise Refused("Only the company's owner and its admins can manage members and personal tokens.")

    def _require_owner(self, caller: Caller) -> None:
        if not caller.member.is_owner:
            raise Refused("Only the company's owner can grant admin, take it away, or hand over ownership.")

    def looks_after(self, member: Member, project_id: str) -> bool:
        """Whether this member looks after the project: its leads do, and so do the company's owner and admins, because
        they have to be able to repair it."""
        if member.is_owner or member.is_admin:
            return True
        with self._db.transaction() as conn:
            return self.looks_after_in(conn, member, project_id)

    @staticmethod
    def looks_after_in(conn: Conn, member: Member, project_id: str) -> bool:
        """`looks_after`, asked inside a transaction already open."""
        return member.is_owner or member.is_admin or Identity._leads_it(conn, member.pk, project_id)

    def told_about(self, conn: Conn, company_pk: int, project_id: str) -> list[str]:
        """Who hears about a project as a whole, by member ID: its leads who can reach it, or the company's owner and
        admins where it has none. Asked inside a transaction already open."""
        leads = conn.execute(
            "SELECT m.id, m.member_id FROM project_leads l JOIN members m ON m.id = l.member_id"
            " WHERE l.project_id = %s AND m.removed_at IS NULL ORDER BY m.member_id",
            (project_id,),
        ).fetchall()
        lost = set(self.cannot_reach(conn, company_pk, [(row["id"], project_id) for row in leads]))
        leads = [row for row in leads if (row["id"], project_id) not in lost]
        if not leads:
            leads = conn.execute(
                "SELECT member_id FROM members WHERE team_id = %s AND removed_at IS NULL AND (is_owner OR is_admin)"
                " ORDER BY member_id",
                (company_pk,),
            ).fetchall()
        return [row["member_id"] for row in leads]

    def _require_lead(self, caller: Caller, project_id: str) -> None:
        if not self.looks_after(caller.member, project_id):
            raise Refused("Only this project's leads and the company's admins can change it.")

    @staticmethod
    def _leads_it(conn: Conn, member_pk: int, project_id: str) -> bool:
        found = conn.execute(
            "SELECT 1 FROM project_leads WHERE project_id = %s AND member_id = %s", (project_id, member_pk)
        ).fetchone()
        return found is not None

    def _member_pk(self, conn: Conn, caller: Caller, member_id: str) -> int:
        return self.present_member(conn, caller.member.company_pk, member_id)

    @staticmethod
    def present_member(conn: Conn, company_pk: int, member_id: str) -> int:
        """The row id of a member of this company who hasn't been removed, refused otherwise. Asked inside a
        transaction already open."""
        row = conn.execute(
            "SELECT id FROM members WHERE team_id = %s AND member_id = %s AND removed_at IS NULL",
            (company_pk, member_id),
        ).fetchone()
        if row is None:
            raise Refused(f"No member with member ID {member_id!r} in your company.")
        pk: int = row["id"]
        return pk

    @staticmethod
    def _one_way_in(github: str | None, email: str | None) -> str | None:
        """The email to keep for a member added with a GitHub login or an email, never both: validated, or None."""
        if _github_login(github) is not None and (email or "").strip():
            raise Refused("Give their GitHub username or their email, not both.")
        return checked_email(email) if email is not None and email.strip() else None

    @staticmethod
    def _claim_email(conn: Conn, company_pk: int, email: str, except_pk: int | None) -> None:
        """Make sure no other member of the company holds this email, as the added one or the verified one, ignoring
        case, removed members included. The two columns can race each other, so the company's row is taken first (after
        any member row, always in that order), which lines up everyone claiming an email in this company."""
        conn.execute("SELECT 1 FROM teams WHERE id = %s FOR NO KEY UPDATE", (company_pk,))
        taken = conn.execute(
            "SELECT member_id FROM members WHERE team_id = %s"
            " AND (lower(added_email) = lower(%s) OR lower(verified_email) = lower(%s))"
            " AND (%s::bigint IS NULL OR id <> %s)",
            (company_pk, email, email, except_pk, except_pk),
        ).fetchone()
        if taken is not None:
            raise Refused(f"That email is already held by {taken['member_id']!r} in this company.")

    def add_member(
        self,
        caller: Caller,
        member_id: str,
        name: str,
        company: str | None = None,
        github: str | None = None,
        email: str | None = None,
    ) -> str:
        self._require_admin(caller)
        added = self._one_way_in(github, email)
        if company is not None and company != caller.company:
            raise Refused(f"You can only add members to your own company ({caller.company}).")
        check_name("Member ID", member_id)
        name = checked_member_name(name)
        # Before the transaction: reading the cap can take a connection of its own.
        cap = self.member_cap()
        with self._db.transaction() as conn:
            existing = conn.execute(
                "SELECT removed_at FROM members WHERE team_id = %s AND member_id = %s",
                (caller.member.company_pk, member_id),
            ).fetchone()
            if existing is not None:
                raise Refused(f"Member ID {member_id!r} is already a member of your company, or was one.")
            if cap is not None and self._members_in_use(conn) >= cap:
                raise Refused(
                    f"This server's member cap is {cap} and all {cap} places are taken, so no one more can be added. "
                    "Remove a member to free a place, or raise the cap by setting SHARED_MEMORY_MEMBER_CAP."
                )
            login = _github_login(github)
            if login is not None:
                self._github_free(conn, caller.member.company_pk, login, None)
            if added is not None:
                self._claim_email(conn, caller.member.company_pk, added, None)
            row = conn.execute(
                "INSERT INTO members (team_id, member_id, name, github_login, added_email, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (caller.member.company_pk, member_id, name, login, added, self._clock()),
            ).fetchone()
            assert row is not None
            return self._issue_token(conn, row["id"])

    def _members_in_use(self, conn: Conn) -> int:
        """The members the server has now, in every company. A removed member holds no place."""
        row = conn.execute("SELECT count(*) AS n FROM members WHERE removed_at IS NULL").fetchone()
        assert row is not None
        used: int = row["n"]
        return used

    def members_in_use(self) -> int:
        with self._db.transaction() as conn:
            return self._members_in_use(conn)

    def members_in_company(self, company_code: str) -> int:
        """The members one company has now, counted as the member cap counts them: a removed member holds no place."""
        with self._db.transaction() as conn:
            company = conn.execute("SELECT id FROM teams WHERE code = %s", (company_code,)).fetchone()
            if company is None:
                raise Refused(f"No company {company_code!r} on this server.")
            row = conn.execute(
                "SELECT count(*) AS n FROM members WHERE team_id = %s AND removed_at IS NULL", (company["id"],)
            ).fetchone()
        assert row is not None
        members: int = row["n"]
        return members

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
            self._require_say_over_access(conn, caller, pk, "reissue", "personal token")
            conn.execute(
                "UPDATE tokens SET revoked_at = %s WHERE member_id = %s AND revoked_at IS NULL", (self._clock(), pk)
            )
            return self._issue_token(conn, pk)

    def link_github(self, company_code: str, member_id: str, github_login: str) -> None:
        """Link a GitHub account to a member who already exists, so they can sign in to the console."""
        login = _github_login(github_login)
        if login is None:
            raise Refused("A GitHub username is needed.")
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT m.id, m.github_login FROM members m JOIN teams t ON t.id = m.team_id"
                " WHERE t.code = %s AND m.member_id = %s AND m.removed_at IS NULL FOR NO KEY UPDATE OF m",
                (company_code, member_id),
            ).fetchone()
            if row is None:
                raise Refused(f"No member with member ID {member_id!r} in company {company_code!r}.")
            taken = conn.execute(
                "SELECT m.member_id FROM members m JOIN teams t ON t.id = m.team_id"
                " WHERE t.code = %s AND lower(m.github_login) = lower(%s) AND m.id <> %s",
                (company_code, login, row["id"]),
            ).fetchone()
            if taken is not None:
                raise Refused(f"GitHub account @{login} is already linked to {taken['member_id']!r} in this company.")
            # Clearing the account id makes the next sign-in bind this login to whichever account signs in with it. Moving
            # to another login drops the verified email too, or the account just unlinked would sign straight back in.
            conn.execute(
                "UPDATE members SET github_login = %s, github_user_id = NULL,"
                " verified_email = CASE WHEN lower(%s) = lower(coalesce(github_login, '')) THEN verified_email END"
                " WHERE id = %s",
                (login, login, row["id"]),
            )
            self._moved_link(conn, row["id"], row["github_login"], login)

    def member_signing_in(self, proven: ProvenSignIn) -> SignedIn:
        """The member a sign-in is for, whichever way it came (ADR-0034): the one matcher every sign-in goes through.
        It finds who was proven, refuses unless that is one member still in their company, and keeps what the
        sign-in proved about them. The GitHub account decides it, refusals included, and the email is looked at only when
        the account names no one: then a member who holds the email and has no GitHub linked is linked to it."""
        with self._db.transaction() as conn:
            found = self._named_by(conn, proven)
            if not found:
                return self._found_by_email(conn, proven)
            if len(found) > 1:
                raise Refused(f"{proven.described} is linked to members in more than one company. Ask an admin.")
            row = found[0]
            if row["removed_at"] is not None:
                raise Refused(REMOVED_SIGNING_IN)
            self._keep_proven(conn, row["id"], proven)
            return SignedIn(self._member_of(row))

    @staticmethod
    def _member_of(row: dict[str, Any]) -> Member:
        return Member(
            row["id"], row["team_id"], row["code"], row["member_id"], row["name"], row["is_owner"], row["is_admin"]
        )

    @staticmethod
    def _not_linked(proven: ProvenSignIn) -> Refused:
        return Refused(f"{proven.described} isn't linked to a member. Ask an admin to link it to you.")

    def _found_by_email(self, conn: Conn, proven: ProvenSignIn) -> SignedIn:
        """No member has this GitHub account. Where the sign-in proved an email, the member holding it (added or
        verified, ignoring case) who has no GitHub linked at all is linked to this account; an email never replaces a
        link, and a removed member is never let back in by one."""
        email = proven.matchable_email
        if email is None:
            raise self._not_linked(proven)
        held = conn.execute(_SIGNING_IN_COLUMNS + " WHERE " + _HOLDS_ASCII, (email, email)).fetchall()
        if not held:
            raise self._not_linked(proven)
        if len(held) > 1:
            raise Refused(f"{proven.described} matches members in more than one company. Ask an admin.")
        if held[0]["removed_at"] is not None:
            raise Refused(REMOVED_SIGNING_IN)
        if held[0]["github_login"] is not None or held[0]["github_user_id"] is not None:
            raise self._not_linked(proven)
        # Lock the row, then look again: what was seen may have changed since. The member's row comes before the
        # company's, always in that order.
        row = conn.execute(
            _SIGNING_IN_COLUMNS + " WHERE m.id = %s AND (" + _HOLDS_ASCII + ") FOR NO KEY UPDATE OF m",
            (held[0]["id"], email, email),
        ).fetchone()
        if row is None or row["github_login"] is not None or row["github_user_id"] is not None:
            raise self._not_linked(proven)
        if row["removed_at"] is not None:
            raise Refused(REMOVED_SIGNING_IN)
        conn.execute("SELECT 1 FROM teams WHERE id = %s FOR NO KEY UPDATE", (row["team_id"],))
        try:
            with conn.transaction():
                conn.execute(
                    "UPDATE members SET github_user_id = %s, github_login = %s, verified_email = %s, added_email = NULL"
                    " WHERE id = %s",
                    (proven.github.account_id, proven.github.login, email, row["id"]),
                )
        except UniqueViolation:
            raise self._not_linked(proven) from None
        return SignedIn(self._member_of(row), linked=True)

    @staticmethod
    def _named_by(conn: Conn, proven: ProvenSignIn) -> list[dict[str, Any]]:
        """The members a proven sign-in names: by the GitHub account's id, or by its login where no id is kept yet."""
        return conn.execute(
            _SIGNING_IN_COLUMNS
            + " WHERE m.github_user_id = %s OR (m.github_user_id IS NULL AND lower(m.github_login) = lower(%s))"
            # The lookup locks the row: a change in flight is waited for and the match checked again against it.
            " FOR NO KEY UPDATE OF m",
            (proven.github.account_id, proven.github.login),
        ).fetchall()

    @staticmethod
    def _keep_proven(conn: Conn, member_pk: int, proven: ProvenSignIn) -> None:
        """Keep the account's id from its first sign-in, and the login it goes by now, and what it proved of the email.
        Where the member was added with an email, only that email, ignoring case, is kept, and it becomes their verified
        one. Where they were not, the email is kept when they have no verified one and no other member of the company
        holds it, in either column."""
        conn.execute(
            "UPDATE members SET github_user_id = %s, github_login = %s WHERE id = %s",
            (proven.github.account_id, proven.github.login, member_pk),
        )
        email = proven.matchable_email
        if email is None:
            return
        # The member's row is locked by the update above; the company's comes after it.
        conn.execute(
            "SELECT 1 FROM teams WHERE id = (SELECT team_id FROM members WHERE id = %s) FOR NO KEY UPDATE", (member_pk,)
        )
        # A savepoint, so a second sign-in winning the email between the check and the write costs only the email,
        # not the sign-in's transaction.
        try:
            with conn.transaction():
                promoted = conn.execute(
                    "UPDATE members SET verified_email = %s, added_email = NULL WHERE id = %s"
                    " AND lower(added_email) = lower(%s) AND octet_length(added_email) = char_length(added_email)",
                    (email, member_pk, email),
                )
                if promoted.rowcount:
                    return
                conn.execute(
                    "UPDATE members SET verified_email = %s WHERE id = %s AND verified_email IS NULL"
                    " AND added_email IS NULL AND NOT EXISTS (SELECT 1 FROM members o"
                    " WHERE o.team_id = members.team_id AND o.id <> members.id"
                    " AND (lower(o.verified_email) = lower(%s) OR lower(o.added_email) = lower(%s)))",
                    (email, member_pk, email, email),
                )
        except UniqueViolation:
            pass

    def reissue_own_token(self, member: Member) -> str:
        """A member replaces their own personal token; the one they had stops working."""
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE tokens SET revoked_at = %s WHERE member_id = %s AND revoked_at IS NULL",
                (self._clock(), member.pk),
            )
            return self._issue_token(conn, member.pk)

    def time_zone(self, member_pk: int) -> MemberTimeZone:
        """A member's time zone as kept: the one they chose and the one detected for them, each None until set."""
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT chosen_time_zone, detected_time_zone FROM members WHERE id = %s", (member_pk,)
            ).fetchone()
        if row is None:
            return MemberTimeZone(None, None)
        return MemberTimeZone(row["chosen_time_zone"], row["detected_time_zone"])

    def detect_time_zone(self, member: Member, name: str) -> MemberTimeZone:
        """Keep the time zone a member's browser reported as the one detected for them, while they have chosen none: a
        choice sticks until they choose to have it detected again."""
        checked(name)
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE members SET detected_time_zone = %s WHERE id = %s AND chosen_time_zone IS NULL",
                (name, member.pk),
            )
        return self.time_zone(member.pk)

    def choose_time_zone(self, member: Member, name: str | None) -> MemberTimeZone:
        """A member chooses their own time zone, or None to have it detected for them again."""
        if name is not None:
            checked(name)
        with self._db.transaction() as conn:
            conn.execute("UPDATE members SET chosen_time_zone = %s WHERE id = %s", (name, member.pk))
        return self.time_zone(member.pk)

    def _github_free(self, conn: Conn, company_pk: int, login: str, except_pk: int | None) -> None:
        taken = conn.execute(
            "SELECT member_id FROM members WHERE team_id = %s AND lower(github_login) = lower(%s)"
            " AND (%s::bigint IS NULL OR id <> %s)",
            (company_pk, login, except_pk, except_pk),
        ).fetchone()
        if taken is not None:
            raise Refused(f"GitHub account @{login} is already linked to {taken['member_id']!r} in this company.")

    def _only_the_owner_touches_admins(self, conn: Conn, caller: Caller, pk: int, done: str, verb: str) -> None:
        row = conn.execute("SELECT is_owner, is_admin FROM members WHERE id = %s", (pk,)).fetchone()
        assert row is not None
        if row["is_owner"]:
            raise Refused(f"The company's owner can't be {done}. Hand ownership over first.")
        if row["is_admin"] and not caller.member.is_owner:
            raise Refused(f"Only the company's owner can {verb} an admin.")

    @staticmethod
    def _require_say_over_access(conn: Conn, caller: Caller, pk: int, verb: str, access: str) -> None:
        """Whoever sets how a member gets in can act as them, so it takes standing above them: the owner's is the
        owner's alone, another admin's the owner's. The row stays locked, so their role holds until the change lands."""
        if pk == caller.member.pk:
            return
        row = conn.execute("SELECT is_owner, is_admin FROM members WHERE id = %s FOR UPDATE", (pk,)).fetchone()
        assert row is not None
        if row["is_owner"]:
            raise Refused(f"Only the owner can {verb} the owner's {access}.")
        if row["is_admin"] and not caller.member.is_owner:
            raise Refused(f"Only the company's owner can {verb} another admin's {access}.")

    def members(self, member: Member) -> list[dict[str, Any]]:
        """Everyone in this member's company, with their role and the GitHub account they sign in with."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT member_id, name, is_owner, is_admin, github_login, verified_email, added_email, removed_at FROM members"
                " WHERE team_id = %s ORDER BY is_owner DESC, is_admin DESC, member_id",
                (member.company_pk,),
            ).fetchall()
        return [
            {
                "member_id": row["member_id"],
                "name": row["name"],
                "role": "owner" if row["is_owner"] else "admin" if row["is_admin"] else "member",
                "github_login": row["github_login"],
                "verified_email": row["verified_email"],
                "added_email": row["added_email"],
                "sign_in_methods": ["github"] if row["github_login"] else [],
                "removed": row["removed_at"] is not None,
            }
            for row in rows
        ]

    def change_member(
        self, caller: Caller, member_id: str, name: str | None, github: str | None, email: str | None = None
    ) -> None:
        """Correct a member's name, the GitHub account they sign in with, or the email an admin keeps for them. A new
        email stays unverified until its holder proves it; an empty one clears both the added and the verified."""
        self._require_admin(caller)
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, member_id)
            if email is not None:
                # The member's row before the company's, wherever an email is claimed: a sign-in takes them in this order.
                conn.execute("SELECT 1 FROM members WHERE id = %s FOR NO KEY UPDATE", (pk,))
                self._require_say_over_access(conn, caller, pk, "change", "email")
            if github is not None:
                self._require_say_over_access(conn, caller, pk, "change", "GitHub account")
            wanted = checked_email(email) if email is not None and email.strip() else None
            if name is not None:
                conn.execute("UPDATE members SET name = %s WHERE id = %s", (checked_member_name(name), pk))
            if github is not None:
                login = _github_login(github)
                if login is not None:
                    self._github_free(conn, caller.member.company_pk, login, pk)
                # Clearing the account id lets the next sign-in bind this login to whoever signs in with it. Moving to
                # another login, or none, drops the verified email: the account just unlinked would otherwise sign
                # straight back in by it. The same login again keeps it.
                before = conn.execute("SELECT github_login FROM members WHERE id = %s FOR NO KEY UPDATE", (pk,)).fetchone()
                assert before is not None
                conn.execute(
                    "UPDATE members SET github_login = %s, github_user_id = NULL,"
                    " verified_email = CASE WHEN lower(coalesce(%s, '')) = lower(coalesce(github_login, ''))"
                    " THEN verified_email END WHERE id = %s",
                    (login, login, pk),
                )
                self._moved_link(conn, pk, before["github_login"], login)
            if email is None:
                return
            if wanted is None:
                conn.execute("UPDATE members SET added_email = NULL, verified_email = NULL WHERE id = %s", (pk,))
                return
            self._claim_email(conn, caller.member.company_pk, wanted, pk)
            # The email the member already holds as verified stays as it is: nothing to prove again.
            conn.execute(
                "UPDATE members SET added_email = %s, verified_email = NULL WHERE id = %s"
                " AND lower(coalesce(verified_email, '')) <> lower(%s)",
                (wanted, pk, wanted),
            )

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
        """Make another member the company's owner. The member handing it over stays an admin."""
        self._require_owner(caller)
        if member_id == caller.member_id:
            raise Refused("You are already the owner.")
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, member_id)
            conn.execute("UPDATE members SET is_owner = FALSE, is_admin = TRUE WHERE id = %s", (caller.member.pk,))
            conn.execute("UPDATE members SET is_owner = TRUE, is_admin = TRUE WHERE id = %s", (pk,))

    def is_removed(self, company_code: str, member_id: str) -> bool:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT m.removed_at FROM members m JOIN teams t ON t.id = m.team_id WHERE t.code = %s AND m.member_id = %s",
                (company_code, member_id),
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
                (member.company_pk, member.is_owner or member.is_admin, member.pk, member.pk),
            ).fetchall()
            walled = self._shut_out(conn, member).projects
        return [Project(row["project_id"], row["name"]) for row in rows if row["project_id"] not in walled]

    def _reachable(self, conn: Conn, member: Member, project_id: str) -> Project:
        """One of this member's company's projects, refused if it is restricted and they are not allowed into it."""
        found = conn.execute(
            "SELECT project_id, name, restricted FROM projects WHERE project_id = %s AND team_id = %s",
            (project_id, member.company_pk),
        ).fetchone()
        if found is None:
            raise Refused(f"Project {project_id!r} is not a project in your company.")
        if found["restricted"] and not self._allowed_in(conn, member, project_id):
            raise restricted_project(project_id)
        if not _runs_the_company(member) and self._wall.shut_pairs(conn, [(member.pk, project_id)]):
            raise restricted_project(project_id)
        return Project(found["project_id"], found["name"])

    def _shut_out(self, conn: Conn, member: Member) -> ShutOut:
        """What restricted departments keep this member out of; nothing for the company's owner and admins."""
        return ShutOut() if _runs_the_company(member) else self._wall.shut_out(conn, member)

    def _caller(self, conn: Conn, member: Member, project: Project | None, repository: str | None) -> Caller:
        walled = self._shut_out(conn, member)
        return Caller(
            member,
            project,
            repository,
            self._unreachable(conn, member) | walled.projects,
            unreachable_departments=walled.departments,
        )

    @staticmethod
    def _unreachable(conn: Conn, member: Member) -> frozenset[str]:
        """The restricted projects of this member's company that their own access lists keep them out of."""
        if member.is_owner or member.is_admin:
            return frozenset()
        rows = conn.execute(
            "SELECT p.project_id FROM projects p WHERE p.team_id = %s AND p.restricted"
            " AND NOT EXISTS (SELECT 1 FROM project_leads l WHERE l.project_id = p.project_id AND l.member_id = %s)"
            " AND NOT EXISTS (SELECT 1 FROM project_access a WHERE a.project_id = p.project_id AND a.member_id = %s)",
            (member.company_pk, member.pk, member.pk),
        ).fetchall()
        return frozenset(row["project_id"] for row in rows)

    def _allowed_in(self, conn: Conn, member: Member, project_id: str) -> bool:
        """Who a restricted project lets in: the company's owner and admins, its leads, and its access list."""
        if member.is_owner or member.is_admin or self._leads_it(conn, member.pk, project_id):
            return True
        found = conn.execute(
            "SELECT 1 FROM project_access WHERE project_id = %s AND member_id = %s", (project_id, member.pk)
        ).fetchone()
        return found is not None

    def member_reaching(self, caller: Caller, project_id: str, member_id: str) -> int:
        """A member of the caller's company who can reach this project, such as a card's assignee; refused otherwise."""
        with self._db.transaction() as conn:
            pk = self._member_pk(conn, caller, member_id)
            row = conn.execute(
                "SELECT NOT p.restricted OR m.is_owner OR m.is_admin"
                " OR EXISTS (SELECT 1 FROM project_leads l WHERE l.project_id = p.project_id AND l.member_id = m.id)"
                " OR EXISTS (SELECT 1 FROM project_access a WHERE a.project_id = p.project_id AND a.member_id = m.id)"
                " AS reaches, m.is_owner OR m.is_admin AS runs FROM projects p, members m"
                " WHERE p.project_id = %s AND m.id = %s",
                (project_id, pk),
            ).fetchone()
            walled = row is not None and not row["runs"] and bool(self._wall.shut_pairs(conn, [(pk, project_id)]))
        if row is None or not row["reaches"] or walled:
            raise Refused(
                f"{member_id!r} can't reach project {project_id!r}: it is restricted and they aren't on its access list."
            )
        return pk

    def named(self, member_pks: Iterable[int]) -> dict[int, tuple[str, str]]:
        """Members kept by their row id elsewhere, each as its member ID and name."""
        asked = list(set(member_pks))
        if not asked:
            return {}
        with self._db.transaction() as conn:
            return self.named_in(conn, asked)

    @staticmethod
    def named_in(conn: Conn, member_pks: Iterable[int]) -> dict[int, tuple[str, str]]:
        """`named`, asked inside a transaction already open."""
        asked = list(set(member_pks))
        if not asked:
            return {}
        rows = conn.execute("SELECT id, member_id, name FROM members WHERE id = ANY(%s)", (asked,)).fetchall()
        return {row["id"]: (row["member_id"], row["name"]) for row in rows}

    @staticmethod
    def in_company(conn: Conn, company_pk: int, member_ids: Iterable[str]) -> dict[str, tuple[int, str]]:
        """These members of a company by member ID, removed ones too, each as its row id and name. Asked inside a
        transaction already open."""
        asked = list(set(member_ids))
        if not asked:
            return {}
        rows = conn.execute(
            "SELECT id, member_id, name FROM members WHERE team_id = %s AND member_id = ANY(%s)", (company_pk, asked)
        ).fetchall()
        return {row["member_id"]: (row["id"], row["name"]) for row in rows}

    @staticmethod
    def present(conn: Conn, member_pk: int) -> Member | None:
        """The member with this row id, or None once they have been removed from the company. Asked inside a
        transaction already open."""
        row = conn.execute(
            "SELECT m.id, m.team_id, t.code, m.member_id, m.name, m.is_owner, m.is_admin, m.removed_at"
            " FROM members m JOIN teams t ON t.id = m.team_id WHERE m.id = %s",
            (member_pk,),
        ).fetchone()
        if row is None or row["removed_at"] is not None:
            return None
        return Member(
            row["id"], row["team_id"], row["code"], row["member_id"], row["name"], row["is_owner"], row["is_admin"]
        )

    @staticmethod
    def company_projects(conn: Conn, company_pk: int) -> list[str]:
        """The project IDs of this company's projects, asked inside a transaction already open."""
        rows = conn.execute("SELECT project_id FROM projects WHERE team_id = %s", (company_pk,)).fetchall()
        return [row["project_id"] for row in rows]

    def cannot_reach(self, conn: Conn, company_pk: int, pairs: Sequence[tuple[int, str]]) -> list[tuple[int, str]]:
        """Of these members (by row id) each in a project, those of this company who can no longer reach it: removed
        from the company, or shut out of a restricted project or restricted department. Asked inside the transaction
        of the change."""
        if not pairs:
            return []
        rows = conn.execute(
            "SELECT x.member_id, x.project_id FROM unnest(%s::bigint[], %s::text[]) AS x(member_id, project_id)"
            " JOIN members m ON m.id = x.member_id JOIN projects p ON p.project_id = x.project_id"
            " WHERE p.team_id = %s AND (m.removed_at IS NOT NULL OR (p.restricted AND NOT m.is_owner AND NOT m.is_admin"
            " AND NOT EXISTS (SELECT 1 FROM project_leads l WHERE l.project_id = p.project_id AND l.member_id = m.id)"
            " AND NOT EXISTS (SELECT 1 FROM project_access a WHERE a.project_id = p.project_id AND a.member_id = m.id)"
            "))",
            ([pk for pk, _ in pairs], [project_id for _, project_id in pairs], company_pk),
        ).fetchall()
        lost = [(row["member_id"], row["project_id"]) for row in rows]
        # The company's owner and admins reach every department; removed members are already counted above.
        kept_out = {
            row["id"]
            for row in conn.execute(
                "SELECT id FROM members WHERE id = ANY(%s) AND team_id = %s AND removed_at IS NULL"
                " AND NOT is_owner AND NOT is_admin",
                (list({pk for pk, _ in pairs}), company_pk),
            ).fetchall()
        }
        walled = self._wall.shut_pairs(conn, [pair for pair in pairs if pair[0] in kept_out])
        return lost + [pair for pair in dict.fromkeys(pairs) if pair in walled and pair not in lost]

    def member_with_github(self, caller: Caller, login: str) -> str | None:
        """The member ID of the member of the caller's company who signs in with this GitHub account, if there is one."""
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT member_id FROM members WHERE team_id = %s AND lower(github_login) = lower(%s)"
                " AND removed_at IS NULL",
                (caller.member.company_pk, _github_login(login) or ""),
            ).fetchone()
        return None if row is None else str(row["member_id"])

    def caller_in(self, member: Member, project_id: str | None) -> Caller:
        """The member as a caller of the memory services, working in one of their company's projects."""
        with self._db.transaction() as conn:
            project = None if project_id is None else self._reachable(conn, member, project_id)
            return self._caller(conn, member, project, None)

    def create_project(self, caller: Caller, name: str) -> Project:
        """Create a project. Whoever creates it is its first project lead."""
        name = checked_project_name(name)
        now = self._clock()
        # Project IDs are unique across every company and the suffix is random, so two projects with a common name can
        # draw the same suffix: draw again rather than fail the member.
        for attempt in range(PROJECT_ID_ATTEMPTS):
            project_id = f"{slugify(name)[:40].strip('-')}-{secrets.token_hex(4)}"
            try:
                with self._db.transaction() as conn:
                    conn.execute(
                        "INSERT INTO projects (project_id, team_id, name, created_at) VALUES (%s, %s, %s, %s)",
                        (project_id, caller.member.company_pk, name.strip(), now),
                    )
                    conn.execute(
                        "INSERT INTO project_leads (project_id, member_id, appointed_at) VALUES (%s, %s, %s)",
                        (project_id, caller.member.pk, now),
                    )
            except UniqueViolation:
                if attempt == PROJECT_ID_ATTEMPTS - 1:
                    raise
                continue
            return Project(project_id, name.strip())
        raise AssertionError("unreachable")  # pragma: no cover

    def rename_project(self, caller: Caller, project_id: str, name: str) -> None:
        """Change a project's name. Its project ID never changes: repositories are committed with it."""
        name = checked_project_name(name)
        self._require_lead(caller, project_id)
        with self._db.transaction() as conn:
            self._project_name(conn, caller.member, project_id)
            conn.execute("UPDATE projects SET name = %s WHERE project_id = %s", (name.strip(), project_id))

    def leads_of(self, member: Member) -> list[str]:
        """The projects this member leads and can reach: a lead a restricted department keeps out leads none of it."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT l.project_id FROM project_leads l JOIN projects p ON p.project_id = l.project_id"
                " WHERE l.member_id = %s AND p.team_id = %s ORDER BY l.project_id",
                (member.pk, member.company_pk),
            ).fetchall()
            walled = self._shut_out(conn, member).projects
        return [row["project_id"] for row in rows if row["project_id"] not in walled]

    @staticmethod
    def _project_name(conn: Conn, member: Member, project_id: str) -> str:
        """The project's name, if it is one of this member's company's projects."""
        row = conn.execute(
            "SELECT name FROM projects WHERE project_id = %s AND team_id = %s", (project_id, member.company_pk)
        ).fetchone()
        if row is None:
            raise Refused(f"Project {project_id!r} is not a project in your company.")
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
            keepers = self.keepers_listed(conn, project_id)
            foundations = self._foundations_listed(conn, project_id)
        return {
            "project_id": project_id,
            "name": project.name,
            "restricted": row["restricted"],
            "leads": leads,
            "foundations": [
                {"slug": slug, "name": name, "core": core, "keepers": keepers.get(slug, [])}
                for slug, name, core in foundations
            ],
            "access": [{"member_id": one["member_id"], "name": one["name"]} for one in access],
            "repositories": [row["name"] for row in repositories],
            "you_lead": you_lead,
            "you_may_change": you_lead or member.is_owner or member.is_admin,
        }

    def restrict(self, caller: Caller, project_id: str, restricted: bool) -> None:
        """Close a project to its access list, or open it to the whole company again.

        Unrestricting keeps the access list, so restricting it again lets the same members straight back in. A project
        inside a restricted department is never opened to the whole company (ADR-0032).
        """
        self._require_lead(caller, project_id)
        with self._db.transaction() as conn:
            name = self._project_name(conn, caller.member, project_id)
            department = None if restricted else self._wall.restricted_department_of(conn, project_id)
            if department is not None:
                raise Refused(
                    f"Project {name!r} is in the restricted department {department!r}, so it can't be opened to the "
                    "whole company. Open the department, or move the project out of it, first."
                )
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
        """Take a lead off a project. Only the company's admins can, so one lead can't unseat another."""
        if not (caller.member.is_owner or caller.member.is_admin):
            raise Refused("Only the company's owner and its admins can take a lead off a project.")
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

    def keeps(self, member: Member, project_id: str, foundation: str) -> bool:
        """Whether this member keeps this foundation of the project. A keeper who can no longer reach the project has
        been dropped, so a row is all it takes."""
        with self._db.transaction() as conn:
            found = conn.execute(
                "SELECT 1 FROM foundation_keepers WHERE project_id = %s AND foundation = %s AND member_id = %s",
                (project_id, foundation, member.pk),
            ).fetchone()
        return found is not None

    def keeps_any(self, member: Member, project_id: str) -> bool:
        """Whether this member keeps at least one foundation of the project."""
        with self._db.transaction() as conn:
            found = conn.execute(
                "SELECT 1 FROM foundation_keepers WHERE project_id = %s AND member_id = %s LIMIT 1",
                (project_id, member.pk),
            ).fetchone()
        return found is not None

    @staticmethod
    def _foundations_listed(conn: Conn, project_id: str) -> list[tuple[str, str, bool]]:
        """A project's foundations as (slug, name, whether core): the core four, then its extras in the order added."""
        listed = [(slug, foundation_title(slug), True) for slug in CORE_FOUNDATIONS]
        rows = conn.execute(
            "SELECT slug, name FROM project_foundations WHERE project_id = %s ORDER BY added_at, slug", (project_id,)
        ).fetchall()
        return listed + [(row["slug"], row["name"], False) for row in rows]

    def foundation_name(self, project_id: str, slug: str) -> str:
        """What a project calls one of its foundations; its slug, capitalised, when it is gone."""
        with self._db.transaction() as conn:
            named = {one: name for one, name, _ in self._foundations_listed(conn, project_id)}
        return named.get(slug, foundation_title(slug))

    def foundations_of(self, project_id: str) -> list[str]:
        """The slugs of a project's foundations, core and extra."""
        with self._db.transaction() as conn:
            return [slug for slug, _, _ in self._foundations_listed(conn, project_id)]

    def _require_foundation(self, conn: Conn, project_id: str, foundation: str) -> None:
        slugs = [slug for slug, _, _ in self._foundations_listed(conn, project_id)]
        if foundation not in slugs:
            raise unknown_foundation(foundation, slugs)

    def add_foundation(self, caller: Caller, project_id: str, name: str, leads_only: bool = False) -> str:
        """Add an extra foundation to a project and answer its slug. A lead can; so can an admin, unless `leads_only`.
        Its name can't be empty or stand for a foundation the project already has."""
        if leads_only:
            if project_id not in self.leads_of(caller.member):
                raise Refused("Only this project's leads can add a foundation.")
        else:
            self._require_lead(caller, project_id)
        if not re.search(r"[a-z0-9]", name.lower()):
            raise Refused("A foundation needs a name with letters or digits in it.")
        if len(name.strip()) > NAME_LIMIT:
            raise Refused(f"A foundation's name is at most {NAME_LIMIT} characters.")
        slug = slugify(name)
        with self._db.transaction() as conn:
            self._project_name(conn, caller.member, project_id)
            if slug in [one for one, _, _ in self._foundations_listed(conn, project_id)]:
                raise Refused(f"This project already has a {slug!r} foundation.")
            conn.execute(
                "INSERT INTO project_foundations (project_id, slug, name, added_by, added_at) VALUES (%s, %s, %s, %s, %s)",
                (project_id, slug, name.strip(), caller.member.pk, self._clock()),
            )
        return slug

    def require_extra_foundation(self, caller: Caller, project_id: str, slug: str) -> None:
        """Refuse removing what isn't an extra foundation of this project: a core one, or one it doesn't have."""
        self._require_lead(caller, project_id)
        if slug in CORE_FOUNDATIONS:
            raise Refused(f"The {slug} foundation is one of the core four, and can't be removed.")
        with self._db.transaction() as conn:
            self._project_name(conn, caller.member, project_id)
            self._require_foundation(conn, project_id, slug)

    def remove_foundation(self, caller: Caller, project_id: str, slug: str) -> None:
        """Remove an extra foundation, and its keepers with it."""
        self.require_extra_foundation(caller, project_id, slug)
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM foundation_keepers WHERE project_id = %s AND foundation = %s", (project_id, slug))
            conn.execute("DELETE FROM project_foundations WHERE project_id = %s AND slug = %s", (project_id, slug))

    def assign_keeper(self, caller: Caller, project_id: str, foundation: str, member_id: str) -> None:
        """Make a member a keeper of one of this project's foundations. A lead can; so can an admin. The member must
        be able to reach the project."""
        self._require_lead(caller, project_id)
        with self._db.transaction() as conn:
            self._project_name(conn, caller.member, project_id)
            self._require_foundation(conn, project_id, foundation)
            pk = self._member_pk(conn, caller, member_id)
            if self.cannot_reach(conn, caller.member.company_pk, [(pk, project_id)]):
                raise Refused(
                    f"{member_id!r} can't reach project {project_id!r}: it is restricted and they aren't on its "
                    "access list."
                )
            conn.execute(
                "INSERT INTO foundation_keepers (project_id, foundation, member_id, assigned_by, assigned_at)"
                " VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (project_id, foundation, pk, caller.member.pk, self._clock()),
            )

    def remove_keeper(self, caller: Caller, project_id: str, foundation: str, member_id: str) -> None:
        """Take a keeper off a foundation."""
        self._require_lead(caller, project_id)
        with self._db.transaction() as conn:
            self._project_name(conn, caller.member, project_id)
            self._require_foundation(conn, project_id, foundation)
            pk = self._member_pk(conn, caller, member_id)
            removed = conn.execute(
                "DELETE FROM foundation_keepers WHERE project_id = %s AND foundation = %s AND member_id = %s"
                " RETURNING member_id",
                (project_id, foundation, pk),
            ).fetchone()
        if removed is None:
            raise Refused(f"{member_id!r} does not keep the {foundation} foundation.")

    def drop_keepers(self, conn: Conn, caller: Caller) -> list[tuple[str, str, str]]:
        """Drop the keeper assignments of members who can no longer reach their project, as (project ID, foundation,
        member ID). Asked inside the transaction of the change that cost them it."""
        company_pk = caller.member.company_pk
        held = conn.execute(
            "SELECT DISTINCT member_id, project_id FROM foundation_keepers WHERE project_id = ANY(%s)",
            (self.company_projects(conn, company_pk),),
        ).fetchall()
        lost = self.cannot_reach(conn, company_pk, [(row["member_id"], row["project_id"]) for row in held])
        if not lost:
            return []
        dropped = conn.execute(
            "DELETE FROM foundation_keepers k USING unnest(%s::bigint[], %s::text[]) AS x(member_id, project_id),"
            " members m WHERE k.member_id = x.member_id AND k.project_id = x.project_id AND m.id = k.member_id"
            " RETURNING k.project_id, k.foundation, m.member_id",
            ([pk for pk, _ in lost], [project_id for _, project_id in lost]),
        ).fetchall()
        return sorted((row["project_id"], row["foundation"], row["member_id"]) for row in dropped)

    @staticmethod
    def keepers_listed(conn: Conn, project_id: str) -> dict[str, list[dict[str, str]]]:
        """The keepers of each foundation of one project that has any, by slug."""
        rows = conn.execute(
            "SELECT k.foundation, m.member_id, m.name FROM foundation_keepers k JOIN members m ON m.id = k.member_id"
            " WHERE k.project_id = %s AND m.removed_at IS NULL ORDER BY m.member_id",
            (project_id,),
        ).fetchall()
        listed: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            listed.setdefault(row["foundation"], []).append({"member_id": row["member_id"], "name": row["name"]})
        return listed

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
