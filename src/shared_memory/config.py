from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


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
    similar_threshold: float = 0.62
    allowed_hosts: tuple[str, ...] = ()

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
        )
