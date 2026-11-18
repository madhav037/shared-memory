"""The browser journeys' seed runs to the end without a browser (#373).

The journeys run only in CI's console job, and implementers don't run Playwright locally. A change that breaks the
seed (tests/console_e2e_server.py), such as a promotion that now raises a challenge the seed asserts against, used to
kill the journeys' server so every journey failed with ECONNREFUSED. Running the seed here fails in seconds instead,
locally and in the server job.
"""

from __future__ import annotations

from pathlib import Path

from anyio.from_thread import start_blocking_portal

from tests.console_e2e_server import seeded


def test_the_journeys_seed_runs_to_the_end(tmp_path: Path) -> None:
    with start_blocking_portal() as portal, seeded(portal, tmp_path / "memory", databases="shared_memory_e2e_seed") as seed:
        assert seed.project
        assert seed.hosted.app.state.licenses.current().status == "read-only"
