"""A long memory is findable to its last word, though the search model reads only 512 tokens at a time."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from anyio.from_thread import BlockingPortal, start_blocking_portal

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.embeddings import FastEmbedEmbedder
from tests.support import REPO_ROOT, RunningServer, Session, TestClock, added_context, fresh_database, new_team

FILLER = (
    "The billing service retries failed invoice webhooks with jittered exponential backoff and records each attempt. "
    "Every invoice keeps its currency beside the amount, and refunds are linked to the charge they reverse. "
    "Reconciliation runs nightly against the payment provider's settlement report and flags any mismatch. "
)
DEPLOY_RULE = "Production deploys only happen on Tuesdays, after the nightly database backup has finished."


def long_body() -> str:
    """About 600 words: billing notes that fill well past the model's 512 tokens, then a deploy rule at the very end."""
    body = " ".join([FILLER] * 13) + "\n\n" + DEPLOY_RULE
    assert 580 <= len(body.split()) <= 600
    return body


LONG = {
    "title": "Billing service notes",
    "summary": "How the billing service handles invoices, and when it ships.",
    "type": "convention",
    "body": long_body(),
}


def remember_long(session: Session) -> str:
    path: str = session.call("remember", **LONG)["path"]
    return path


def test_a_rule_at_the_end_of_a_long_memory_is_recalled(owner: Session) -> None:
    path = remember_long(owner)

    context = added_context(owner.prompt("which day of the week are production deploys allowed?"))

    assert path in context
    assert DEPLOY_RULE in context


def test_a_long_memory_is_recalled_once_with_its_title(owner: Session) -> None:
    path = remember_long(owner)

    context = added_context(owner.prompt("which day of the week are production deploys allowed?"))

    assert context.count(f"({path})") == 1
    assert "] Billing service notes (" in context


def test_search_finds_a_long_memory_by_the_meaning_of_its_last_lines(owner: Session) -> None:
    for title, body in [
        ("Money amounts", "All money amounts are stored as integer cents, never floats."),
        ("Charge retries", "When a card charge fails we try it again two more times, then give up."),
        ("Staging database", "The staging database is wiped and reseeded every night."),
        ("Release notes", "Every release gets a changelog entry written by the member who merged it."),
    ]:
        owner.call("remember", title=title, summary=title, type="convention", body=body)
    path = remember_long(owner)

    results = owner.call("search", query="which weekday may we ship to prod")["results"]

    assert results[0]["path"] == path
    assert [result["path"] for result in results].count(path) == 1
    assert results[0]["heading"] == "Billing service notes"


def test_promote_sees_what_the_end_of_a_long_memory_says(owner: Session) -> None:
    rule = owner.call(
        "remember",
        title="Deploy days",
        summary="When production deploys happen.",
        type="convention",
        body="We deploy to production on Tuesdays only, once the database backup is done.",
    )["path"]
    promoted = owner.call("promote", path=rule, level="project")["path"]

    result = owner.call("promote", path=remember_long(owner), level="project")

    assert result["status"] == "similar_memories", result
    assert promoted in [similar["path"] for similar in result["similar"]]


# The index as it stood before chunks: one row per section, its embedding made from the section's first 512 tokens.
OLD_INDEX = """
DELETE FROM sections WHERE chunk_no > 0;
UPDATE sections SET content_hash = 'the whole section';
ALTER TABLE sections DROP CONSTRAINT sections_pkey;
ALTER TABLE sections DROP COLUMN chunk_no;
ALTER TABLE sections ADD PRIMARY KEY (team, path, section_no);
"""


@pytest.fixture
def upgrading(tmp_path: Path) -> Settings:
    return Settings(
        database_url=fresh_database("shared_memory_upgrade"),
        memory_root=tmp_path / "memory",
        model_cache=REPO_ROOT / ".cache" / "fastembed",
    )


def serving(settings: Settings, portal: BlockingPortal) -> RunningServer:
    app = build_app(settings, clock=TestClock(), embedder=FastEmbedEmbedder(settings.model_cache))
    return RunningServer(app, settings, TestClock(), portal)


def test_an_index_built_before_chunks_is_brought_up_to_date_at_start(upgrading: Settings) -> None:
    prompt = "which day of the week are production deploys allowed?"
    with start_blocking_portal() as portal:
        before = serving(upgrading, portal)
        try:
            team = new_team(before)
            project = team.owner().call("create_project", name="Billing")["project_id"]
            path = remember_long(team.owner().in_project(project))
        finally:
            before.stop()
        with psycopg.connect(upgrading.database_url, autocommit=True) as conn:
            conn.execute(OLD_INDEX)

        after = serving(upgrading, portal)
        try:
            context = added_context(Session(after, team.owner_token, project).prompt(prompt))
        finally:
            after.stop()

    assert path in context
