from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Callable, TypeVar

from .config import Settings
from .embeddings import (
    EmbeddingProvider,
    create_embedding_provider,
    normalize_embedding_text,
)
from .store import Store
from .vector_store import QdrantVectorStore, VectorCandidate, content_hash, vector_id


logger = logging.getLogger(__name__)
T = TypeVar("T")


class EmbeddingTimeoutError(TimeoutError):
    pass


def _with_timeout(operation: Callable[[], T], seconds: float) -> T:
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="personagraph-embedding")
    future = executor.submit(operation)
    try:
        return future.result(timeout=seconds)
    except FutureTimeout as exc:
        future.cancel()
        raise EmbeddingTimeoutError(f"Embedding timed out after {seconds:g} seconds") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


@dataclass
class ReconcileStats:
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    deleted: int = 0


class VectorService:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        provider: EmbeddingProvider | None = None,
        vector_store: QdrantVectorStore | None = None,
    ):
        self.settings = settings
        self.store = store
        self._provider = provider
        self._vector_store = vector_store
        self._collection_ready = False
        self._embedding_ready = False
        self._embedding_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self.settings.vector_search_enabled

    @property
    def provider(self) -> EmbeddingProvider:
        if self._provider is None:
            self._provider = create_embedding_provider(
                self.settings.embedding_provider,
                self.settings.embedding_model,
                self.settings.embedding_dimensions,
            )
        return self._provider

    @property
    def vector_store(self) -> QdrantVectorStore:
        if self._vector_store is None:
            self._vector_store = QdrantVectorStore(
                self.settings.qdrant_url,
                self.settings.qdrant_collection,
                self.settings.embedding_dimensions,
                self.settings.embedding_model,
                self.settings.vector_timeout_seconds,
            )
        return self._vector_store

    def ensure_ready(self) -> None:
        if not self._collection_ready:
            self.vector_store.ensure_collection()
            self._collection_ready = True

    def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            result = _with_timeout(
                lambda: self.provider.embed(texts), self.settings.embedding_timeout_seconds
            )
            self._embedding_ready = True
            self._embedding_error = None
            return result
        except Exception as exc:
            self._embedding_ready = False
            self._embedding_error = str(exc)[:500]
            raise

    def index_chunks(self, chunks: list[dict]) -> tuple[int, int]:
        if not self.enabled or not chunks:
            return 0, len(chunks)
        self.ensure_ready()
        eligible = [chunk for chunk in chunks if normalize_embedding_text(chunk["content"])]
        existing = self.vector_store.existing_payloads(eligible)
        stale = [
            chunk
            for chunk in eligible
            if not (
                (payload := existing.get(int(chunk["id"])))
                and payload.get("content_hash") == content_hash(chunk["content"])
                and payload.get("embedding_model") == self.settings.embedding_model
            )
        ]
        for start in range(0, len(stale), self.settings.embedding_batch_size):
            batch = stale[start : start + self.settings.embedding_batch_size]
            vectors = self._embed([chunk["content"] for chunk in batch])
            self.vector_store.upsert(batch, vectors)
        return len(stale), len(chunks) - len(stale)

    def index_document(self, document_id: str) -> tuple[int, int]:
        chunks = self.store.get_chunks([document_id])
        if not self.enabled:
            self.store.set_vector_status(
                document_id, "disabled", self.settings.embedding_model
            )
            return 0, len(chunks)
        try:
            self.store.set_vector_status(
                document_id, "indexing", self.settings.embedding_model
            )
            result = self.index_chunks(chunks)
            self.store.set_vector_status(document_id, "ready", self.settings.embedding_model)
            return result
        except Exception as exc:
            self.store.set_vector_status(
                document_id, "needs_reindex", self.settings.embedding_model, str(exc)[:500]
            )
            raise

    def search(
        self, question: str, document_ids: list[str] | None, limit: int
    ) -> list[VectorCandidate]:
        if not self.enabled:
            return []
        self.ensure_ready()
        vector = self._embed([question])[0]
        return self.vector_store.search(vector, limit, document_ids)

    def delete_document(self, document_id: str) -> None:
        if not self.enabled:
            return
        self.ensure_ready()
        self.vector_store.delete_document(document_id)

    def health(self) -> dict:
        if not self.enabled:
            return {
                "vector_database": {"status": "disabled"},
                "embedding_model": {"status": "disabled"},
            }
        vector_status = "ready"
        vector_error = None
        try:
            self.ensure_ready()
        except Exception as exc:
            vector_status, vector_error = "degraded", str(exc)
        # Model loading is intentionally lazy so a health probe never triggers a
        # download. A real embedding attempt transitions this to ready or degraded.
        embedding_status = (
            "ready"
            if self._embedding_ready
            else "degraded"
            if self._embedding_error
            else "not_loaded"
        )
        return {
            "vector_database": {"status": vector_status, "error": vector_error},
            "embedding_model": {
                "status": embedding_status,
                "model": self.settings.embedding_model,
                "dimensions": self.settings.embedding_dimensions,
                "error": self._embedding_error,
            },
        }

    def reconcile(self) -> ReconcileStats:
        stats = ReconcileStats()
        chunks = self.store.get_chunks()
        try:
            self.ensure_ready()
        except Exception:
            stats.failed = len(chunks)
            logger.exception("Vector backfill could not initialize the collection")
            return stats
        for start in range(0, len(chunks), self.settings.embedding_batch_size):
            batch = chunks[start : start + self.settings.embedding_batch_size]
            try:
                processed, skipped = self.index_chunks(batch)
                stats.processed += processed
                stats.skipped += skipped
            except Exception:
                stats.failed += len(batch)
                logger.exception("Vector backfill batch failed")

        valid_ids = {vector_id(chunk["document_id"], chunk["id"]) for chunk in chunks}
        orphan_ids = [
            point_id
            for point_id, _ in self.vector_store.iter_chunk_points()
            if point_id not in valid_ids
        ]
        for start in range(0, len(orphan_ids), 256):
            batch = orphan_ids[start : start + 256]
            self.vector_store.delete_points(batch)
            stats.deleted += len(batch)
        return stats
