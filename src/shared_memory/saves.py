"""Saves run on threads of their own, so a save waiting its turn never holds a thread that reads and hooks need.

Saves into the same area take turns (`MemoryStore.change`, ADR-0012). Tools and console routes run on a small pool of
worker threads, so a save that waited for its turn on one of them would hold a thread that reads and hooks need; under
load most of the pool sat waiting to save. Every caller that saves goes through `Saves.run` instead, which runs it on a
separate pool. Everything a save does before and after its turn (checking the personal token, promote's search for
similar memories, the audit log) still runs alongside other saves; only the store's turns order them.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

import anyio
import anyio.to_thread

T = TypeVar("T")

# Enough threads that saves waiting their turn don't queue the work around them; they are only ever saves.
SAVE_THREADS = 40


class Saves:
    def __init__(self, threads: int = SAVE_THREADS) -> None:
        self._threads = anyio.CapacityLimiter(threads)

    async def run(self, save: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a save on the saves' own threads, leaving the shared pool to reads and hooks."""
        return await anyio.to_thread.run_sync(functools.partial(save, *args, **kwargs), limiter=self._threads)
