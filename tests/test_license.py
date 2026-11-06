"""The repository's license is FSL-1.1-ALv2, and nothing calls Shared Memory 'open source'."""

from __future__ import annotations

import pathlib
import re
import subprocess
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPDX = "FSL-1.1-ALv2"
LOCKFILES = ("uv.lock", "package-lock.json")
TEXT_SUFFIXES = {".md", ".tsx", ".ts", ".html", ".txt", ".toml", ".json", ".py"}


def _tracked_text_files() -> list[pathlib.Path]:
    names = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    files = []
    for name in names:
        path = ROOT / name
        if path.name in LOCKFILES or path == pathlib.Path(__file__).resolve() or not path.is_file():
            continue
        if path.suffix in TEXT_SUFFIXES:
            files.append(path)
    return files


def test_license_names_the_licensor_and_the_license() -> None:
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Functional Source License, Version 1.1, ALv2 Future License" in text
    assert "Copyright 2026 Madhav Lehru" in text
    assert "${" not in text


def test_package_metadata_declares_the_license() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["license"] == SPDX
    package = (ROOT / "console" / "package.json").read_text(encoding="utf-8")
    assert f'"license": "{SPDX}"' in package


def test_readme_says_source_available() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "source-available" in readme
    assert SPDX in readme


def test_nothing_calls_shared_memory_open_source() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in _tracked_text_files()
        if re.search(r"open[\s-]source", path.read_text(encoding="utf-8", errors="ignore"), re.IGNORECASE)
    ]
    assert not offenders, f"'open source' appears in: {offenders}"
