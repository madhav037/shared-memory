"""The deployment preflight checks the settings the stack cannot start without.

`deploy/compose.yaml` marks a setting with no default as `${NAME:?...}`, which makes Compose refuse to start —
but only after the build, which takes several minutes on a fresh host. `deploy/preflight.sh` asks for the same
settings in two seconds instead. The two lists are written in different languages in different files, so this
is what keeps them the same list.
"""

from __future__ import annotations

import re

from tests.support import REPO_ROOT

COMPOSE = (REPO_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
PREFLIGHT = (REPO_ROOT / "deploy" / "preflight.sh").read_text(encoding="utf-8")


def settings_with_no_default() -> set[str]:
    """The settings Compose refuses to start without."""
    found = set(re.findall(r"\$\{([A-Z_]+):\?", COMPOSE))
    assert found, "deploy/compose.yaml no longer marks any setting as required"
    return found


def settings_the_preflight_asks_for() -> set[str]:
    """The names the preflight loops over before anything is built."""
    checked = re.search(r"for name in ([A-Z_ ]+); do", PREFLIGHT)
    assert checked, "preflight.sh no longer checks a list of settings"
    return set(checked.group(1).split())


def test_the_preflight_asks_for_every_setting_the_stack_has_no_default_for() -> None:
    assert settings_the_preflight_asks_for() == settings_with_no_default()


def test_the_preflight_guards_the_backup_key_against_the_directory_compose_leaves() -> None:
    """The quiet one: a missing key is a directory by the time anything reports it.

    Compose creates a directory when a bind-mounted file is absent, so the backup container finds one where a
    key should be and every nightly push fails. backup.sh does refuse it, but not until 02:00.
    """
    assert re.search(r'if \[ -d "\$KEY" \]', PREFLIGHT), "the preflight no longer catches the directory case"
    assert "ssh-keygen" in PREFLIGHT, "the preflight no longer says how to make the key"


def test_the_deployment_steps_run_the_preflight_before_building() -> None:
    steps = (REPO_ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
    assert "preflight.sh" in steps, "docs/deployment.md doesn't mention the preflight"
    assert steps.index("preflight.sh") < steps.index("docker compose up -d --build"), (
        "the preflight is documented after the build it is meant to come before"
    )
