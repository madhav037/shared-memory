from __future__ import annotations

import hashlib
import threading
from array import array
from collections import OrderedDict
from pathlib import Path
from typing import Any, Protocol

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


class CachedQueries:
    """An embedder that remembers the embeddings of its most recent queries, so a repeated search or recall doesn't
    embed its query again. Passages are embedded afresh: a save always carries new text.

    Bounded: it keeps `size` queries and forgets the least recently used. Each is kept under a digest of its text (a
    recalled prompt can be long), as the single-precision floats the model produces.
    """

    def __init__(self, embedder: Embedder, size: int = 1024) -> None:
        self._embedder = embedder
        self._size = size
        self._queries: OrderedDict[bytes, array[float]] = OrderedDict()
        self._guard = threading.Lock()

    def passages(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.passages(texts)

    def tokens(self, words: list[str]) -> list[int]:
        return self._embedder.tokens(words)

    def query(self, text: str) -> list[float]:
        key = hashlib.sha256(text.encode()).digest()
        with self._guard:
            known = self._queries.get(key)
            if known is not None:
                self._queries.move_to_end(key)
                return known.tolist()
        vector = self._embedder.query(text)
        with self._guard:
            self._queries[key] = array("f", vector)
            self._queries.move_to_end(key)
            while len(self._queries) > self._size:
                self._queries.popitem(last=False)
        return list(vector)
