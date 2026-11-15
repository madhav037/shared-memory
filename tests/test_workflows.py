"""The workflows run third-party code only pinned, and never while the deploy key is on disk (#390).

A moved tag runs new code. The deploy job holds the key that can deploy to the server, so no action, ours or anyone's,
runs between the key being written and its removal; and every action is pinned to a commit, the tag a comment beside it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.support import REPO_ROOT

WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
DEPLOY = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
KEY = "~/.ssh/deploy_key"


def steps(workflow: Path) -> list[tuple[str, dict[str, Any]]]:
    jobs = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
    return [(name, step) for name, job in jobs.items() for step in job.get("steps", [])]


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_every_action_is_pinned_to_a_commit_with_its_tag_beside_it(workflow: Path) -> None:
    lines = [line for line in workflow.read_text(encoding="utf-8").splitlines() if re.match(r"\s*-?\s*uses:", line)]

    assert lines, f"{workflow.name} uses no actions"
    for line in lines:
        assert re.search(r"uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\S+$", line), line


def test_no_action_runs_while_the_deploy_key_is_on_disk() -> None:
    on_disk = False
    seen_written = seen_removed = False
    for _, step in steps(DEPLOY):
        run = step.get("run", "")
        name = step.get("name", step.get("uses", ""))
        if "uses" in step:
            assert not on_disk, f"{name} runs with the deploy key on disk"
        writes = f"> {KEY}" in run
        removes = f"rm -f {KEY}" in run
        seen_written |= writes
        seen_removed |= removes
        if writes and not removes:
            on_disk = True
        if removes and not writes:
            assert step.get("if", "").startswith("always()"), f"{name} must remove the key however the job went"
            on_disk = False

    assert seen_written and seen_removed
    assert not on_disk, "the job ends with the deploy key on disk"


def test_the_deploy_key_is_written_after_every_build() -> None:
    names = [step.get("name", step.get("uses", "")) for _, step in steps(DEPLOY)]
    lasting = [
        i
        for i, (_, step) in enumerate(steps(DEPLOY))
        if f"> {KEY}" in step.get("run", "") and "trap" not in step["run"]
    ]
    builds = [i for i, name in enumerate(names) if "docker/" in name or name.startswith("Build")]

    assert lasting and builds
    assert min(lasting) > max(builds), "the key that stays on disk is written once the images are built"
