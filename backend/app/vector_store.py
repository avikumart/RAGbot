from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID, uuid5

from .embeddings import normalize_embedding_text


VECTOR_NAMESPACE = UUID("3c114b9c-f4dd-4a25-8dac-cc68c96eb43c")
METADATA_NAMESPACE = UUID("9b3b8430-dc43-4781-8486-cd0d80a0c113")


class VectorConfigurationError(RuntimeError):
    pass


def vector_id(document_id: str, chunk_id: int) -> str:
    return str(uuid5(VECTOR_NAMESPACE, f"{document_id}\0{chunk_id}"))


def content_hash(content: str) -> str:
    return hashlib.sha256(normalize_embedding_text(content).encode("utf-8")).hexdigest()


def vector_payload(chunk: dict, embedding_model: str) -> dict:
    return {
        "record_type": "chunk",
        "document_id": chunk["document_id"],
        "chunk_id": int(chunk["id"]),
        "ordinal": int(chunk["ordinal"]),
        "page": chunk["page"],
        "people": list(chunk["people"]),
        "embedding_model": embedding_model,
        "content_hash": content_hash(chunk["content"]),
    }


@dataclass(frozen=True)
class VectorCandidate:
    chunk_id: int
    document_id: str
    score: float


class QdrantVectorStore:
    def __init__(
        self, url: str, collection: str, dimensions: int, model_id: str, timeout: float = 5
    ):
        from qdrant_client import QdrantClient

        self.collection = collection
        self.dimensions = dimensions
        self.model_id = model_id
        self.client = QdrantClient(url=url, timeout=timeout)

    @property
    def metadata_id(self) -> str:
        return str(uuid5(METADATA_NAMESPACE, self.collection))

    def _write_metadata(self) -> None:
        from qdrant_client.models import PointStruct

        self.client.upsert(
            self.collection,
            [
                PointStruct(
                    id=self.metadata_id,
                    vector=[0.0] * self.dimensions,
                    payload={
                        "record_type": "collection_metadata",
                        "embedding_model": self.model_id,
                        "dimensions": self.dimensions,
                    },
                )
            ],
            wait=True,
        )

    def ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=self.dimensions, distance=Distance.COSINE),
            )
            self._write_metadata()
            return

        info = self.client.get_collection(self.collection)
        vector_config = info.config.params.vectors
        actual_dimensions = getattr(vector_config, "size", None)
        actual_distance = str(getattr(vector_config, "distance", "")).casefold()
        if actual_dimensions != self.dimensions or "cosine" not in actual_distance:
            raise VectorConfigurationError(
                f"Qdrant collection {self.collection!r} uses dimension "
                f"{actual_dimensions} and distance {actual_distance or 'unknown'}; expected "
                f"dimension {self.dimensions} with cosine. Use a new collection or run an "
                "explicit full reindex."
            )

        metadata = self.client.retrieve(self.collection, [self.metadata_id], with_vectors=False)
        if not metadata:
            if getattr(info, "points_count", None) == 0:
                # Repairs an interrupted first-time initialization without risking
                # adoption of a collection that already contains unknown vectors.
                self._write_metadata()
                return
            raise VectorConfigurationError(
                f"Qdrant collection {self.collection!r} has no Personagraph model metadata. "
                "Use a new collection or run an explicit full reindex."
            )
        payload = metadata[0].payload or {}
        if payload.get("embedding_model") != self.model_id:
            raise VectorConfigurationError(
                f"Qdrant collection {self.collection!r} contains embeddings from "
                f"{payload.get('embedding_model')!r}, not {self.model_id!r}. Use a new "
                "collection or run an explicit full reindex."
            )

    def existing_payloads(self, chunks: Sequence[dict]) -> dict[int, dict]:
        if not chunks:
            return {}
        points = self.client.retrieve(
            self.collection,
            [vector_id(chunk["document_id"], chunk["id"]) for chunk in chunks],
            with_vectors=False,
        )
        return {
            int(point.payload["chunk_id"]): point.payload
            for point in points
            if point.payload and point.payload.get("record_type") == "chunk"
        }

    def upsert(self, chunks: Sequence[dict], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("Chunk and vector batch lengths differ")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise VectorConfigurationError(
                    f"Refusing {len(vector)}-dimension vector; collection expects {self.dimensions}"
                )

        from qdrant_client.models import PointStruct

        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            points.append(
                PointStruct(
                    id=vector_id(chunk["document_id"], chunk["id"]),
                    vector=list(vector),
                    payload=vector_payload(chunk, self.model_id),
                )
            )
        if points:
            self.client.upsert(self.collection, points, wait=True)

    def search(
        self, query_vector: Sequence[float], limit: int, document_ids: list[str] | None
    ) -> list[VectorCandidate]:
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

        must = [FieldCondition(key="record_type", match=MatchValue(value="chunk"))]
        if document_ids:
            must.append(
                FieldCondition(key="document_id", match=MatchAny(any=document_ids))
            )
        result = self.client.query_points(
            collection_name=self.collection,
            query=list(query_vector),
            query_filter=Filter(must=must),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        ).points
        return [
            VectorCandidate(
                chunk_id=int(point.payload["chunk_id"]),
                document_id=str(point.payload["document_id"]),
                score=float(point.score),
            )
            for point in result
            if point.payload and "chunk_id" in point.payload
        ]

    def delete_document(self, document_id: str) -> None:
        from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

        self.client.delete(
            self.collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id", match=MatchValue(value=document_id)
                        )
                    ]
                )
            ),
            wait=True,
        )

    def iter_chunk_points(self, batch_size: int = 256) -> Iterable[tuple[str, dict]]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        offset = None
        while True:
            points, offset = self.client.scroll(
                self.collection,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="record_type", match=MatchValue(value="chunk")
                        )
                    ]
                ),
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                yield str(point.id), point.payload or {}
            if offset is None:
                break

    def delete_points(self, point_ids: Sequence[str]) -> None:
        if point_ids:
            self.client.delete(self.collection, list(point_ids), wait=True)

    def ready(self) -> bool:
        self.ensure_collection()
        return True
