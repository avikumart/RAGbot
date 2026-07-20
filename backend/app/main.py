from __future__ import annotations

import hashlib
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import Settings
from .extraction import ExtractionError, chunk_pages, count_people, extract_pages
from .llm import generate_with_cerebras
from .retrieval import hybrid_retrieve, synthesize_answer
from .store import Store
from .vector_service import VectorService


logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    document_ids: list[str] | None = None
    person: str | None = Field(default=None, max_length=160)
    top_k: int = Field(default=4, ge=1, le=8)


def create_app(
    data_dir: Path | None = None, vector_service: VectorService | None = None
) -> FastAPI:
    settings = Settings.from_env(data_dir)
    store = Store(settings.data_dir)
    vectors = vector_service or VectorService(settings, store)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        store.initialize()
        yield

    app = FastAPI(
        title="Personagraph API",
        version="0.1.0",
        description="Private document ingestion and person-aware retrieval with grounded citations.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.vector_service = vectors
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        sqlite_status = "ready"
        sqlite_error = None
        try:
            with store.connect() as connection:
                connection.execute("SELECT 1").fetchone()
        except Exception as exc:
            sqlite_status, sqlite_error = "unavailable", str(exc)
        components = {
            "api": {"status": "ready"},
            "sqlite": {"status": sqlite_status, "error": sqlite_error},
            **vectors.health(),
        }
        degraded = any(
            component["status"] in {"degraded", "unavailable"}
            for component in components.values()
        )
        return {
            "status": "degraded" if degraded else "ok",
            "service": "personagraph-api",
            "components": components,
        }

    @app.get("/api/documents")
    def documents() -> list[dict]:
        return store.list_documents()

    @app.get("/api/people")
    def people(document_id: list[str] | None = None) -> list[dict]:
        return store.list_people(document_id)

    @app.post("/api/documents", status_code=201)
    async def upload_document(file: UploadFile = File(...)) -> dict:
        filename = Path(file.filename or "document").name
        payload = await file.read(settings.max_upload_bytes + 1)
        if len(payload) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="The maximum document size is 10 MB.")
        if not payload:
            raise HTTPException(status_code=400, detail="The uploaded document is empty.")
        try:
            pages = extract_pages(filename, payload)
            chunks = chunk_pages(pages)
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        document_id = uuid4().hex
        suffix = Path(filename).suffix.lower()
        safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(filename).stem).strip("-")[:48]
        stored_path = store.upload_dir / f"{document_id}-{safe_stem or 'document'}{suffix}"
        stored_path.write_bytes(payload)
        try:
            result = store.add_document(
                document_id=document_id,
                filename=filename,
                content_type=file.content_type or "application/octet-stream",
                stored_path=stored_path,
                digest=hashlib.sha256(payload).hexdigest(),
                size_bytes=len(payload),
                chunks=chunks,
                people=dict(count_people(chunks)),
            )
            try:
                processed, skipped = vectors.index_document(document_id)
                logger.info(
                    "Vector indexing completed document_id=%s processed=%d skipped=%d",
                    document_id,
                    processed,
                    skipped,
                )
            except Exception as exc:
                # SQLite is authoritative. The retained document remains searchable
                # lexically and is repairable through the backfill command.
                logger.warning(
                    "Document retained but requires vector reindex document_id=%s reason=%s",
                    document_id,
                    exc,
                )
            return result
        except Exception:
            stored_path.unlink(missing_ok=True)
            raise

    @app.delete("/api/documents/{document_id}")
    def delete_document(document_id: str) -> dict:
        if not store.delete_document(document_id):
            raise HTTPException(status_code=404, detail="Document not found.")
        try:
            vectors.delete_document(document_id)
        except Exception as exc:
            logger.warning(
                "SQLite document deleted; deferred Qdrant cleanup document_id=%s reason=%s",
                document_id,
                exc,
            )
        return {"deleted": True}

    @app.post("/api/chat")
    async def chat(payload: ChatRequest) -> dict:
        if not store.list_documents():
            raise HTTPException(status_code=409, detail="Upload a document before asking a question.")
        identified_people, sources, retrieval_mode = hybrid_retrieve(
            store,
            payload.message,
            payload.document_ids,
            payload.person,
            payload.top_k,
            vector_service=vectors,
            lexical_limit=settings.lexical_candidate_limit,
            vector_limit=settings.vector_candidate_limit,
        )
        generated = await generate_with_cerebras(
            api_key=settings.cerebras_api_key,
            base_url=settings.cerebras_base_url,
            model=settings.cerebras_model,
            question=payload.message,
            sources=sources,
        )
        return {
            "answer": generated or synthesize_answer(payload.message, identified_people, sources),
            "people": identified_people,
            "sources": sources,
            "mode": f"cerebras:{settings.cerebras_model}" if generated else "local-grounded",
            "retrieval_mode": retrieval_mode,
        }

    return app


app = create_app()
