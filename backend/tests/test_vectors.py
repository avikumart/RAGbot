from __future__ import annotations

from dataclasses import dataclass

from app.extraction import Chunk
from app.retrieval import RankedChunk, hybrid_retrieve, reciprocal_rank_fusion
from app.config import Settings
from app.store import Store
from app.vector_service import VectorService
import pytest

from app.vector_store import (
    QdrantVectorStore,
    VectorCandidate,
    VectorConfigurationError,
    content_hash,
    vector_id,
    vector_payload,
)


def add_document(store: Store, document_id: str, contents: list[str]) -> list[dict]:
    path = store.upload_dir / f"{document_id}.txt"
    path.write_text("\n".join(contents))
    store.add_document(
        document_id=document_id,
        filename=path.name,
        content_type="text/plain",
        stored_path=path,
        digest="digest",
        size_bytes=path.stat().st_size,
        chunks=[
            Chunk(ordinal=index, page=None, content=content, people=())
            for index, content in enumerate(contents)
        ],
        people={},
    )
    return store.get_chunks([document_id])


def test_vector_ids_are_deterministic_and_document_safe():
    assert vector_id("document-a", 7) == vector_id("document-a", 7)
    assert vector_id("document-a", 7) != vector_id("document-b", 7)
    assert vector_id("document-a", 7) != vector_id("document-a", 8)


def test_vector_payload_references_sqlite_without_chunk_text():
    chunk = {
        "id": 12,
        "document_id": "document-a",
        "ordinal": 4,
        "page": 2,
        "content": "  Jordan  owns the rollout. ",
        "people": ["Jordan Lee"],
    }
    payload = vector_payload(chunk, "test/model")
    assert payload["chunk_id"] == 12
    assert payload["content_hash"] == content_hash("Jordan owns the rollout.")
    assert payload["embedding_model"] == "test/model"
    assert "content" not in payload


def test_rrf_deduplicates_candidates_and_is_deterministic():
    fused = reciprocal_rank_fusion(
        [RankedChunk(1, 9), RankedChunk(2, 8)],
        [RankedChunk(2, 0.9), RankedChunk(3, 0.8)],
    )
    assert set(fused) == {1, 2, 3}
    assert fused[2] > fused[1]
    assert fused == reciprocal_rank_fusion(
        [RankedChunk(1, 9), RankedChunk(2, 8)],
        [RankedChunk(2, 0.9), RankedChunk(3, 0.8)],
    )


def test_dimension_mismatch_is_rejected_before_upsert():
    vectors = QdrantVectorStore.__new__(QdrantVectorStore)
    vectors.dimensions = 384
    with pytest.raises(VectorConfigurationError, match="collection expects 384"):
        vectors.upsert([{"id": 1}], [[0.0] * 128])


@dataclass
class FakeVectorService:
    candidates: list[VectorCandidate]
    enabled: bool = True
    error: Exception | None = None
    seen_scope: list[str] | None = None

    def search(self, question, document_ids, limit):
        self.seen_scope = document_ids
        if self.error:
            raise self.error
        return self.candidates[:limit]


def test_hybrid_retrieval_scopes_and_validates_vector_candidates(tmp_path):
    store = Store(tmp_path)
    store.initialize()
    first = add_document(store, "first", ["Jordan owns the rollout plan."])[0]
    second = add_document(store, "second", ["A confidential unrelated passage."])[0]
    service = FakeVectorService(
        [
            VectorCandidate(first["id"], "first", 0.8),
            VectorCandidate(second["id"], "second", 0.99),
            VectorCandidate(999999, "first", 1.0),
        ]
    )

    _, sources, mode = hybrid_retrieve(
        store, "Who handles deployment?", ["first"], None, 4, service
    )
    assert service.seen_scope == ["first"]
    assert mode == "hybrid"
    assert [source["document_id"] for source in sources] == ["first"]


