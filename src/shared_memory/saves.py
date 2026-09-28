"""Saves take turns, and a save waiting its turn waits on the event loop, not on a worker thread.

The memory store serializes every save (`MemoryStore.change`). Tools and console routes run on a small pool of worker
threads, so a save that waited for the store on one of them would hold a thread that reads and hooks need; under load
most of the pool sat waiting to save. Every caller that saves goes through `Saves.run` instead: it queues here, and
only the save whose turn it is runs on a thread. The store's own serialization stays the one that guarantees order.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

import anyio
import anyio.to_thread

T = TypeVar("T")


class Saves:
    def __init__(self) -> None:
        self._turn = anyio.Lock()

    async def run(self, save: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Wait for this save's turn without holding a thread, then run it on one."""
        async with self._turn:
            return await anyio.to_thread.run_sync(functools.partial(save, *args, **kwargs))
