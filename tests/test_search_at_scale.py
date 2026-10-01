"""Vector search stays fast as memory grows: section embeddings carry an approximate-nearest-neighbour index, and a
search or promote check read through it still finds a team's own memories under a crowd of other teams' sections.

At the sizes a test builds, Postgres would rather read every section than the index, so this server's database is set
to prefer the index, the way it does once memory has grown.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from anyio.from_thread import start_blocking_portal
from pgvector.psycopg import register_vector

from shared_memory.app import build_app
from shared_memory.config import Settings
from shared_memory.embeddings import FastEmbedEmbedder
from tests.support import NPM, PNPM, REPO_ROOT, RunningServer, Session, TestClock, fresh_database, member, new_team

CROWD = 1000


@pytest.fixture(scope="module")
def embedder() -> FastEmbedEmbedder:
    return FastEmbedEmbedder(REPO_ROOT / ".cache" / "fastembed")


@pytest.fixture(scope="module")
def grown(tmp_path_factory: pytest.TempPathFactory, embedder: FastEmbedEmbedder) -> Iterator[RunningServer]:
    url = fresh_database("shared_memory_grown")
    name = url.rsplit("/", 1)[1]
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"ALTER DATABASE {name} SET enable_seqscan = off")
        conn.execute(f"ALTER DATABASE {name} SET enable_sort = off")
    settings = Settings(url, tmp_path_factory.mktemp("grown-memory"), REPO_ROOT / ".cache" / "fastembed")
    clock = TestClock()
    with start_blocking_portal() as portal:
        running = RunningServer(build_app(settings, clock=clock, embedder=embedder), settings, clock, portal)
        try:
            yield running
        finally:
            running.stop()


def crowd(server: RunningServer, far: list[float], near: list[float]) -> None:
    """Fill other teams with active team memories whose sections lie between two embeddings, each nearer the second
    than the first is."""
    with psycopg.connect(server.settings.database_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO sections (team, path, section_no, chunk_no, level, project_id, member_id, type, author,"
            " status, content_hash, embedding, tokens)"
            " SELECT 'crowd-' || md5(random()::text), 'team/conventions/crowd-' || g || '.md', 0, 0, 'team', NULL,"
            " NULL, 'convention', 'someone', 'active', md5(g::text),"
            " (SELECT array_agg((1 - t) * f + t * n + (random() - 0.5) * 0.1 ORDER BY i)"
            " FROM unnest(%(far)s::float8[], %(near)s::float8[]) WITH ORDINALITY AS u(f, n, i))::vector, ''::tsvector"
            " FROM generate_series(1, %(crowd)s) g CROSS JOIN LATERAL (SELECT 0.4 + random() * 0.6 AS t"
            " WHERE g IS NOT NULL) way",
            {"far": far, "near": near, "crowd": CROWD},
        )
        conn.execute("ANALYZE sections")


def section_embedding(server: RunningServer, path: str) -> list[float]:
    with psycopg.connect(server.settings.database_url) as conn:
        register_vector(conn)
        row = conn.execute(
            "SELECT embedding FROM sections WHERE path = %s ORDER BY section_no, chunk_no", (path,)
        ).fetchone()
    assert row is not None
    embedding: list[float] = row[0].to_list()
    return embedding


def test_the_section_embeddings_carry_an_approximate_nearest_neighbour_index(grown: RunningServer) -> None:
    with psycopg.connect(grown.settings.database_url) as conn:
        definitions = [row[0] for row in conn.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'sections'")]

    assert any("USING hnsw (embedding vector_cosine_ops)" in definition for definition in definitions), definitions


def test_search_finds_a_teams_memory_under_a_crowd_of_nearer_sections(
    grown: RunningServer, embedder: FastEmbedEmbedder
) -> None:
    team = new_team(grown)
    project = team.owner().call("create_project", name="Billing")["project_id"]
    owner = team.owner().in_project(project, "billing-api")
    path = owner.call(
        "remember",
        title="Charge retries",
        summary="Charge retries",
        type="convention",
        body="When a card charge fails we try it again two more times, then give up.",
    )["path"]
    query = "what happens after a payment is declined"
    crowd(grown, section_embedding(grown, path), embedder.query(query))

    results = owner.call("search", query=query)["results"]

    assert [result["path"] for result in results] == [path]


def test_promote_finds_a_similar_memory_under_a_crowd_of_nearer_sections(grown: RunningServer) -> None:
    team = new_team(grown)
    project = team.owner().call("create_project", name="Billing")["project_id"]
    owner: Session = team.owner().in_project(project, "billing-api")
    dana = member(team, project, "emp-2", "Dana Dev")
    existing = dana.call("promote", path=dana.call("remember", **NPM)["path"], level="project")["path"]
    personal = owner.call("remember", **PNPM)["path"]
    crowd(grown, section_embedding(grown, existing), section_embedding(grown, personal))

    result = owner.call("promote", path=personal, level="project")

    assert result["status"] == "similar_memories"
    assert [similar["path"] for similar in result["similar"]] == [existing]