def test_vector_failure_falls_back_to_lexical_with_citations(tmp_path):
    store = Store(tmp_path)
    store.initialize()
    add_document(store, "first", ["Jordan Lee owns the rollout plan."])
    service = FakeVectorService([], error=TimeoutError("qdrant unavailable"))

    people, sources, mode = hybrid_retrieve(
        store, "What does Jordan Lee own?", None, None, 4, service
    )
    assert people == []
    assert mode == "lexical-fallback"
    assert sources[0]["filename"] == "first.txt"


def test_explicit_person_boost_is_preserved_after_fusion(tmp_path):
    store = Store(tmp_path)
    store.initialize()
    path = store.upload_dir / "people.txt"
    path.write_text("people")
    store.add_document(
        document_id="people",
        filename="people.txt",
        content_type="text/plain",
        stored_path=path,
        digest="digest",
        size_bytes=6,
        chunks=[
            Chunk(0, None, "Jordan Lee coordinates the release.", ("Jordan Lee",)),
            Chunk(1, None, "The infrastructure lead handles deployment.", ()),
        ],
        people={"Jordan Lee": 1},
    )
    chunks = store.get_chunks(["people"])
    service = FakeVectorService(
        [
            VectorCandidate(chunks[1]["id"], "people", 0.99),
            VectorCandidate(chunks[0]["id"], "people", 0.8),
        ]
    )
    _, sources, _ = hybrid_retrieve(
        store, "Who handles deployment?", ["people"], "Jordan Lee", 2, service
    )
    assert sources[0]["excerpt"].startswith("Jordan Lee")


class FakeProvider:
    model_id = "test/model"
    dimensions = 3

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeVectorStore:
    def __init__(self):
        self.payloads = {}
        self.deleted = []

    def ensure_collection(self):
        pass

    def existing_payloads(self, chunks):
        return {
            chunk["id"]: self.payloads[vector_id(chunk["document_id"], chunk["id"])]
            for chunk in chunks
            if vector_id(chunk["document_id"], chunk["id"]) in self.payloads
        }

    def upsert(self, chunks, vectors):
        for chunk in chunks:
            self.payloads[vector_id(chunk["document_id"], chunk["id"])] = vector_payload(
                chunk, "test/model"
            )

    def iter_chunk_points(self):
        return iter(self.payloads.items())

    def delete_points(self, point_ids):
        self.deleted.extend(point_ids)
        for point_id in point_ids:
            self.payloads.pop(point_id, None)


def test_backfill_is_idempotent_and_removes_orphans(tmp_path, monkeypatch):
    monkeypatch.setenv("VECTOR_SEARCH_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_MODEL", "test/model")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "3")
    settings = Settings.from_env(tmp_path)
    store = Store(tmp_path)
    store.initialize()
    chunks = add_document(store, "first", ["One chunk", "Another chunk"])
    provider = FakeProvider()
    vectors = FakeVectorStore()
    service = VectorService(settings, store, provider, vectors)

    processed, skipped = service.index_chunks(chunks)
    assert (processed, skipped) == (2, 0)
    processed, skipped = service.index_chunks(chunks)
    assert (processed, skipped) == (0, 2)
    assert provider.calls == 1

    vectors.payloads["orphan"] = {"chunk_id": 999, "record_type": "chunk"}
    stats = service.reconcile()
    assert stats.skipped == 2
    assert stats.deleted == 1
    assert vectors.deleted == ["orphan"]


def test_empty_chunks_are_never_sent_to_embedding_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("VECTOR_SEARCH_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_MODEL", "test/model")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "3")
    settings = Settings.from_env(tmp_path)
    store = Store(tmp_path)
    store.initialize()
    provider = FakeProvider()
    service = VectorService(settings, store, provider, FakeVectorStore())
    assert service.index_chunks(
        [
            {
                "id": 1,
                "document_id": "document",
                "ordinal": 0,
                "page": None,
                "content": " \n ",
                "people": [],
            }
        ]
    ) == (0, 1)
    assert provider.calls == 0
