from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import Settings
from .extraction import ExtractionError, chunk_pages, count_people, extract_pages
from .llm import (
    LLMService,
    create_llm_provider,
    generate_with_cerebras,
    generate_with_cerebras_stream,
)
from .reranker import RerankerService
from .retrieval import hybrid_retrieve, synthesize_answer
from .store import Store
from .vector_service import VectorService


logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    document_ids: list[str] | None = None
    person: str | None = Field(default=None, max_length=160)
    top_k: int = Field(default=4, ge=1, le=8)
    session_id: str | None = Field(default=None, min_length=8, max_length=128)
    client_message_id: str | None = Field(default=None, min_length=8, max_length=128)
    stream: bool = False


class CreateSessionRequest(BaseModel):
    topic: str | None = Field(default=None, max_length=120)
    document_ids: list[str] | None = None
    person: str | None = Field(default=None, max_length=160)


class UpdateSessionRequest(BaseModel):
    topic: str | None = Field(default=None, max_length=120)
    document_ids: list[str] | None = None
    person: str | None = Field(default=None, max_length=160)


def initial_topic(message: str) -> str:
    normalized = re.sub(r"\s+", " ", message).strip()
    return normalized[:96].rstrip() or "New conversation"


def opaque_owner_id(identity: str) -> str:
    return hashlib.sha256(f"personagraph-owner:v1:{identity}".encode()).hexdigest()


