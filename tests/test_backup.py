"""The nightly backup (deploy/backup/backup.sh), run for real against a local git remote.

The script's folders are fixed paths in the container; the test points them at a temporary directory, and puts a
stub `pg_dump` ahead of the real one on the path.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support import REPO_ROOT

BACKUP_SH = REPO_ROOT / "deploy" / "backup" / "backup.sh"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="backup.sh runs in a Linux container")


def run_backup_now(tmp_path: Path, memory_has_commit: bool) -> subprocess.CompletedProcess[str]:
    remote = tmp_path / "remote.git"
    memory = tmp_path / "memory"
    bin_dir = tmp_path / "bin"
    for folder in (memory, bin_dir, tmp_path / "backups", tmp_path / "home"):
        folder.mkdir()
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "GIT_CONFIG_GLOBAL": str(tmp_path / "home" / ".gitconfig"),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "BACKUP_REMOTE": remote.as_posix(),
        "MEMORY": memory.as_posix(),
        "BACKUPS": (tmp_path / "backups").as_posix(),
        "BACKUP_KEY": (tmp_path / "no-key").as_posix(),
    }
    pg_dump = bin_dir / "pg_dump"
    pg_dump.write_text('#!/bin/sh\nwhile [ "$1" != "-f" ]; do shift; done\necho "-- dump" > "$2"\n')
    pg_dump.chmod(0o755)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "--bare", remote.as_posix()], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", memory.as_posix()], check=True)
    if memory_has_commit:
        (memory / "a.md").write_text("a")
        subprocess.run([*git, "-C", memory.as_posix(), "add", "."], check=True)
        subprocess.run([*git, "-C", memory.as_posix(), "commit", "-q", "-m", "a"], check=True)
    return subprocess.run(["bash", BACKUP_SH.as_posix(), "now"], env=env, capture_output=True, text=True, check=False)


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
