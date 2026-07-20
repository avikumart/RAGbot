from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Protocol


class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def normalize_embedding_text(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


class LocalFastEmbedProvider:
    """Lazy CPU embedding provider; importing the API never downloads a model."""

    def __init__(self, model_id: str, dimensions: int):
        self.model_id = model_id
        self.dimensions = dimensions
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_id)
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        normalized = [normalize_embedding_text(text) for text in texts]
        if any(not text for text in normalized):
            raise ValueError("Empty text cannot be embedded")
        vectors = [vector.tolist() for vector in self._load().embed(normalized)]
        if any(len(vector) != self.dimensions for vector in vectors):
            actual = len(vectors[0]) if vectors else 0
            raise ValueError(
                f"Embedding model {self.model_id!r} returned {actual} dimensions; "
                f"configured dimension is {self.dimensions}"
            )
        return vectors


def create_embedding_provider(provider: str, model_id: str, dimensions: int) -> EmbeddingProvider:
    if provider != "local":
        raise ValueError(f"Unsupported embedding provider: {provider!r}")
    return LocalFastEmbedProvider(model_id, dimensions)
