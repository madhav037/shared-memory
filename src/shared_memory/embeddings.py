from __future__ import annotations

import hashlib
import logging
import os
import threading
from array import array
from collections import OrderedDict
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from shared_memory.clock import Clock

log = logging.getLogger("shared_memory")

MODEL = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
# The model reads at most this many tokens of a text, its two markers included, and ignores the rest.
MAX_TOKENS = 512


class Embedder(Protocol):
    def passages(self, texts: list[str]) -> list[list[float]]: ...

    def query(self, text: str) -> list[float]: ...

    def tokens(self, words: list[str]) -> list[int]:
        """How many of the model's tokens each word takes."""
        ...


class FastEmbedEmbedder:
    """A small local embedding model running inside the server, so memory text never leaves it.

    The model loads when this is built, so a server is ready before its first request instead of making that request
    wait for the download. Each embed runs on one thread: at the model's default an embed spins every core, so a few
    concurrent searches starve the rest of the server.
    """

    def __init__(self, cache_dir: Path, model: str = MODEL) -> None:
        from fastembed import TextEmbedding

        self._model: Any = TextEmbedding(model_name=model, cache_dir=str(cache_dir), threads=1)

    def passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [vector.tolist() for vector in self._model.passage_embed(texts)]

    def query(self, text: str) -> list[float]:
        vector = next(iter(self._model.query_embed([text])))
        result: list[float] = vector.tolist()
        return result

    def tokens(self, words: list[str]) -> list[int]:
        if not words:
            return []
        encodings = self._model.model.tokenizer.encode_batch(words, add_special_tokens=False)
        return [len(encoding.ids) for encoding in encodings]


class LazyEmbedder:
    """The local model, loaded the first time something needs an embedding instead of when this is built. Setup uses
    it so the process that prepares the database holds the model only if a catch-up really embeds something."""

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._loaded: FastEmbedEmbedder | None = None
        self._guard = threading.Lock()

    def _model(self) -> FastEmbedEmbedder:
        with self._guard:
            if self._loaded is None:
                self._loaded = FastEmbedEmbedder(self._cache_dir)
            return self._loaded

    def passages(self, texts: list[str]) -> list[list[float]]:
        return self._model().passages(texts) if texts else []

    def query(self, text: str) -> list[float]:
        return self._model().query(text)

    def tokens(self, words: list[str]) -> list[int]:
        return self._model().tokens(words) if words else []


class QuerySource(StrEnum):
    """Where a query that is embedded came from."""

    RECALL = "recall"
    SEARCH = "search"
    CONSOLE_SEARCH = "console-search"


class QueryCacheCounts:
    """How often the query cache saved a model run (a hit) or didn't (a miss), by where the query came from.

    One worker's counts, kept in memory and gone when it restarts, like the cache. Nothing runs on a timer: the first
    query after `period` has passed writes one log line with the period's counts and the totals since the worker
    started, so a worker nobody queries writes nothing. `docs/deployment.md` says how to read the line.
    """

    def __init__(self, clock: Clock, period: timedelta, worker: int | None = None) -> None:
        self._clock = clock
        self._period = period
        self._worker = os.getpid() if worker is None else worker
        self._began = clock()
        self._in_period = self._nothing()
        self._since_start = self._nothing()
        self._guard = threading.Lock()

    @staticmethod
    def _nothing() -> dict[QuerySource, list[int]]:
        return {source: [0, 0] for source in QuerySource}

    @staticmethod
    def _written(counts: dict[QuerySource, list[int]]) -> str:
        return ", ".join(f"{source} hits={hits} misses={misses}" for source, (hits, misses) in counts.items())

    def count(self, source: QuerySource, hit: bool) -> None:
        with self._guard:
            for counts in (self._in_period, self._since_start):
                counts[source][0 if hit else 1] += 1
            now = self._clock()
            if now - self._began < self._period:
                return
            line = (
                f"Query cache worker={self._worker} minutes={round((now - self._began).total_seconds() / 60)}"
                f" | period: {self._written(self._in_period)} | since start: {self._written(self._since_start)}"
            )
            self._began = now
            self._in_period = self._nothing()
        log.info(line)


class CachedQueries:
    """An embedder that remembers the embeddings of its most recent queries, so a repeated search or recall doesn't
    embed its query again. Passages are embedded afresh: a save always carries new text.

    Bounded: it keeps `size` queries and forgets the least recently used. Each is kept under a digest of its text (a
    recalled prompt can be long), as the single-precision floats the model produces.

    A query that names where it came from is counted, as a hit or a miss, when the cache was given `counts`.
    """

    def __init__(self, embedder: Embedder, size: int = 1024, counts: QueryCacheCounts | None = None) -> None:
        self._embedder = embedder
        self._size = size
        self._counts = counts
        self._queries: OrderedDict[bytes, array[float]] = OrderedDict()
        self._guard = threading.Lock()

    def passages(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.passages(texts)

    def tokens(self, words: list[str]) -> list[int]:
        return self._embedder.tokens(words)

    def query(self, text: str, source: QuerySource | None = None) -> list[float]:
        key = hashlib.sha256(text.encode()).digest()
        with self._guard:
            known = self._queries.get(key)
            if known is not None:
                self._queries.move_to_end(key)
        if self._counts is not None and source is not None:
            self._counts.count(source, hit=known is not None)
        if known is not None:
            return known.tolist()
        vector = self._embedder.query(text)
        with self._guard:
            self._queries[key] = array("f", vector)
            self._queries.move_to_end(key)
            while len(self._queries) > self._size:
                self._queries.popitem(last=False)
        return list(vector)
