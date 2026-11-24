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
    assert {name.split(":", 1)[1] for name in held} == {"memory.bundle.age", "shared_memory.sql.age"}
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


@pytest.mark.parametrize("work_folder", ["kept", "rebuilt from the remote"])
def test_after_encryption_is_turned_off_the_restore_loads_the_latest_plain_backup(
    tmp_path: Path, work_folder: str
) -> None:
    host = Host(tmp_path)
    host.save_memory()
    work = tmp_path / "backups" / "database"
    if work_folder == "kept":
        assert host.run("now").returncode == 0
    else:
        subprocess.run(["git", "init", "-q", "-b", "database", work.as_posix()], check=True)
    # What an encrypted night leaves at the tip of branch database; the content doesn't matter here.
    for name in ("shared_memory.sql.age", "memory.bundle.age"):
        (work / name).write_text("age-encryption.org/v1 stand-in")
    subprocess.run([*GIT, "-C", work.as_posix(), "add", "."], check=True)
    subprocess.run([*GIT, "-C", work.as_posix(), "commit", "-q", "-m", "encrypted night"], check=True)
    subprocess.run(["git", "-C", work.as_posix(), "push", "-q", host.remote.as_posix(), "HEAD:database"], check=True)
    if work_folder == "rebuilt from the remote":
        shutil.rmtree(work)

    assert host.run("now").returncode == 0
    tip = subprocess.run(
        ["git", "-C", host.remote.as_posix(), "ls-tree", "-r", "--name-only", "database"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert tip == ["shared_memory.sql"]
    fresh = tmp_path / "fresh-memory"
    fresh.mkdir()
    restored = host.run("restore", memory=fresh)

    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert host.received.read_text().strip() == DUMP
    assert (fresh / "a.md").read_text() == MEMORY_TEXT


def stand_in_age(host: Host) -> str:
    """An `age` on the path that writes a changed copy (`age -r R -o OUT IN`): what is encrypted doesn't matter here,
    only which commits and files reach the remote. Returns the recipient to pass."""
    stub(host.bin / "age", 'printf "age-encryption.org/v1 stand-in %s\n" "$(date +%N)" > "$4"; base64 "$5" >> "$4"')
    return "age1standin"


def everything_reachable(remote: Path, *refs: str) -> bytes:
    """The bytes of every file in every commit reachable from the refs (all of them by default): history included."""
    objects = subprocess.run(
        ["git", "-C", remote.as_posix(), "rev-list", "--objects", *(refs or ("--all",))],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    return b"".join(
        subprocess.run(["git", "-C", remote.as_posix(), "cat-file", "-p", line.split()[0]], capture_output=True).stdout
        for line in objects
        if line.strip()
    )


def heads(remote: Path) -> dict[str, str]:
    listed = subprocess.run(
        ["git", "-C", remote.as_posix(), "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    return dict(line.split() for line in listed if line)


def parents(remote: Path, ref: str) -> list[str]:
    return subprocess.run(
        ["git", "-C", remote.as_posix(), "rev-list", "--parents", "-n", "1", ref], capture_output=True, text=True
    ).stdout.split()[1:]


def test_turning_encryption_on_sends_no_earlier_plaintext_to_a_new_repository(tmp_path: Path) -> None:
    host = Host(tmp_path)
    recipient = stand_in_age(host)
    host.save_memory()
    assert host.run("now").returncode == 0
    recreated = tmp_path / "recreated.git"
    subprocess.run(["git", "init", "-q", "--bare", recreated.as_posix()], check=True)

    done = host.run("now", extra={"BACKUP_AGE_RECIPIENT": recipient, "BACKUP_REMOTE": recreated.as_posix()})

    assert done.returncode == 0, done.stdout + done.stderr
    held = everything_reachable(recreated)
    assert DUMP.encode() not in held and MEMORY_TEXT.encode() not in held
    assert not (tmp_path / "backups" / "database").exists(), "the plain history is gone from the server too"


def test_turning_encryption_on_keeps_the_earlier_backups_apart_from_branch_database(tmp_path: Path) -> None:
    host = Host(tmp_path)
    recipient = stand_in_age(host)
    host.save_memory()
    assert host.run("now").returncode == 0
    plain_tip = heads(host.remote)["database"]

    done = host.run("now", extra={"BACKUP_AGE_RECIPIENT": recipient})

    assert done.returncode == 0, done.stdout + done.stderr
    branches = heads(host.remote)
    assert DUMP.encode() not in everything_reachable(host.remote, "database")
    assert parents(host.remote, "database") == []
    kept = [name for name in branches if name.startswith("database-before-")]
    assert len(kept) == 1 and branches[kept[0]] == plain_tip, "the unencrypted backups are kept, not dropped"
    assert "database-before-" in done.stdout


def test_encrypted_backups_keep_the_last_seven_nights_and_no_history(tmp_path: Path) -> None:
    host = Host(tmp_path)
    recipient = stand_in_age(host)
    host.save_memory()

    for _ in range(9):
        done = host.run("now", extra={"BACKUP_AGE_RECIPIENT": recipient})
        assert done.returncode == 0, done.stdout + done.stderr

    branches = heads(host.remote)
    nights = sorted(name for name in branches if name.startswith("backup/"))
    assert len(nights) == 7
    assert all(parents(host.remote, night) == [] for night in nights), "each night is one commit, with no history"
    assert branches["database"] == branches[nights[-1]]
    assert sorted(branches) == sorted([*nights, "database"])
    commits = subprocess.run(
        ["git", "-C", host.remote.as_posix(), "rev-list", "--all", "--count"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert commits == "7"
    assert not (tmp_path / "backups" / "database").exists()
