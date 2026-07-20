from __future__ import annotations

import pytest

qdrant_client = pytest.importorskip("qdrant_client")

from app.config import Settings
from app.store import Store
from app.vector_service import VectorService
from app.vector_store import QdrantVectorStore, VectorConfigurationError


class TinyProvider:
    model_id = "test/tiny"
    dimensions = 3

    def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


def local_vectors(client, model_id="test/tiny"):
    vectors = QdrantVectorStore.__new__(QdrantVectorStore)
    vectors.collection = "chunks"
    vectors.dimensions = 3
    vectors.model_id = model_id
    vectors.client = client
    return vectors


def test_real_qdrant_client_indexes_searches_deletes_and_rejects_model_mix(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("VECTOR_SEARCH_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_MODEL", "test/tiny")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "3")
    settings = Settings.from_env(tmp_path)
    store = Store(tmp_path)
    store.initialize()
    qdrant = qdrant_client.QdrantClient(":memory:")
    vectors = local_vectors(qdrant)
    service = VectorService(settings, store, TinyProvider(), vectors)

    path = store.upload_dir / "semantic.txt"
    path.write_text("Jordan owns the rollout plan.")
    from app.extraction import Chunk

    store.add_document(
        document_id="document-1",
        filename="semantic.txt",
        content_type="text/plain",
        stored_path=path,
        digest="digest",
        size_bytes=30,
        chunks=[Chunk(0, None, "Jordan owns the rollout plan.", ("Jordan",))],
        people={"Jordan": 1},
    )
    assert service.index_document("document-1") == (1, 0)
    result = service.search("Who handles deployment?", ["document-1"], 5)
    assert len(result) == 1

    service.delete_document("document-1")
    assert service.search("Who handles deployment?", ["document-1"], 5) == []

    incompatible = local_vectors(qdrant, model_id="test/other")
    with pytest.raises(VectorConfigurationError, match="contains embeddings from"):
        incompatible.ensure_collection()
