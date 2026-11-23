"""Signing in to the console with GitHub, and the sessions that follow (ADR-0007).

A personal token proves who a Claude session belongs to; it never goes into a browser. The console instead sends the
member to GitHub, and what comes back is matched to the member an admin linked that GitHub account to. A hosted server
has no GitHub app of its own: it sends the member to the platform, which signs them in with GitHub and hands the
result back, signed (platform_sign_in.py). Either way the member is then signed in the same way.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from shared_memory.audit import SIGN_IN_REFUSED, SIGNED_IN, Audit
from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.identity import GitHubAccount, Identity, Member, ProvenSignIn
from shared_memory.platform_sign_in import MAX_LIFETIME, InvalidSignIn, verify

COOKIE = "shared_memory_console"
# The cookie holding what the browser was sent away with, the nonce for the platform or the state for GitHub, until
# the sign-in comes back: a sign-in finishes only in the browser that started it.
NONCE_COOKIE = "shared_memory_sign_in_nonce"
SIGN_IN_PATH = "/api/sign-in/github"
CALLBACK_PATH = f"{SIGN_IN_PATH}/callback"
# Where the platform hands a sign-in back to, as `?sign_in=<the handed-over sign-in>`.
HANDED_OVER_PATH = "/api/sign-in/platform/callback"
STATE_MINUTES = 10


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def end_member_sessions(conn: Conn, member_pk: int, at: datetime) -> None:
    """End every open console session of one member, in the caller's transaction."""
    conn.execute("UPDATE console_sessions SET ended_at = %s WHERE ended_at IS NULL AND member_id = %s", (at, member_pk))


@dataclass(frozen=True)
class SignInStarted:
    """Where to send the member to sign in, and the one-time value the browser keeps meanwhile."""

    url: str
    nonce: str


