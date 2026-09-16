from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Protocol

MODEL = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384


class Embedder(Protocol):
    def passages(self, texts: list[str]) -> list[list[float]]: ...

    def query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """A small local embedding model running inside the server, so memory text never leaves it."""

    def __init__(self, cache_dir: Path, model: str = MODEL) -> None:
        self._cache_dir = cache_dir
        self._model_name = model
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(model_name=self._model_name, cache_dir=str(self._cache_dir))
            return self._model

    def passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [vector.tolist() for vector in self._load().passage_embed(texts)]

    def query(self, text: str) -> list[float]:
        vector = next(iter(self._load().query_embed([text])))
        result: list[float] = vector.tolist()
        return result
