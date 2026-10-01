from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


# Below this a worker cannot keep a connection free for reads while saves hold theirs.
MIN_POOL_CONNECTIONS = 4


@dataclass(frozen=True)
class Settings:
    database_url: str
    memory_root: Path
    model_cache: Path
    briefing_cap_tokens: int = 1500
    recall_limit: int = 3
    recall_budget_seconds: float = 2.0
    recall_threshold: float = 0.63
    challenge_fallback_days: int = 3
    memory_word_limit: int = 600
    # A hook payload is a prompt plus a little metadata; a body past this is not read.
    hook_body_limit_bytes: int = 1_000_000
    similar_threshold: float = 0.62
    # The longest one database statement may run, waiting included, before its request fails.
    statement_timeout_seconds: float = 10.0
    allowed_hosts: tuple[str, ...] = ()
    plugin_marketplace: str = "madhav037/shared-memory"
    github_client_id: str = ""
    github_client_secret: str = ""
    github_sign_in_url: str = "https://github.com"
    github_api_url: str = "https://api.github.com"
    console_url: str = ""
    console_session_idle_hours: float = 24
    console_session_days: float = 7
    # How many server processes `serve` runs, and how many connections to Postgres all of them may hold together.
    workers: int = 2
    database_connections: int = 40
    # How long a worker counts the query cache's hits and misses before it writes them to the log.
    query_cache_log_minutes: float = 15

    @property
    def github_sign_in(self) -> bool:
        """Whether this server can sign anyone in to the console."""
        return bool(self.github_client_id and self.github_client_secret)

    @property
    def pool_connections(self) -> int:
        """One worker's connection pool: its share of the connections, and never fewer than it needs to work."""
        return max(MIN_POOL_CONNECTIONS, self.database_connections // max(1, self.workers))

    @property
    def saving_connections(self) -> int:
        """How many of a worker's connections saves may hold at once; reads and hooks keep the other half."""
        return self.pool_connections // 2

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        hosts = tuple(host.strip() for host in env.get("SHARED_MEMORY_ALLOWED_HOSTS", "").split(",") if host.strip())
        return cls(
            database_url=env.get(
                "SHARED_MEMORY_DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/shared_memory"
            ),
            memory_root=Path(env.get("SHARED_MEMORY_ROOT", "data/memory")),
            model_cache=Path(env.get("SHARED_MEMORY_MODEL_CACHE", ".cache/fastembed")),
            allowed_hosts=hosts,
            plugin_marketplace=env.get("SHARED_MEMORY_PLUGIN_MARKETPLACE", "madhav037/shared-memory"),
            github_client_id=env.get("SHARED_MEMORY_GITHUB_CLIENT_ID", ""),
            github_client_secret=env.get("SHARED_MEMORY_GITHUB_CLIENT_SECRET", ""),
            github_sign_in_url=env.get("SHARED_MEMORY_GITHUB_SIGN_IN_URL", "https://github.com"),
            github_api_url=env.get("SHARED_MEMORY_GITHUB_API_URL", "https://api.github.com"),
            console_url=env.get("SHARED_MEMORY_CONSOLE_URL", ""),
            workers=int(env.get("SHARED_MEMORY_WORKERS", "2")),
            database_connections=int(env.get("SHARED_MEMORY_DATABASE_CONNECTIONS", "40")),
            query_cache_log_minutes=float(env.get("SHARED_MEMORY_QUERY_CACHE_LOG_MINUTES", "15")),
        )
