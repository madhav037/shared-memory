from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS teams (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS members (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    member_id TEXT NOT NULL,
    name TEXT NOT NULL,
    is_owner BOOLEAN NOT NULL DEFAULT FALSE,
    removed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (team_id, member_id)
);

CREATE TABLE IF NOT EXISTS tokens (
    id BIGSERIAL PRIMARY KEY,
    member_id BIGINT NOT NULL REFERENCES members(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS repositories (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    name TEXT NOT NULL,
    PRIMARY KEY (project_id, name)
);
"""


Conn = psycopg.Connection[dict[str, Any]]


class Database:
    def __init__(self, url: str) -> None:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(SCHEMA)
        self._pool: ConnectionPool[Conn] = ConnectionPool(
            url,
            min_size=1,
            max_size=10,
            open=True,
            kwargs={"row_factory": dict_row},
            configure=register_vector,
        )

    @contextmanager
    def transaction(self) -> Iterator[Conn]:
        with self._pool.connection() as conn:
            yield conn

    def close(self) -> None:
        self._pool.close()