class ConsoleSessions:
    """Sign-ins in flight, and the sessions they leave behind."""

    def __init__(self, settings: Settings, db: Database, identity: Identity, audit: Audit, clock: Clock) -> None:
        self._settings = settings
        self._db = db
        self._identity = identity
        self._audit = audit
        self._clock = clock

    @property
    def configured(self) -> bool:
        return self._settings.github_sign_in

    def _require_configured(self) -> None:
        if self.configured:
            return
        if self._settings.signs_in_through_platform:
            raise Refused(
                "Signing in through the platform isn't set up on this server. "
                "The person running it sets the platform's address, its public key and this server's subdomain."
            )
        raise Refused(
            "Signing in with GitHub isn't set up on this server. "
            "The person running it sets the GitHub app's client ID and secret."
        )

    def redirect_uri(self, base_url: str) -> str:
        """Where GitHub sends the member back: the console's own address when the server knows it."""
        root = (self._settings.console_url or base_url).rstrip("/")
        return f"{root}{CALLBACK_PATH}"

    def start(self, base_url: str) -> SignInStarted:
        """Begin a sign-in: remember a one-time state and return the address on GitHub to send the member to, with that
        state for the browser to keep in a cookie. A server
        that signs in through the platform sends the member there instead, naming its subdomain, where to come back and
        a one-time nonce, which the browser keeps in a cookie until the sign-in comes back carrying it."""
        self._require_configured()
        if self._settings.signs_in_through_platform:
            back = f"{(self._settings.console_url or base_url).rstrip('/')}{HANDED_OVER_PATH}"
            nonce = secrets.token_urlsafe(24)
            query = urlencode({"subdomain": self._settings.subdomain, "return_to": back, "nonce": nonce})
            return SignInStarted(f"{self._settings.platform_url.rstrip('/')}/sign-in?{query}", nonce)
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
                "scope": "read:user user:email",
                "state": state,
            }
        )
        return SignInStarted(f"{self._settings.github_sign_in_url.rstrip('/')}/login/oauth/authorize?{query}", state)

    def finish(self, code: str, state: str, base_url: str, kept: str | None) -> str:
        """Complete a sign-in and return the session's token, or refuse with what to tell the member: its state must
        be the one this browser was sent with (`kept`, from its cookie), checked before it is spent."""
        self._require_configured()
        if self._settings.signs_in_through_platform:
            raise Refused("This server signs members in through the platform, not with a GitHub app of its own.")
        self._require_started_here(state, kept)
        self._spend_state(state)
        token = self._access_token(code, base_url)
        return self._sign_in_by(ProvenSignIn(self._account(token), self._verified_email(token)))

    def finish_handed_over(self, text: str, nonce: str | None) -> str:
        """Complete a sign-in the platform handed over and return the session's token, or refuse with what to tell the
        member: it must be signed by the platform, name this server's subdomain, not have expired nor expire too far
        ahead, carry the nonce this browser was sent with (`nonce`, from its cookie), and be used once. A sign-in landing
        in another browser is refused before it is spent, so the browser that started it can still finish it."""
        if not self._settings.signs_in_through_platform:
            raise Refused("This server doesn't take sign-ins from the platform. Sign in with GitHub here.")
        self._require_configured()
        try:
            handed = verify(text, self._settings.platform_public_key)
        except InvalidSignIn as wrong:
            raise Refused(str(wrong)) from None
        if handed.subdomain != self._settings.subdomain:
            raise Refused("That sign-in was for another company's server, so it can't sign you in here. Try again.")
        now = self._clock()
        if handed.expires <= now:
            raise Refused("That sign-in took too long. Try again.")
        if handed.expires > now + MAX_LIFETIME:
            raise Refused("That sign-in couldn't be checked, so it can't be trusted. Try again.")
        self._require_started_here(handed.nonce, nonce)
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM handed_over_sign_ins WHERE expires_at <= %s", (now,))
            spent = conn.execute(
                "INSERT INTO handed_over_sign_ins (id, expires_at) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING"
                " RETURNING id",
                (handed.id, handed.expires),
            ).fetchone()
        if spent is None:
            raise Refused("That sign-in was already used. Sign in again.")
        return self._sign_in_by(ProvenSignIn(GitHubAccount(handed.github_id, handed.github_login)))

    def _sign_in_by(self, proven: ProvenSignIn) -> str:
        """Sign in the member this proven sign-in is for, and return the session's token. Every way in ends here."""
        try:
            signed = self._identity.member_signing_in(proven)
        except Refused as refused:
            self._audit.record(SIGN_IN_REFUSED, actor=proven.actor, detail={"reason": str(refused)})
            raise
        member = signed.member
        token = self._begin_session(member)
        # An email is never kept in the log: only that this sign-in linked the account through one.
        detail: dict[str, Any] = {**proven.audited, **({"linked": True} if signed.linked else {})}
        self._audit.record(SIGNED_IN, member=member, detail=detail)
        return token

    @staticmethod
    def _require_started_here(returned: str, kept: str | None) -> None:
        """Refuse a sign-in coming back to a browser other than the one that was sent away with it."""
        if not kept or not secrets.compare_digest(returned.encode(), kept.encode()):
            raise Refused("That sign-in didn't start in this browser, so it can't sign you in here. Sign in again.")

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

    def _verified_email(self, access_token: str) -> str | None:
        """The account's primary email, only if GitHub says it is verified. Anything going wrong reading it, or
        reading it as something other than the list GitHub documents, means no email, never a refused sign-in."""
        try:
            response = httpx.get(
                f"{self._settings.github_api_url.rstrip('/')}/user/emails",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
                timeout=10,
            )
            if response.status_code != 200:
                return None
            body = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(body, list):
            return None
        for one in body:
            if not isinstance(one, dict) or one.get("primary") is not True or one.get("verified") is not True:
                continue
            email = one.get("email")
            if isinstance(email, str) and email.strip():
                return email.strip()
        return None

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
                "SELECT id, member_id, created_at, used_at, ended_at FROM console_sessions WHERE token_hash = %s",
                (_hash(token),),
            ).fetchone()
            if row is None or row["ended_at"] is not None:
                return None
            if now - row["used_at"] > timedelta(hours=self._settings.console_session_idle_hours):
                return None
            if now - row["created_at"] > timedelta(days=self._settings.console_session_days):
                return None
            member = self._identity.present(conn, row["member_id"])
            if member is None:
                return None
            conn.execute("UPDATE console_sessions SET used_at = %s WHERE id = %s", (now, row["id"]))
            return member

    def member_pk_of(self, token: str | None) -> int | None:
        """The number the server keeps the member under whose session this is, or None when it is no session of
        theirs or has ended. Looks only: the session's use is not marked, and its expiry not judged."""
        if not token:
            return None
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT member_id FROM console_sessions WHERE token_hash = %s AND ended_at IS NULL", (_hash(token),)
            ).fetchone()
        return int(row["member_id"]) if row else None

    def end_for_moved_link(self, conn: Conn, member_pk: int) -> None:
        """End a member's console sessions when their GitHub account is moved or taken away, inside that change."""
        end_member_sessions(conn, member_pk, self._clock())

    def end_all_for(self, member_id: str, company_pk: int) -> None:
        """End every console session of one member, for when they are removed from the company."""
        with self._db.transaction() as conn:
            found = self._identity.in_company(conn, company_pk, [member_id]).get(member_id)
            if found is None:
                return
            conn.execute(
                "UPDATE console_sessions SET ended_at = %s WHERE ended_at IS NULL AND member_id = %s",
                (self._clock(), found[0]),
            )

    def end(self, token: str | None) -> None:
        if not token:
            return
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE console_sessions SET ended_at = %s WHERE token_hash = %s AND ended_at IS NULL",
                (self._clock(), _hash(token)),
            )
