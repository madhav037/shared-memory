"""Signing in to the console with GitHub, and the sessions that follow (ADR-0007).

A personal token proves who a Claude session belongs to; it never goes into a browser. The console instead sends the
member to GitHub, and what comes back is matched to the member an admin linked that GitHub account to.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.identity import Identity, Member

COOKIE = "shared_memory_console"
SIGN_IN_PATH = "/api/sign-in/github"
CALLBACK_PATH = f"{SIGN_IN_PATH}/callback"
STATE_MINUTES = 10


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class GitHubAccount:
    account_id: int
    login: str


class ConsoleSessions:
    """Sign-ins in flight, and the sessions they leave behind."""

    def __init__(self, settings: Settings, db: Database, identity: Identity, clock: Clock) -> None:
        self._settings = settings
        self._db = db
        self._identity = identity
        self._clock = clock

    @property
    def configured(self) -> bool:
        return self._settings.github_sign_in

    def _require_configured(self) -> None:
        if not self.configured:
            raise Refused(
                "Signing in with GitHub isn't set up on this server. "
                "The person running it sets the GitHub app's client ID and secret."
            )

    def redirect_uri(self, base_url: str) -> str:
        """Where GitHub sends the member back: the console's own address when the server knows it."""
        root = (self._settings.console_url or base_url).rstrip("/")
        return f"{root}{CALLBACK_PATH}"

    def start(self, base_url: str) -> str:
        """Begin a sign-in: remember a one-time state and return the address on GitHub to send the member to."""
        self._require_configured()
        state = secrets.token_urlsafe(24)
        now = self._clock()
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM console_sign_ins WHERE created_at < %s", (now - timedelta(minutes=STATE_MINUTES),))
            conn.execute(
                "INSERT INTO console_sign_ins (state_hash, created_at) VALUES (%s, %s)", (_hash(state), now)
            )
        query = urlencode(
            {
                "client_id": self._settings.github_client_id,
                "redirect_uri": self.redirect_uri(base_url),
                "scope": "read:user",
                "state": state,
            }
        )
        return f"{self._settings.github_sign_in_url.rstrip('/')}/login/oauth/authorize?{query}"

    def finish(self, code: str, state: str, base_url: str) -> str:
        """Complete a sign-in and return the session's token, or refuse with what to tell the member."""
        self._require_configured()
        self._spend_state(state)
        account = self._account(self._access_token(code, base_url))
        member = self._identity.member_for_github(account.account_id, account.login)
        return self._begin_session(member)

    def _spend_state(self, state: str) -> None:
        now = self._clock()
        with self._db.transaction() as conn:
            row = conn.execute(
                "DELETE FROM console_sign_ins WHERE state_hash = %s AND created_at >= %s RETURNING state_hash",
                (_hash(state), now - timedelta(minutes=STATE_MINUTES)),
            ).fetchone()
        if row is None:
            raise Refused("That sign-in didn't come from this console, or it took too long. Try again.")

    def _access_token(self, code: str, base_url: str) -> str:
        response = httpx.post(
            f"{self._settings.github_sign_in_url.rstrip('/')}/login/oauth/access_token",
            json={
                "client_id": self._settings.github_client_id,
                "client_secret": self._settings.github_client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri(base_url),
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        token = self._answer(response).get("access_token")
        if not isinstance(token, str) or not token:
            raise Refused("GitHub didn't accept that sign-in. Try again.")
        return token

    def _account(self, access_token: str) -> GitHubAccount:
        response = httpx.get(
            f"{self._settings.github_api_url.rstrip('/')}/user",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
            timeout=15,
        )
        body = self._answer(response)
        account_id, login = body.get("id"), body.get("login")
        if not isinstance(account_id, int) or not isinstance(login, str):
            raise Refused("GitHub didn't say who you are. Try again.")
        return GitHubAccount(account_id, login)

    @staticmethod
    def _answer(response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise Refused("GitHub couldn't be reached to sign you in. Try again.")
        try:
            body = response.json()
        except ValueError:
            raise Refused("GitHub's answer wasn't understood. Try again.") from None
        if not isinstance(body, dict) or "error" in body:
            raise Refused("GitHub didn't accept that sign-in. Try again.")
        return body

    def _begin_session(self, member: Member) -> str:
        token = "smc_" + secrets.token_urlsafe(32)
        now = self._clock()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO console_sessions (member_id, token_hash, created_at, used_at) VALUES (%s, %s, %s, %s)",
                (member.pk, _hash(token), now, now),
            )
        return token

    def member_for(self, token: str | None) -> Member | None:
        """Who this session belongs to, or nobody if it has expired, ended, or the member has been removed."""
        if not token:
            return None
        now = self._clock()
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT s.id, s.created_at, s.used_at, s.ended_at,"
                " m.id AS member_pk, m.team_id, t.code, m.member_id, m.name, m.is_owner, m.removed_at"
                " FROM console_sessions s JOIN members m ON m.id = s.member_id JOIN teams t ON t.id = m.team_id"
                " WHERE s.token_hash = %s",
                (_hash(token),),
            ).fetchone()
            if row is None or row["ended_at"] is not None or row["removed_at"] is not None:
                return None
            if now - row["used_at"] > timedelta(hours=self._settings.console_session_idle_hours):
                return None
            if now - row["created_at"] > timedelta(days=self._settings.console_session_days):
                return None
            conn.execute("UPDATE console_sessions SET used_at = %s WHERE id = %s", (now, row["id"]))
            return Member(row["member_pk"], row["team_id"], row["code"], row["member_id"], row["name"], row["is_owner"])

    def end(self, token: str | None) -> None:
        if not token:
            return
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE console_sessions SET ended_at = %s WHERE token_hash = %s AND ended_at IS NULL",
                (self._clock(), _hash(token)),
            )
