"""Server errors reach Sentry with private data removed (spec #407).

Reporting is off unless `SHARED_MEMORY_SENTRY_DSN` is set, so a self-hosted server sends nothing by default. When it is
on, every event passes through `scrub` before it leaves the process: request bodies, query strings, headers, cookies,
local variables, exception messages, breadcrumbs that carry data, and every member identifier or GitHub login are
dropped. What stays is what a developer needs to fix the bug: the kind of error, the stack, the route and the release.
"""

from __future__ import annotations

from typing import Any

import sentry_sdk
from sentry_sdk.transport import Transport

from shared_memory.config import Settings

# Contexts that describe the machine, not the member.
_KEPT_ENVIRONMENT = ("runtime", "os")
# Breadcrumb fields that say what kind of step it was; the rest may carry text.
_KEPT_BREADCRUMB_FIELDS = ("type", "category", "level", "timestamp")


def scrub(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """The event with everything that could hold memory text, a token, a cookie or a member removed."""
    request = event.get("request")
    if isinstance(request, dict):
        # The URL's path can name a member or a memory, so only the method stays; the route is `transaction`.
        event["request"] = {"method": request["method"]} if "method" in request else {}
    for private in ("user", "extra", "logentry", "message", "tags", "modules"):
        event.pop(private, None)
    event["contexts"] = {name: value for name, value in event.get("contexts", {}).items() if name in _KEPT_ENVIRONMENT}
    for exception in event.get("exception", {}).get("values", []):
        # An exception's message is built from what was being handled: a title, a path, a member.
        exception["value"] = ""
        for frame in exception.get("stacktrace", {}).get("frames", []):
            frame.pop("vars", None)
    breadcrumbs = event.get("breadcrumbs")
    if breadcrumbs is not None:
        values = breadcrumbs.get("values", []) if isinstance(breadcrumbs, dict) else breadcrumbs
        event["breadcrumbs"] = {
            "values": [
                {key: value for key, value in crumb.items() if key in _KEPT_BREADCRUMB_FIELDS}
                for crumb in values
                if not crumb.get("data")
            ]
        }
    return event


def scrub_breadcrumb(crumb: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """A breadcrumb is dropped at once when it carries data."""
    return None if crumb.get("data") else crumb


def start_reporting(settings: Settings, transport: type[Transport] | Transport | None = None) -> bool:
    """Turn on error reporting when the server has an address to report to. Says whether it did."""
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        before_send=scrub,  # type: ignore[arg-type]
        before_breadcrumb=scrub_breadcrumb,
        traces_sample_rate=0,
        include_local_variables=False,
        max_request_body_size="never",
        transport=transport,
    )
    return True
