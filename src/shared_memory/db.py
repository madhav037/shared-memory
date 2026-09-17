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

CREATE TABLE IF NOT EXISTS project_leads (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    member_id BIGINT NOT NULL REFERENCES members(id),
    appointed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (project_id, member_id)
);

ALTER TABLE members ADD COLUMN IF NOT EXISTS github_login TEXT;
ALTER TABLE members ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE members ADD COLUMN IF NOT EXISTS github_user_id BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS members_one_github_login_per_team
    ON members (team_id, lower(github_login)) WHERE github_login IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS members_one_github_account_per_team
    ON members (team_id, github_user_id) WHERE github_user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS console_sessions (
    id BIGSERIAL PRIMARY KEY,
    member_id BIGINT NOT NULL REFERENCES members(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS console_sign_ins (
    state_hash TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL,
    team_id BIGINT REFERENCES teams(id),
    actor_id BIGINT REFERENCES members(id),
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    project_id TEXT,
    target TEXT,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS audit_events_by_team ON audit_events (team_id, id DESC);
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
