"""The nightly backup (deploy/backup/backup.sh), run for real against a local git remote.

The script's folders are fixed paths in the container; the test points them at a temporary directory, and puts stub
`pg_dump` and `psql` programs ahead of the real ones on the path. The encrypted form needs the real `age` and
`age-keygen`, which the backup image installs and CI's Linux job installs; where they are missing those tests skip.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support import REPO_ROOT

BACKUP_SH = REPO_ROOT / "deploy" / "backup" / "backup.sh"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="backup.sh runs in a Linux container")

needs_age = pytest.mark.skipif(
    shutil.which("age") is None or shutil.which("age-keygen") is None,
    reason="age and age-keygen are not installed (apt install age; CI's Linux job installs it)",
)

DUMP = "-- secret dump"
MEMORY_TEXT = "secret memory text"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


def stub(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


class Host:
    """A temporary stand-in for the backup container: its folders, its stub programs and a bare git remote."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.remote = tmp_path / "remote.git"
        self.memory = tmp_path / "memory"
        self.bin = tmp_path / "bin"
        self.received = tmp_path / "psql-received.sql"
        for folder in (self.memory, self.bin, tmp_path / "backups", tmp_path / "home"):
            folder.mkdir()
        stub(self.bin / "pg_dump", f'while [ "$1" != "-f" ]; do shift; done\necho "{DUMP}" > "$2"')
        # psql: the restore asks whether the database is empty (to_regclass), then loads the dump (the last argument).
        stub(
            self.bin / "psql",
            'case "$*" in\n'
            f'  *to_regclass*) echo f ;;\n  *" -f "*) for a; do last=$a; done; cp "$last" "{self.received.as_posix()}" ;;\nesac',
        )
        subprocess.run(["git", "init", "-q", "--bare", self.remote.as_posix()], check=True)

    def save_memory(self) -> None:
        subprocess.run(["git", "init", "-q", "-b", "main", self.memory.as_posix()], check=True)
        (self.memory / "a.md").write_text(MEMORY_TEXT)
        subprocess.run([*GIT, "-C", self.memory.as_posix(), "add", "."], check=True)
        subprocess.run([*GIT, "-C", self.memory.as_posix(), "commit", "-q", "-m", "a"], check=True)

    def run(
        self, command: str, memory: Path | None = None, extra: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "HOME": str(self.root / "home"),
            "GIT_CONFIG_GLOBAL": str(self.root / "home" / ".gitconfig"),
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "BACKUP_REMOTE": self.remote.as_posix(),
            "MEMORY": (memory or self.memory).as_posix(),
            "BACKUPS": (self.root / "backups").as_posix(),
            "BACKUP_KEY": (self.root / "no-key").as_posix(),
            "BACKUP_AGE_RECIPIENT": "",
            "BACKUP_AGE_IDENTITY": (self.root / "no-identity").as_posix(),
            **(extra or {}),
        }
        return subprocess.run(
            ["bash", BACKUP_SH.as_posix(), command], env=env, capture_output=True, text=True, check=False
        )

    def branches(self) -> str:
        return subprocess.run(
            ["git", "-C", self.remote.as_posix(), "branch", "--list"], capture_output=True, text=True, check=True
        ).stdout

    def everything_the_remote_holds(self) -> dict[str, bytes]:
        """Every file on every branch of the remote, by branch and name, as the bytes a reader of the remote sees."""
        held: dict[str, bytes] = {}
        remote = self.remote.as_posix()
        for branch in subprocess.run(
            ["git", "-C", remote, "for-each-ref", "--format=%(refname:short)", "refs/heads"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split():
            names = subprocess.run(
                ["git", "-C", remote, "ls-tree", "-r", "--name-only", branch],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split()
            for name in names:
                held[f"{branch}:{name}"] = subprocess.run(
                    ["git", "-C", remote, "show", f"{branch}:{name}"], capture_output=True, check=True
                ).stdout
        return held


def keypair(tmp_path: Path) -> tuple[str, Path]:
    """A fresh age identity file and its public recipient."""
    identity = tmp_path / "identity.txt"
    subprocess.run(["age-keygen", "-o", identity.as_posix()], capture_output=True, check=True)
    recipient = subprocess.run(
        ["age-keygen", "-y", identity.as_posix()], capture_output=True, text=True, check=True
    ).stdout.strip()
    return recipient, identity


def run_backup_now(tmp_path: Path, memory_has_commit: bool) -> subprocess.CompletedProcess[str]:
    host = Host(tmp_path)
    subprocess.run(["git", "init", "-q", "-b", "main", host.memory.as_posix()], check=True)
    if memory_has_commit:
        host.save_memory()
    return host.run("now")


def test_a_backup_before_the_first_memory_is_saved_still_succeeds(tmp_path: Path) -> None:
    done = run_backup_now(tmp_path, memory_has_commit=False)

    assert done.returncode == 0, done.stderr
    assert "nothing to push" in done.stdout
    assert "Backup finished" in done.stdout
    assert (tmp_path / "backups" / "last-success").exists()


def test_a_backup_pushes_the_memory_once_one_is_saved(tmp_path: Path) -> None:
    done = run_backup_now(tmp_path, memory_has_commit=True)

    assert done.returncode == 0, done.stderr
    heads = subprocess.run(
        ["git", "-C", (tmp_path / "remote.git").as_posix(), "branch", "--list"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "main" in heads
    assert "database" in heads


def test_without_a_recipient_the_backup_is_as_it_was_and_the_log_says_it_is_unencrypted(tmp_path: Path) -> None:
    host = Host(tmp_path)
    host.save_memory()

    done = host.run("now")

    assert done.returncode == 0, done.stderr
    assert "unencrypted" in done.stdout
    held = host.everything_the_remote_holds()
    assert held["database:shared_memory.sql"].decode().strip() == DUMP
    assert held["main:a.md"].decode() == MEMORY_TEXT


@needs_age
def test_with_a_recipient_the_remote_holds_only_ciphertext(tmp_path: Path) -> None:
    recipient, _ = keypair(tmp_path)
    host = Host(tmp_path)
    host.save_memory()

    done = host.run("now", extra={"BACKUP_AGE_RECIPIENT": recipient})

    assert done.returncode == 0, done.stderr
    assert "unencrypted" not in done.stdout
    assert "encrypted with age" in done.stdout
    held = host.everything_the_remote_holds()
    assert sorted(held) == ["database:memory.bundle.age", "database:shared_memory.sql.age"]
    for name, content in held.items():
        assert content.startswith(b"age-encryption.org/"), f"{name} is not an age file"
        assert DUMP.encode() not in content and MEMORY_TEXT.encode() not in content
    assert "main" not in host.branches(), "the memory history is pushed only as an encrypted bundle"
    assert (tmp_path / "backups" / "last-success").exists()


@needs_age
def test_decrypting_with_the_matching_identity_restores_the_dump_and_the_history(tmp_path: Path) -> None:
    recipient, identity = keypair(tmp_path)
    host = Host(tmp_path)
    host.save_memory()
    assert host.run("now", extra={"BACKUP_AGE_RECIPIENT": recipient}).returncode == 0
    fresh = tmp_path / "fresh-memory"
    fresh.mkdir()

    done = host.run("restore", memory=fresh, extra={"BACKUP_AGE_IDENTITY": identity.as_posix()})

    assert done.returncode == 0, done.stderr
    assert host.received.read_text().strip() == DUMP
    assert (fresh / "a.md").read_text() == MEMORY_TEXT
    log = subprocess.run(
        ["git", "-C", fresh.as_posix(), "log", "--format=%s"], capture_output=True, text=True, check=True
    )
    assert log.stdout.split() == ["a"]


@needs_age
def test_restoring_an_encrypted_backup_without_the_identity_says_so_and_changes_nothing(tmp_path: Path) -> None:
    recipient, _ = keypair(tmp_path)
    host = Host(tmp_path)
    host.save_memory()
    assert host.run("now", extra={"BACKUP_AGE_RECIPIENT": recipient}).returncode == 0
    fresh = tmp_path / "fresh-memory"
    fresh.mkdir()

    done = host.run("restore", memory=fresh)

    assert done.returncode != 0
    assert "age identity" in done.stdout + done.stderr
    assert not (fresh / ".git").exists()
    assert not host.received.exists()


@needs_age
def test_an_identity_that_does_not_match_restores_nothing(tmp_path: Path) -> None:
    recipient, _ = keypair(tmp_path)
    host = Host(tmp_path)
    host.save_memory()
    assert host.run("now", extra={"BACKUP_AGE_RECIPIENT": recipient}).returncode == 0
    other = tmp_path / "other"
    other.mkdir()
    _, wrong_identity = keypair(other)
    fresh = tmp_path / "fresh-memory"
    fresh.mkdir()

    done = host.run("restore", memory=fresh, extra={"BACKUP_AGE_IDENTITY": wrong_identity.as_posix()})

    assert done.returncode != 0
    assert not host.received.exists()


@needs_age
def test_a_backup_continues_after_unencrypted_ones_without_keeping_the_plain_dump(tmp_path: Path) -> None:
    recipient, _ = keypair(tmp_path)
    host = Host(tmp_path)
    host.save_memory()
    assert host.run("now").returncode == 0

    done = host.run("now", extra={"BACKUP_AGE_RECIPIENT": recipient})

    assert done.returncode == 0, done.stderr
    tip = subprocess.run(
        ["git", "-C", host.remote.as_posix(), "ls-tree", "-r", "--name-only", "database"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert tip == ["memory.bundle.age", "shared_memory.sql.age"]
