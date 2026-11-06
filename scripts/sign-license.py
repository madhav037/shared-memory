"""Sign a license key for a team (spec #416). The developer runs this locally when someone pays.

    uv run python scripts/sign-license.py --generate --private-key-file ~/secrets/shared-memory-license.key
    uv run python scripts/sign-license.py --private-key-file ~/secrets/shared-memory-license.key \\
        --team "Acme" --member-cap 10 --expires 2027-11-06

The private key file holds the key's 32-byte seed as 64 hex characters. KEEP IT OFFLINE and OUTSIDE this repository:
never commit it. `--generate` prints the matching public key to put in `PUBLIC_KEYS` in src/shared_memory/license.py
(docs/deployment.md, "License keys"). The signed key is printed to standard output; nothing is sent anywhere.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from shared_memory.license import License, sign, verify


def public_hex(private: Ed25519PrivateKey) -> str:
    raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return raw.hex()


def generate(path: Path) -> int:
    if path.exists():
        print(f"{path} already exists; not overwriting a private key.", file=sys.stderr)
        return 1
    seed = secrets.token_bytes(32)
    path.write_text(seed.hex() + "\n", encoding="ascii")
    path.chmod(0o600)
    private = Ed25519PrivateKey.from_private_bytes(seed)
    print(f"Private key written to {path}. Keep it offline and never commit it.")
    print(f"Public key (put it in PUBLIC_KEYS in src/shared_memory/license.py):\n{public_hex(private)}")
    return 0


def read_private(path: Path) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(path.read_text(encoding="ascii").strip()))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Sign a Shared Memory license key.")
    parser.add_argument("--private-key-file", type=Path, required=True, help="where the private key is (or goes)")
    parser.add_argument("--generate", action="store_true", help="make a new key pair instead of signing")
    parser.add_argument("--key-version", type=int, default=1, help="the signing key's version (default 1)")
    parser.add_argument("--team", help="the team's name")
    parser.add_argument("--member-cap", type=int, help="how many members the team may have")
    parser.add_argument("--expires", type=date.fromisoformat, help="the last day the key is valid, as YYYY-MM-DD")
    parser.add_argument("--issued", type=date.fromisoformat, default=None, help="default: today")
    parser.add_argument("--key-id", help="default: the team, the issue date and the cap")
    args = parser.parse_args(argv)

    if args.generate:
        return generate(args.private_key_file)
    if not (args.team and args.member_cap and args.expires):
        parser.error("signing needs --team, --member-cap and --expires")
    issued = args.issued or date.today()
    key_id = args.key_id or f"{args.team.lower().replace(' ', '-')}-{issued.isoformat()}-{args.member_cap}"
    private = read_private(args.private_key_file)
    key = sign(private, args.key_version, License(args.team, args.member_cap, issued, args.expires, key_id))
    # Check what was made against the public half before handing it over.
    verify(key, {args.key_version: bytes.fromhex(public_hex(private))})
    print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
