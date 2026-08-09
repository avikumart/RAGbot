# Backend

The backend is a FastAPI application in `backend/app/`. It ingests documents, persists authoritative records in SQLite, retrieves supporting passages, and optionally creates answers with Cerebras.

## Run and test

Docker Compose is the normal local runtime and exposes the API at `http://localhost:8000`; interactive OpenAPI documentation is available at `/docs`.

```bash
docker compose up --build
```

The Python tests live in `backend/tests/`. The repository check script builds the backend test image and runs the suite. Run `./scripts/local_checks.sh` for the whole application check.

## HTTP API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Reports API, SQLite, embedding, and Qdrant health. |
| `GET`, `POST /api/documents` | Lists documents or uploads a PDF, DOCX, TXT, or Markdown file. Uploads are limited to 10 MB. |
| `DELETE /api/documents/{id}` | Deletes a document and schedules recoverable file/vector cleanup. |
| `GET /api/people` | Lists detected people; optional repeated `document_id` query parameters scope results. |
| `POST /api/chat` | Retrieves scoped citations and persists a conversational turn. |
| `POST`, `GET /api/sessions` | Creates or lists owner-scoped conversations. |
| `GET`, `PATCH`, `DELETE /api/sessions/{id}` | Reads, updates, or removes one owner-scoped conversation. |

The frontend calls the backend through same-origin route handlers. In production, the route handlers attach a signed owner identity. Set the same non-empty `AUTH_PROXY_SECRET` in both services before exposing the stack. When it is unset, the API intentionally uses one fixed local-development owner.

## Ingestion and retrieval

Uploads are extracted into pages and chunks, then SQLite is committed before vector indexing begins. If vector indexing fails, the document remains available through lexical retrieval and is marked `needs_reindex`. Backfill safely reconciles missing, outdated, and orphaned vectors:

```bash
docker compose run --rm api python -m app.vector_admin backfill
```

Semantic retrieval uses local FastEmbed with `BAAI/bge-small-en-v1.5` by default. Qdrant and lexical candidates are combined with deterministic reciprocal-rank fusion; cited text is always read from SQLite. Set `CEREBRAS_API_KEY` to enable optional generated answers. Without it, the API returns deterministic grounded synthesis.

## Configuration

The primary settings are defined in `backend/app/config.py` and documented in `.env.example`: data directory, CORS origins, vector service, embedding model and limits, Cerebras, and proxy authentication. Keep the configured embedding dimensions aligned with the selected model. Changing models requires a new `QDRANT_COLLECTION` followed by backfill.
