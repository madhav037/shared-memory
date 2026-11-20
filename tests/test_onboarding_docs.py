"""The docs page on onboarding a brownfield project (#623, spec #614) covers what a company plans with."""

from __future__ import annotations

from tests.support import REPO_ROOT

PAGE = REPO_ROOT / "docs" / "onboarding.md"


def test_the_docs_page_covers_sources_repositories_headless_runs_interviews_and_progress() -> None:
    page = PAGE.read_text(encoding="utf-8")

    for heading in ("## Choosing sources", "## Many repositories", "## Headless runs in CI", "## Interviews", "## Progress"):
        assert heading in page, heading
    assert "Nothing is sent anywhere but your company's Shared Memory server" in page


def test_the_docs_page_has_a_worked_example_of_a_headless_run_in_ci() -> None:
    page = PAGE.read_text(encoding="utf-8")
    headless = page[page.index("## Headless runs in CI") : page.index("## Interviews")]

    assert "```yaml" in headless
    assert "mode headless" in headless
    assert "shared-memory-proposals-" in headless


def test_setup_points_at_the_onboarding_page() -> None:
    assert "(./onboarding.md)" in (REPO_ROOT / "docs" / "setup.md").read_text(encoding="utf-8")
