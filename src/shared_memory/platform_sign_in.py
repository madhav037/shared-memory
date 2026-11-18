"""A sign-in handed over by the platform (#471): how a member signs in to a hosted server's console.

A hosted server has no GitHub OAuth app of its own, one per subdomain being impossible. The platform signs the member in
with its single GitHub app instead, and hands the result to the hosted server, signed with Ed25519. The server checks it
offline against the platform's public key, which it is given in its settings, and never calls the platform.

A handed-over sign-in reads `<payload>.<signature>`, both base64url without padding. The payload is JSON:

    {"expires": 1763112300, "github_id": 583231, "github_login": "olive", "id": "kq3…", "nonce": "Zp8…",
     "subdomain": "acme"}

`github_id` and `github_login` name the GitHub account, `subdomain` the hosted server it is for, `expires` the moment it
stops being accepted (Unix seconds), and `id` a one-time ID the server remembers until then, so it is accepted once.
`nonce` is the one the server sent the member to the platform with; the server accepts the sign-in only in the browser
holding that nonce in its cookie, so an unused sign-in passed to someone else signs nobody in. The signature covers the
payload's base64url text exactly as sent. The order of the keys does not matter.

The server only ever verifies. Signing lives here so the tests' fake platform signs exactly what the platform does.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

# The longest one-time ID the server will remember, and the longest nonce it compares.
MAX_ID_LENGTH = 200
MAX_NONCE_LENGTH = 200
# The furthest ahead a sign-in may expire: the platform signs one to last a few minutes.
MAX_LIFETIME = timedelta(minutes=10)


class InvalidSignIn(Exception):
    """A handed-over sign-in that can't be trusted. The message says so in words a member can act on."""


@dataclass(frozen=True)
class HandedOverSignIn:
    """What a verified handed-over sign-in says."""

    github_id: int
    github_login: str
    subdomain: str
    expires: datetime
    id: str
    nonce: str


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(private_key: Ed25519PrivateKey, sign_in: HandedOverSignIn) -> str:
    """A handed-over sign-in, signed by the platform's key."""
    payload = json.dumps(
        {
            "expires": int(sign_in.expires.timestamp()),
            "github_id": sign_in.github_id,
            "github_login": sign_in.github_login,
            "id": sign_in.id,
            "nonce": sign_in.nonce,
            "subdomain": sign_in.subdomain,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    encoded = _b64(payload.encode())
    return f"{encoded}.{_b64(private_key.sign(encoded.encode('ascii')))}"


def verify(text: str, public_key_hex: str) -> HandedOverSignIn:
    """What a handed-over sign-in says, if the platform's key signed it; otherwise InvalidSignIn. Whether it is for this
    server and the browser it lands in, has expired or was already used is not decided here."""
    distrusted = InvalidSignIn("That sign-in couldn't be checked, so it can't be trusted. Try again.")
    parts = text.strip().split(".")
    if len(parts) != 2:
        raise distrusted
    try:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex.strip()))
        public.verify(_unb64(parts[1]), parts[0].encode("ascii"))
        body = json.loads(_unb64(parts[0]))
        found = HandedOverSignIn(
            github_id=body["github_id"],
            github_login=body["github_login"],
            subdomain=body["subdomain"],
            expires=datetime.fromtimestamp(body["expires"], UTC),
            id=body["id"],
            nonce=body["nonce"],
        )
    except (InvalidSignature, binascii.Error, ValueError, UnicodeError, KeyError, TypeError, OverflowError, OSError):
        raise distrusted from None
    if (
        not isinstance(found.github_id, int)
        or isinstance(found.github_id, bool)
        or not isinstance(found.github_login, str)
        or not isinstance(found.subdomain, str)
        or not isinstance(found.id, str)
        or not 0 < len(found.id) <= MAX_ID_LENGTH
        or not isinstance(found.nonce, str)
        or not 0 < len(found.nonce) <= MAX_NONCE_LENGTH
    ):
        raise distrusted
    return found
