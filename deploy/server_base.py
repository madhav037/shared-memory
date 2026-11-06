"""The server image's base: the part of it that changes rarely (see the Dockerfile).

    python3 deploy/server_base.py dependencies PYPROJECT   the dependency part of a pyproject.toml, as a pyproject.toml
    python3 deploy/server_base.py tag                      a hash of exactly what goes into the base, to tag it with

The base installs the locked dependencies from uv.lock and the `dependencies` part of pyproject.toml, never the whole
file, so a change to the linters' settings or the tests' leaves the base, and the layers every server already has,
alone. The tag hashes the Dockerfile up to the release stage (the system packages, the pinned images and the search
model's name), uv.lock and that dependency part. Standard library only: it runs in the image and on GitHub's runner.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The line the release stage starts on. Everything above it in the Dockerfile builds the base.
RELEASE_STAGE = "FROM base AS release"


def dependencies(pyproject: str) -> str:
    """What uv needs from pyproject.toml to install the locked dependencies, and nothing else."""
    data = tomllib.loads(pyproject)
    project = data["project"]
    lines = [
        "[project]",
        f"name = {json.dumps(project['name'])}",
        f"version = {json.dumps(project['version'])}",
        f"requires-python = {json.dumps(project['requires-python'])}",
        "dependencies = [",
        *(f"    {json.dumps(requirement)}," for requirement in project.get("dependencies", [])),
        "]",
        "",
        "[build-system]",
        f"requires = {json.dumps(data['build-system']['requires'])}",
        f"build-backend = {json.dumps(data['build-system']['build-backend'])}",
    ]
    return "\n".join(lines) + "\n"


def base_stage(dockerfile: str) -> str:
    lines = dockerfile.splitlines(keepends=True)
    for number, line in enumerate(lines):
        if line.strip() == RELEASE_STAGE:
            return "".join(lines[:number])
    raise SystemExit(f"The Dockerfile has no line {RELEASE_STAGE!r}, so where the base ends is unknown.")


def tag(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for name, text in (
        ("Dockerfile", base_stage((root / "Dockerfile").read_text(encoding="utf-8"))),
        ("uv.lock", (root / "uv.lock").read_text(encoding="utf-8")),
        ("pyproject.toml", dependencies((root / "pyproject.toml").read_text(encoding="utf-8"))),
    ):
        digest.update(f"{name}\0{len(text.encode())}\0".encode())
        digest.update(text.encode())
    return digest.hexdigest()[:20]


def main(argv: list[str]) -> None:
    match argv:
        case ["dependencies", path]:
            sys.stdout.write(dependencies(Path(path).read_text(encoding="utf-8")))
        case ["tag"]:
            print(tag())
        case _:
            raise SystemExit("usage: server_base.py dependencies PYPROJECT | tag")


if __name__ == "__main__":
    main(sys.argv[1:])
