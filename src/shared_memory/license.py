"""License keys (spec #416): a small document signed with Ed25519, checked offline.

A key reads `sm<N>.<payload>.<signature>`. The payload is JSON, base64url-encoded, holding the team's name, the member
cap, the dates the key was issued and expires, a key ID and, for a hosted server's key only, `"hosted": true`. `<N>` says which signing key signed it, so the signing key
can rotate: the server keeps one public key per version and accepts any of them. The signature covers `sm<N>.<payload>`.

The server only ever verifies. Nothing here makes a network call. On a self-hosted server a key that fails to verify, or
has lapsed, only changes what the console says and whether more members can be added: memory, MCP tools and hooks never
depend on it. A hosted server's key that has lapsed makes the server read-only (ADR-0022). A key without the hosted
field is a self-hosted server's, so every key signed before the field existed reads as it always did.
Signing lives here so `scripts/sign-license.py` and the tests share one format.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

# From this many days before a key expires, the console says it is expiring.
EXPIRING_DAYS = 30

# The public keys that verify license keys, by the signing key's version. THIS ONE IS A PLACEHOLDER whose private half
# nobody holds: the developer replaces it with the public half of the production pair that
# `scripts/sign-license.py --generate` prints (docs/deployment.md, "License keys"). A new version is added beside the
# old one when the signing key rotates, so keys signed by the old one keep working until they expire.
PUBLIC_KEYS: Mapping[int, bytes] = {1: bytes.fromhex("5e236721ae8ebe8e3662280238e9fcbb394fd11ed5123bc107d2a00b6e97c310")}

PREFIX = "sm"


class InvalidLicense(Exception):
    """A license key that can't be trusted. The message says why in words an admin can act on."""


@dataclass(frozen=True)
class License:
    """What a verified license key says."""

    team: str
    member_cap: int
    issued: date
    expires: date
    key_id: str
    # The key is for a hosted server, which turns read-only once the key lapses (ADR-0022).
    hosted: bool = False

    def days_left(self, today: date) -> int:
        return (self.expires - today).days

    def status(self, today: date) -> str:
        """`lapsed` once the expiry date has passed (`read-only` for a hosted server's key), `expiring` from 30 days
        before it, else `licensed`."""
        left = self.days_left(today)
        if left < 0:
            return "read-only" if self.hosted else "lapsed"
        return "expiring" if left <= EXPIRING_DAYS else "licensed"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(private_key: Ed25519PrivateKey, version: int, license: License) -> str:
    """A license key for this license, signed by the signing key of this version."""
    body: dict[str, object] = {
        "team": license.team,
        "member_cap": license.member_cap,
        "issued": license.issued.isoformat(),
        "expires": license.expires.isoformat(),
        "key_id": license.key_id,
    }
    if license.hosted:
        # Only a hosted key carries the field, so a self-hosted key is signed exactly as before it existed.
        body["hosted"] = True
    payload = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    )
    signed = f"{PREFIX}{version}.{_b64(payload.encode())}"
    return f"{signed}.{_b64(private_key.sign(signed.encode()))}"


def verify(text: str, public_keys: Mapping[int, bytes] = PUBLIC_KEYS) -> License:
    """The license a key holds, if it is well formed and signed by one of these public keys; otherwise InvalidLicense.
    Whether it has lapsed is not decided here: see `License.status`."""
    parts = text.strip().split(".")
    if len(parts) != 3 or not parts[0].startswith(PREFIX) or not parts[0][len(PREFIX) :].isdigit():
        raise InvalidLicense("That isn't a license key: it should look like sm1.… with three parts.")
    version = int(parts[0][len(PREFIX) :])
    public = public_keys.get(version)
    if public is None:
        raise InvalidLicense(f"This license key was signed with key version {version}, which this server doesn't know.")
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(_unb64(parts[2]), f"{parts[0]}.{parts[1]}".encode())
    except (InvalidSignature, binascii.Error, ValueError):
        raise InvalidLicense("This license key's signature doesn't check out, so it can't be trusted.") from None
    try:
        body = json.loads(_unb64(parts[1]))
        return License(
            team=str(body["team"]),
            member_cap=int(body["member_cap"]),
            issued=date.fromisoformat(body["issued"]),
            expires=date.fromisoformat(body["expires"]),
            key_id=str(body["key_id"]),
            hosted=body.get("hosted", False) is True,
        )
    except (KeyError, TypeError, ValueError, binascii.Error):
        raise InvalidLicense("This license key is signed, but its contents can't be read.") from None
