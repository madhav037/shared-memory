"""The developer's signing script makes keys the server accepts, and never overwrites or commits a private key."""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

from shared_memory.license import verify
from tests.license_keys import TEST_PRIVATE, TEST_PUBLIC_KEYS, TEST_SEED, public_of

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sign-license.py"


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True, check=False)


def test_a_signed_key_is_accepted_by_the_servers_check(tmp_path: Path) -> None:
    private = tmp_path / "test-only.key"
    private.write_text(TEST_SEED.hex())

    done = run(
        "--private-key-file", str(private), "--team", "Acme", "--member-cap", "10", "--expires", "2027-11-06",
        "--issued", "2026-11-06", "--key-id", "acme-1",
    )  # fmt: skip

    assert done.returncode == 0, done.stderr
    found = verify(done.stdout.strip(), TEST_PUBLIC_KEYS)
    assert (found.team, found.member_cap, found.expires, found.key_id) == ("Acme", 10, date(2027, 11, 6), "acme-1")


def test_the_script_signs_a_hosted_servers_key(tmp_path: Path) -> None:
    private = tmp_path / "test-only.key"
    private.write_text(TEST_SEED.hex())
    signing = ("--private-key-file", str(private), "--team", "Acme", "--member-cap", "5", "--expires", "2026-12-06")

    hosted = run(*signing, "--hosted")
    self_hosted = run(*signing)

    assert hosted.returncode == 0, hosted.stderr
    assert hosted.stdout.startswith("sm1.")
    assert verify(hosted.stdout.strip(), TEST_PUBLIC_KEYS).hosted is True
    assert verify(self_hosted.stdout.strip(), TEST_PUBLIC_KEYS).hosted is False


def test_generate_writes_a_private_key_once_and_prints_only_the_public_half(tmp_path: Path) -> None:
    private = tmp_path / "fresh.key"

    first = run("--generate", "--private-key-file", str(private))
    again = run("--generate", "--private-key-file", str(private))

    assert first.returncode == 0, first.stderr
    seed = private.read_text().strip()
    assert len(seed) == 64
    assert seed not in first.stdout
    assert again.returncode == 1
    assert private.read_text().strip() == seed
    assert public_of(TEST_PRIVATE).hex() not in first.stdout


def test_signing_without_a_team_or_cap_is_refused(tmp_path: Path) -> None:
    private = tmp_path / "test-only.key"
    private.write_text(TEST_SEED.hex())

    assert run("--private-key-file", str(private)).returncode != 0