def request_owner(request: Request, settings: Settings) -> str:
    """Accept an owner only from the signed same-origin proxy.

    A development API with no proxy secret deliberately has one fixed owner,
    never a browser-provided identity. This keeps local use frictionless while
    avoiding an arbitrary-user-id API in production.
    """
    if not settings.auth_proxy_secret:
        return opaque_owner_id(settings.local_development_owner)

    owner = request.headers.get("x-personagraph-owner")
    timestamp = request.headers.get("x-personagraph-owner-timestamp")
    signature = request.headers.get("x-personagraph-owner-signature")
    if not owner or not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Authenticated session required.")
    try:
        issued_at = datetime.fromtimestamp(int(timestamp), UTC)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid authenticated session.") from exc
    if abs((datetime.now(UTC) - issued_at).total_seconds()) > 300:
        raise HTTPException(status_code=401, detail="Authenticated session expired.")
    expected = hmac.new(
        settings.auth_proxy_secret.encode(), f"{owner}:{timestamp}".encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid authenticated session.")
    return owner


def encode_cursor(cursor: tuple[str, str] | None) -> str | None:
    if not cursor:
        return None
    return urlsafe_b64encode(f"{cursor[0]}\n{cursor[1]}".encode()).decode()


def decode_cursor(value: str | None) -> tuple[str, str] | None:
    if not value:
        return None
    try:
        timestamp, session_id = urlsafe_b64decode(value.encode()).decode().split("\n", 1)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid session cursor.") from exc
    if not timestamp or not session_id:
        raise HTTPException(status_code=400, detail="Invalid session cursor.")
    return timestamp, session_id


def create_app(
    data_dir: Path | None = None,
    vector_service: VectorService | None = None,
    llm_service: LLMService | None = None,
) -> FastAPI:
    settings = Settings.from_env(data_dir)
    store = Store(settings.data_dir, settings.database_url)
    vectors = vector_service or VectorService(settings, store)
    llm = llm_service or LLMService(create_llm_provider(settings))

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
    app.state.llm_service = llm
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        database_status = "ready"
        database_error = None
        try:
            with store.connect() as connection:
                connection.execute("SELECT 1").fetchone()
        except Exception as exc:
            database_status, database_error = "unavailable", str(exc)
        components = {
            "api": {"status": "ready"},
            store.database_component: {
                "status": database_status,
                "error": database_error,
            },
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
            chunks = chunk_pages(pages, limit=settings.chunk_size, overlap=settings.chunk_overlap)
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
                # PostgreSQL is authoritative. The retained document remains searchable
                # lexically and is repairable through the backfill command.
                store.set_vector_status(
                    document_id,
                    "needs_reindex",
                    settings.embedding_model,
                    str(exc)[:500],
                )
                logger.warning(
                    "Document retained but requires vector reindex document_id=%s reason=%s",
                    document_id,
                    exc,
                )
            return store.get_document(document_id) or result
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
                "PostgreSQL document deleted; deferred Qdrant cleanup document_id=%s reason=%s",
                document_id,
                exc,
            )
        return {"deleted": True}

    @app.post("/api/sessions", status_code=201)
    def create_session(payload: CreateSessionRequest, request: Request) -> dict:
        owner_id = request_owner(request, settings)
        return store.create_chat_session(
            owner_id,
            topic=(payload.topic or "New conversation").strip() or "New conversation",
            document_ids=payload.document_ids,
            person=payload.person,
        )

    @app.get("/api/sessions")
    def list_sessions(request: Request, limit: int = 30, cursor: str | None = None) -> dict:
        owner_id = request_owner(request, settings)
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100.")
        sessions, next_cursor = store.list_chat_sessions(
            owner_id, limit, decode_cursor(cursor)
        )
        return {"sessions": sessions, "next_cursor": encode_cursor(next_cursor)}

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str, request: Request) -> dict:
        session = store.get_chat_session(request_owner(request, settings), session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return session

    @app.patch("/api/sessions/{session_id}")
    def update_session(session_id: str, payload: UpdateSessionRequest, request: Request) -> dict:
        fields = payload.model_fields_set
        if "topic" in fields and not (payload.topic or "").strip():
            raise HTTPException(status_code=422, detail="A conversation topic is required.")
        session = store.update_chat_session(
            request_owner(request, settings),
            session_id,
            topic=payload.topic.strip() if payload.topic else None,
            document_ids=payload.document_ids,
            person=payload.person,
            update_topic="topic" in fields,
            update_document_ids="document_ids" in fields,
            update_person="person" in fields,
        )
        if not session:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return session

    @app.delete("/api/sessions/{session_id}", status_code=204, response_class=Response)
    def delete_session(session_id: str, request: Request) -> Response:
        if not store.delete_chat_session(request_owner(request, settings), session_id):
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return Response(status_code=204)

    @app.post("/api/chat", response_model=None)
    async def chat(payload: ChatRequest, request: Request) -> Response | dict:
        owner_id = request_owner(request, settings)
        client_message_id = payload.client_message_id or uuid4().hex
        history: list[dict] = []
        scoped_person = payload.person
        scoped_doc_ids = payload.document_ids
        is_streaming = payload.stream or "text/event-stream" in request.headers.get("accept", "")

        if payload.session_id:
            session = store.get_chat_session(owner_id, payload.session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Conversation not found.")
            persisted = store.find_chat_turn(
                owner_id, payload.session_id, client_message_id
            )
            if persisted:
                assistant = persisted["assistant_message"]
                if is_streaming:
                    async def replay_stream():
                        meta = {
                            "sources": assistant["sources"],
                            "people": [],
                            "mode": assistant["mode"],
                            "retrieval_mode": assistant["retrieval_mode"],
                        }
                        yield f"event: metadata\ndata: {json.dumps(meta)}\n\n"
                        yield f"event: token\ndata: {json.dumps({'delta': assistant['content']})}\n\n"
                        complete_payload = {
                            "session_id": persisted["session"]["id"],
                            "topic": persisted["session"]["topic"],
                            "user_message": persisted["user_message"],
                            "assistant_message": assistant,
                            "answer": assistant["content"],
                        }
                        yield f"event: complete\ndata: {json.dumps(complete_payload)}\n\n"

                    return StreamingResponse(
                        replay_stream(),
                        media_type="text/event-stream",
                        headers={
                            "Cache-Control": "no-cache",
                            "Connection": "keep-alive",
                            "X-Accel-Buffering": "no",
                        },
                    )
                return {
                    "answer": assistant["content"], "sources": assistant["sources"],
                    "mode": assistant["mode"], "retrieval_mode": assistant["retrieval_mode"],
                    "session_id": persisted["session"]["id"],
                    "topic": persisted["session"]["topic"],
                    "user_message": persisted["user_message"],
                    "assistant_message": assistant,
                }
            history = session.get("messages", [])[-6:]
            if scoped_person is None and session.get("person"):
                scoped_person = session.get("person")
            if scoped_doc_ids is None and session.get("document_ids"):
                scoped_doc_ids = session.get("document_ids")

        if not store.list_documents():
            raise HTTPException(status_code=409, detail="Upload a document before asking a question.")
        identified_people, sources, retrieval_mode = hybrid_retrieve(
            store,
            payload.message,
            scoped_doc_ids,
            scoped_person,
            payload.top_k,
            vector_service=vectors,
            lexical_limit=settings.lexical_candidate_limit,
            vector_limit=settings.vector_candidate_limit,
            reranker=RerankerService(enabled=settings.reranker_enabled, model_name=settings.reranker_model),
            history=history,
        )

        if is_streaming:
            stream_gen = None
            if llm_service is not None:
                stream_gen, mode = await llm.generate_stream(
                    question=payload.message,
                    sources=sources,
                    history=history,
                )
            elif settings.llm_provider == "cerebras":
                if settings.cerebras_api_key:
                    stream_gen = generate_with_cerebras_stream(
                        api_key=settings.cerebras_api_key,
                        base_url=settings.cerebras_base_url,
                        model=settings.cerebras_model,
                        question=payload.message,
                        sources=sources,
                        history=history,
                    )
                    mode = f"cerebras:{settings.cerebras_model}"
                else:
                    stream_gen = None
                    mode = "local-grounded"
            else:
                stream_gen, mode = await llm.generate_stream(
                    question=payload.message,
                    sources=sources,
                    history=history,
                )

            async def event_stream() -> AsyncIterator[str]:
                meta = {
                    "sources": sources,
                    "people": identified_people,
                    "mode": mode,
                    "retrieval_mode": retrieval_mode,
                }
                yield f"event: metadata\ndata: {json.dumps(meta)}\n\n"

                accumulated_tokens: list[str] = []
                if stream_gen is not None:
                    try:
                        async for token in stream_gen:
                            if token:
                                accumulated_tokens.append(token)
                                yield f"event: token\ndata: {json.dumps({'delta': token})}\n\n"
                    except Exception as exc:
                        logger.warning("Stream token error: %s", exc)

                full_answer = "".join(accumulated_tokens).strip()
                persisted_mode = mode
                if not full_answer:
                    persisted_mode = "local-grounded"
                    full_answer = synthesize_answer(payload.message, identified_people, sources)
                    for chunk in re.split(r"(\s+)", full_answer):
                        if chunk:
                            yield f"event: token\ndata: {json.dumps({'delta': chunk})}\n\n"

                if sources and not any(f"[{source['index']}]" in full_answer for source in sources):
                    citation_suffix = "\n\n" + " ".join(f"[{source['index']}]" for source in sources[:2])
                    full_answer += citation_suffix
                    yield f"event: token\ndata: {json.dumps({'delta': citation_suffix})}\n\n"

                persisted = store.persist_chat_turn(
                    owner_id,
                    session_id=payload.session_id,
                    client_message_id=client_message_id,
                    content=payload.message,
                    document_ids=payload.document_ids,
                    person=payload.person,
                    answer=full_answer,
                    sources=sources,
                    mode=persisted_mode,
                    retrieval_mode=retrieval_mode,
                    topic=initial_topic(payload.message),
                )
                if not persisted:
                    yield f"event: error\ndata: {json.dumps({'detail': 'Conversation not found.'})}\n\n"
                    return

                assistant = persisted["assistant_message"]
                complete_payload = {
                    "session_id": persisted["session"]["id"],
                    "topic": persisted["session"]["topic"],
                    "user_message": persisted["user_message"],
                    "assistant_message": assistant,
                    "answer": assistant["content"],
                }
                yield f"event: complete\ndata: {json.dumps(complete_payload)}\n\n"

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        if llm_service is not None:
            generated, mode = await llm.generate(
                question=payload.message,
                sources=sources,
                history=history,
            )
        elif settings.llm_provider == "cerebras":
            if settings.cerebras_api_key:
                generated = await generate_with_cerebras(
                    api_key=settings.cerebras_api_key,
                    base_url=settings.cerebras_base_url,
                    model=settings.cerebras_model,
                    question=payload.message,
                    sources=sources,
                    history=history,
                )
                mode = f"cerebras:{settings.cerebras_model}" if generated else "local-grounded"
            else:
                generated, mode = None, "local-grounded"
        else:
            generated, mode = await llm.generate(
                question=payload.message,
                sources=sources,
                history=history,
            )
        answer = generated or synthesize_answer(payload.message, identified_people, sources)
        persisted = store.persist_chat_turn(
            owner_id,
            session_id=payload.session_id,
            client_message_id=client_message_id,
            content=payload.message,
            document_ids=payload.document_ids,
            person=payload.person,
            answer=answer,
            sources=sources,
            mode=mode,
            retrieval_mode=retrieval_mode,
            topic=initial_topic(payload.message),
        )
        if not persisted:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        assistant = persisted["assistant_message"]
        return {
            "answer": assistant["content"], "people": identified_people,
            "sources": assistant["sources"], "mode": assistant["mode"],
            "retrieval_mode": assistant["retrieval_mode"],
            "session_id": persisted["session"]["id"],
            "topic": persisted["session"]["topic"],
            "user_message": persisted["user_message"],
            "assistant_message": assistant,
        }

    return app


app = create_app()
