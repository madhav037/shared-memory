"""The rate limit: a ceiling on how many calls one caller can make a minute, so one bad caller can't take the server
down for everyone (CONTEXT.md).

Each caller has a bucket in Postgres holding the calls it may still make. A call takes one; the bucket refills at the
limit's pace, up to a burst of a quarter of a minute's allowance. The buckets are rows that every worker reads and
writes, as saves' turns are (ADR-0013), so running more workers never multiplies the allowance. The clock is the
server's, so a test moves it by hand.

The limiter never refuses a call because of its own fault: when a bucket can't be read or written, the call is allowed
and the failure logged.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from typing import Any

import anyio.to_thread
from starlette.datastructures import Headers
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Database
from shared_memory.identity import Identity

log = logging.getLogger("shared_memory")

# A burst is this share of a minute's allowance: 30 calls at the default 120 a minute.
BURST_SHARE = 4

# The most of a refused MCP call's body that is read, to answer it in its own JSON-RPC shape.
REFUSED_BODY_LIMIT = 64_000


def burst_of(per_minute: int) -> int:
    """How many calls a caller may make at once, from a full bucket."""
    return max(1, per_minute // BURST_SHARE)


def told_to_wait(seconds: int) -> str:
    """What a caller over the limit is told, in the words of a tool error."""
    unit = "second" if seconds == 1 else "seconds"
    return f"Rate limit: too many calls from this personal token. Slow down and try again in {seconds} {unit}."


class RateLimits:
    """Counts calls against the limits and says how long a caller over one must wait."""

    def __init__(self, settings: Settings, db: Database, identity: Identity, clock: Clock) -> None:
        self._settings = settings
        self._db = db
        self._identity = identity
        self._clock = clock

    def check(self, token: str | None) -> int | None:
        """Count one call carrying this personal token. None lets it through; otherwise the whole seconds the caller
        must wait before a call is allowed again. Calls with no personal token, or one the server doesn't know, are
        not counted here."""
        if not self._settings.rate_limit_on or not token:
            return None
        token_id = self._identity.token_id(token)
        if token_id is None:
            return None
        return self._take(f"token:{token_id}", self._settings.rate_limit_token_per_minute)

    def _take(self, key: str, per_minute: int) -> int | None:
        """Take one call from the bucket under this key, which starts full."""
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
        self, app: ASGIApp, limits: RateLimits, paths: tuple[str, ...], bearer: Callable[[str | None], str | None]
    ) -> None:
        self.app = app
        self._limits = limits
        self._paths = paths
        self._bearer = bearer

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self._paths):
            await self.app(scope, receive, send)
            return
        token = self._bearer(Headers(scope=scope).get("authorization"))
        try:
            wait = await anyio.to_thread.run_sync(self._limits.check, token)
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
        return JSONResponse({"error": message, "retry_after_seconds": wait}, status_code=429, headers=headers)


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
