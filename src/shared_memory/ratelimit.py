"""The rate limit: a ceiling on how many calls one caller can make a minute, so one bad caller can't take the server
down for everyone (CONTEXT.md).

A caller is counted by what it carries: a personal token it carries is counted per personal token; a console session's
cookie, per member and apart from their coding agents, so browsing the console never uses up their allowance; and a
call with neither, or with ones the server doesn't know, per address, because there is nothing else to count it by.
The address is the one the server already trusts behind Caddy.

Each caller has a bucket in Postgres holding the calls it may still make. A call takes one; the bucket refills at the
limit's pace, up to a burst of a quarter of a minute's allowance. The buckets are rows that every worker reads and
writes, as saves' turns are (ADR-0013), so running more workers never multiplies the allowance. The clock is the
server's, so a test moves it by hand.

The limiter never refuses a call because of its own fault: when a bucket can't be read or written, the call is allowed
and the failure logged.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import anyio.to_thread
from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from shared_memory.audit import RATE_LIMITS_CHANGED, TOKEN_LIMITED, Audit
from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.console_sessions import ConsoleSessions
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.identity import Identity, Member

log = logging.getLogger("shared_memory")

# A burst is a minute's allowance divided by this: 30 calls at the default 120 a minute.
BURST_DIVISOR = 4

# The most of a refused MCP call's body that is read, to answer it in its own JSON-RPC shape.
REFUSED_BODY_LIMIT = 64_000


def burst_of(per_minute: int) -> int:
    """How many calls a caller may make at once, from a full bucket."""
    return max(1, per_minute // BURST_DIVISOR)


# A bucket idle for this long has long since refilled, so a row that old is the same as none and is deleted. Each
# worker looks every this often.
IDLE_BUCKETS = timedelta(hours=1)
PRUNE_EVERY = timedelta(minutes=10)


# What an admin may set a limit to, a minute.
MIN_PER_MINUTE = 1
MAX_PER_MINUTE = 100_000

# How long what the limits are is remembered before a worker asks Postgres again, so a change an admin makes on another
# worker is in force here within this long.
LIMITS_CACHED = timedelta(seconds=5)

# A personal token being limited is written to the audit log at most this often.
AUDITED_EVERY = timedelta(hours=1)


@dataclass(frozen=True)
class Limits:
    """The rate limit in force: whether it is on, and how many calls a minute each kind of caller may make."""

    on: bool
    token_per_minute: int
    console_per_minute: int
    address_per_minute: int


def told_to_wait(seconds: int) -> str:
    """What a caller over the limit is told, in the words of a tool error."""
    unit = "second" if seconds == 1 else "seconds"
    return f"Rate limit: too many calls. Slow down and try again in {seconds} {unit}."


class RateLimits:
    """Counts calls against the limits and says how long a caller over one must wait."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        identity: Identity,
        console_sessions: ConsoleSessions,
        audit: Audit,
        clock: Clock,
    ) -> None:
        self._settings = settings
        self._db = db
        self._identity = identity
        self._console_sessions = console_sessions
        self._audit = audit
        self._clock = clock
        self._pruned_at: datetime | None = None
        self._known: tuple[datetime, Limits] | None = None

    def limits(self) -> Limits:
        """The limits in force: what an admin set, or else the environment's numbers. Remembered for a few seconds."""
        now = self._clock()
        if self._known is not None and now - self._known[0] < LIMITS_CACHED:
            return self._known[1]
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT enabled, token_per_minute, console_per_minute, address_per_minute FROM rate_limit_settings"
            ).fetchone()
        if row is None:
            limits = Limits(
                self._settings.rate_limit_on,
                self._settings.rate_limit_token_per_minute,
                self._settings.rate_limit_console_per_minute,
                self._settings.rate_limit_address_per_minute,
            )
        else:
            limits = Limits(
                row["enabled"], row["token_per_minute"], row["console_per_minute"], row["address_per_minute"]
            )
        self._known = (now, limits)
        return limits

    def change(self, admin: Member, limits: Limits) -> Limits:
        """Set the limits server-wide, as an owner or an admin, and record who did it."""
        if not (admin.is_owner or admin.is_admin):
            raise Refused("Only the team's owner and its admins can change the rate limits.")
        for number in (limits.token_per_minute, limits.console_per_minute, limits.address_per_minute):
            if not MIN_PER_MINUTE <= number <= MAX_PER_MINUTE:
                raise Refused(f"A rate limit is from {MIN_PER_MINUTE} to {MAX_PER_MINUTE:,} calls a minute.")
        before = self.limits()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO rate_limit_settings (id, enabled, token_per_minute, console_per_minute, address_per_minute)"
                " VALUES (1, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET enabled = EXCLUDED.enabled,"
                " token_per_minute = EXCLUDED.token_per_minute, console_per_minute = EXCLUDED.console_per_minute,"
                " address_per_minute = EXCLUDED.address_per_minute",
                (limits.on, limits.token_per_minute, limits.console_per_minute, limits.address_per_minute),
            )
        self._known = None
        self._audit.record(
            RATE_LIMITS_CHANGED,
            member=admin,
            detail={"now": dataclasses.asdict(limits), "before": dataclasses.asdict(before)},
        )
        return limits

    def check(self, token: str | None, session: str | None, address: str | None) -> int | None:
        """Count one call, carrying this personal token and console session's cookie, if it carries them, from this
        address. None lets it through; otherwise the whole seconds the caller must wait before a call is allowed
        again."""
        limits = self.limits()
        if not limits.on:
            return None
        if token and (token_id := self._identity.token_id(token)) is not None:
            wait = self._count_call(f"token:{token_id}", limits.token_per_minute)
            if wait is not None:
                self._audit_limited(token_id, limits.token_per_minute)
            return wait
        if session and (member := self._console_sessions.member_pk_of(session)) is not None:
            return self._count_call(f"console:{member}", limits.console_per_minute)
        self._prune_if_due()
        return self._count_call(f"address:{address or 'unknown'}", limits.address_per_minute)

    def _audit_limited(self, token_id: int, per_minute: int) -> None:
        """Write to the audit log that this personal token was limited, unless that was written within the hour, so
        the log shows a leaked token or a runaway agent without a flood of entries. A fault here is logged only."""
        now = self._clock()
        try:
            with self._db.transaction() as conn:
                first = conn.execute(
                    "UPDATE rate_buckets SET limited_audited_at = %s WHERE key = %s"
                    " AND (limited_audited_at IS NULL OR limited_audited_at < %s) RETURNING key",
                    (now, f"token:{token_id}", now - AUDITED_EVERY),
                ).fetchone()
            who = self._identity.token_member(token_id) if first else None
            if who is not None:
                self._audit.record(TOKEN_LIMITED, member=who, target=who.member_id, detail={"per_minute": per_minute})
        except Exception:
            log.exception("A limited personal token could not be written to the audit log")

    def _prune_if_due(self) -> None:
        """Delete the buckets nobody has used for an hour, which address buckets are the ones to leave behind."""
        now = self._clock()
        if self._pruned_at is not None and now - self._pruned_at < PRUNE_EVERY:
            return
        self._pruned_at = now
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM rate_buckets WHERE updated_at < %s", (now - IDLE_BUCKETS,))

    def _count_call(self, key: str, per_minute: int) -> int | None:
        """Count one call against the bucket under this key, which starts full."""
        pace = per_minute / 60
        capacity = float(burst_of(per_minute))
        now = self._clock()
        with self._db.transaction() as conn:
            query = "SELECT tokens, updated_at FROM rate_buckets WHERE key = %s FOR UPDATE"
            row = conn.execute(query, (key,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO rate_buckets (key, tokens, updated_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (key, capacity, now),
                )
                row = conn.execute(query, (key,)).fetchone()
            assert row is not None
            elapsed = max(0.0, (now - row["updated_at"]).total_seconds())
            held = min(capacity, row["tokens"] + elapsed * pace)
            allowed = held >= 1
            conn.execute(
                "UPDATE rate_buckets SET tokens = %s, updated_at = %s WHERE key = %s",
                (held - 1 if allowed else held, max(now, row["updated_at"]), key),
            )
        return None if allowed else max(1, math.ceil((1 - held) / pace))


class RateLimited:
    """Counts every call under the private paths before anything handles it, and refuses those over their limit with
    a 429 and the seconds to wait in `Retry-After`. What the refusal says is in the shape each caller can read."""

    def __init__(
        self,
        app: ASGIApp,
        limits: RateLimits,
        paths: tuple[str, ...],
        bearer: Callable[[str | None], str | None],
        cookie: str,
    ) -> None:
        """bearer reads a personal token from an Authorization header; cookie is the console session's cookie name."""
        self.app = app
        self._limits = limits
        self._paths = paths
        self._bearer = bearer
        self._cookie = cookie

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self._paths):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        token = self._bearer(headers.get("authorization"))
        session = cookie_parser(headers.get("cookie", "")).get(self._cookie)
        peer = scope.get("client")
        address = peer[0] if peer else None
        try:
            wait = await anyio.to_thread.run_sync(self._limits.check, token, session, address)
        except Exception:
            log.exception("The rate limit could not be checked; the call was allowed")
            wait = None
        if wait is None:
            await self.app(scope, receive, send)
            return
        response = await self._refusal(scope, receive, wait)
        await response(scope, receive, send)

    async def _refusal(self, scope: Scope, receive: Receive, wait: int) -> Response:
        message = told_to_wait(wait)
        headers = {"Retry-After": str(wait)}
        path = scope["path"]
        if path.startswith("/mcp"):
            return JSONResponse(await _tool_error(receive, message), status_code=429, headers=headers)
        if path.startswith("/hooks/"):
            # Nothing to add: a coding agent that reads the answer finds none, and one that stops at the status is
            # as it is when the server is unreachable.
            return JSONResponse({}, status_code=429, headers=headers)
        # What the console reads: its usual refusal, `message`, and how long the wait is.
        return JSONResponse({"message": message, "retry_after_seconds": wait}, status_code=429, headers=headers)


async def _tool_error(receive: Receive, message: str) -> dict[str, Any]:
    """A refused MCP call, answered as its own JSON-RPC response: a tool call gets a tool error naming the wait."""
    request: Any = None
    body = bytearray()
    while len(body) <= REFUSED_BODY_LIMIT:
        chunk: Message = await receive()
        if chunk["type"] != "http.request":
            break
        body += chunk.get("body", b"")
        if not chunk.get("more_body", False):
            try:
                request = json.loads(body)
            except ValueError:
                request = None
            break
    identifier = request.get("id") if isinstance(request, dict) else None
    if isinstance(request, dict) and request.get("method") == "tools/call":
        result = {"content": [{"type": "text", "text": message}], "isError": True}
        return {"jsonrpc": "2.0", "id": identifier, "result": result}
    return {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32000, "message": message}}
