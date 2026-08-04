# Personagraph

Personagraph is a local-first prototype for asking questions about people mentioned in personal documents. It accepts PDF, DOCX, TXT, and Markdown files, indexes likely names and supporting passages, retrieves person-specific context, and returns answers with expandable citations.

The default experience uses local hybrid retrieval: BM25-style lexical search plus semantic search with local embeddings in Qdrant. Answer generation remains deterministic and grounded unless a Cerebras API key is configured. No API key is needed for embeddings, and document content is not sent to an embedding service.

## Run locally with Docker

Requirements: Docker Desktop with Compose.

To enable Cerebras generation, copy the environment template and add your API key. You can skip this step to use local grounded synthesis.

```bash
cp .env.example .env
```

Edit `.env` and set `CEREBRAS_API_KEY` as described in [Cerebras API generation](#cerebras-api-generation).

```bash
docker compose up --build
```

Then open:

- App: <http://localhost:3000>
- API documentation: <http://localhost:8000/docs>

Try the included `examples/people-notes.txt`, or upload one of your own documents. Files and the authoritative SQLite database persist in `personagraph_data`; derived Qdrant vectors persist separately in `qdrant_data`. The embedding model cache uses `embedding_cache`.

The first upload downloads `BAAI/bge-small-en-v1.5` into the local model-cache volume. It is a 384-dimensional, MIT-licensed English embedding model; expect roughly 130 MB of model data plus runtime overhead. Later starts reuse the cache.

To stop the app:

```bash
docker compose down
```

To also erase uploaded documents, SQLite, model cache, and vectors:

```bash
docker compose down --volumes
```

Qdrant has no host port in this production-shaped Compose setup. Only the API reaches it on the internal network. Removing only the `personagraph_qdrant_data` volume does not affect uploaded files or SQLite; run the backfill below to rebuild it.

## Vector retrieval configuration

Defaults are shown in `.env.example`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `VECTOR_SEARCH_ENABLED` | `true` | Enable indexing and hybrid retrieval; set `false` for lexical-only operation. |
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant address. Compose fixes this to its internal service URL. |
| `QDRANT_COLLECTION` | `personagraph_chunks` | Vector collection name. |
| `EMBEDDING_PROVIDER` | `local` | Embedding provider; only local FastEmbed is supported currently. |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Exact embedding model identifier. |
| `EMBEDDING_DIMENSIONS` | `384` | Must match the model and collection. |
| `EMBEDDING_BATCH_SIZE` | `32` | Chunk indexing batch size. |
| `VECTOR_CANDIDATE_LIMIT` | `20` | Maximum semantic candidates before rank fusion. |
| `LEXICAL_CANDIDATE_LIMIT` | `20` | Maximum lexical candidates before rank fusion. |
| `VECTOR_TIMEOUT_SECONDS` | `5` | Qdrant operation timeout. |
| `EMBEDDING_TIMEOUT_SECONDS` | `30` | Local embedding-operation timeout. |

To backfill existing SQLite chunks, repair missing/outdated vectors, and remove orphan vectors:

```bash
docker compose run --rm api python -m app.vector_admin backfill
```

The command is idempotent and reports `processed`, `skipped`, `failed`, and `deleted` counts as JSON. It batches work, commits each vector upsert, and can be interrupted and rerun safely.

Do not change the model or dimensions in an existing collection. Personagraph stores collection-level model metadata and refuses model/dimension mismatches. To switch models safely, choose a new `QDRANT_COLLECTION` name and correct `EMBEDDING_DIMENSIONS`, restart the API, then run the backfill. The old collection can be removed after the new index is verified.

If `/api/health` reports Qdrant or embeddings as degraded, check `docker compose logs api qdrant`, confirm the model cache has download space, and verify the collection/model/dimension settings. Uploads remain stored in SQLite and chat automatically uses lexical retrieval, with `retrieval_mode: "lexical-fallback"`, until vector service recovers. Run backfill afterward to repair missed indexing.

## Cerebras API generation

Create an API key in the [Cerebras Cloud Console](https://cloud.cerebras.ai), then put it in the `.env` file at the repository root, next to `docker-compose.yml`:

```bash
CEREBRAS_API_KEY=your-api-key-here
```

Do not put the real key in `.env.example`, source files, or GitHub workflow files. The local `.env` file is excluded from both Git and Docker build contexts; Docker Compose reads it and passes the key only to the API service at runtime.

The remaining settings already have production defaults:

```bash
CEREBRAS_API_BASE_URL=https://api.cerebras.ai/v1
CEREBRAS_MODEL=gpt-oss-120b
```

When running the backend outside Docker, export the same variables in the shell that starts Uvicorn. See the [official Cerebras quickstart](https://inference-docs.cerebras.ai/quickstart) for API-key creation and account troubleshooting.

## Test cases

Install Chromium once, then run the frontend render and browser tests, backend API tests,
and Compose validation in containers:

```bash
npx playwright install chromium
./scripts/local_checks.sh
```

The API and unit tests cover empty and legacy SQLite database upgrades, idempotent schema migrations, document persistence, vector payloads and IDs, hybrid fusion, person and document scoping, cited semantic retrieval, lexical fallback, recoverable file deletion, idempotent backfill, orphan cleanup, empty-library behavior, and unsupported files. SQLite schema changes are ordered migrations tracked by `PRAGMA user_version`; migration 001 owns the initial schema, and later schema changes append a new migration.

Pull requests run `.github/workflows/ci.yml`, which performs three independent checks:

- FastAPI endpoint, mocked vector retrieval/indexing, and mocked Cerebras request-contract tests
- SQLite schema, foreign-key, persistence, and cascade-delete tests
- Frontend lint, build, server-rendering tests, and a browser-level degraded-index workflow

The vector tests use fake vector stores and embedding providers, so they do not require a
Qdrant service or download an embedding model. The Cerebras tests are network-isolated and
never require an API key or consume API credits.

## Architecture

- `app/`: responsive React/vinext browser client
- `backend/app/`: FastAPI ingestion, authoritative SQLite storage, local embeddings, Qdrant indexing, hybrid retrieval, and optional Cerebras generation
- `backend/tests/`: end-to-end API tests using a temporary data directory
- `docker-compose.yml`: production-shaped web/API/Qdrant stack with separate persistent volumes

SQLite is the system of record for documents, stored-file metadata, extracted chunks, people, and their relationships. Qdrant stores only rebuildable embeddings, content hashes, model identifiers, scoping metadata, and SQLite document/chunk references—never authoritative chunk text. Upload commits SQLite first and then indexes vectors in batches. A failed vector step marks the document for reindex without rolling back SQLite.

`GET /api/documents` includes `index_status`, `index_error`, and `index_updated_at` for every document. Status values currently include `pending`, `indexing`, `ready`, `needs_reindex`, and `disabled`. A document with no index-state row (for example, a legacy document) defaults to `pending`, with a null error and update timestamp. Index failures return a safe, actionable error message; internal exception details are retained only for diagnostics and are not exposed by this endpoint.

At query time Personagraph scopes both retrieval paths, identifies people using existing behavior, and combines lexical and vector ranks with deterministic Reciprocal Rank Fusion. Person boosts are applied after fusion. Every Qdrant hit is checked against scoped SQLite rows, and source excerpts, filenames, and pages always come from SQLite. This also prevents stale vectors for deleted documents from reaching an answer.

Deletion is ordered so SQLite remains authoritative and post-commit cleanup is recoverable. A single SQLite transaction first records the stored path in `pending_file_cleanup`, then deletes the document row and its cascading metadata. After the transaction commits, the API best-effort unlinks the uploaded file and removes the cleanup record; an unlink failure is logged, recorded with its attempt details, and still returns a successful document deletion. Pending files are retried during the next startup or deletion. Matching vectors are deleted last. If Qdrant is unavailable, deletion still succeeds; the next backfill/reconciliation removes the vector orphan. Qdrant or filesystem loss cannot make an already-committed deletion appear to have failed.

## Privacy and limitations

- Uploaded bytes and the SQLite index stay in the local Docker volume.
- Local embedding sends no text to a hosted service. Qdrant runs only on the Compose network by default, and its payload is not an authorization boundary.
- When `CEREBRAS_API_KEY` is configured, each question and its retrieved source excerpts are sent to the Cerebras API. The application does not send the complete document unless its full contents happen to be selected as retrieved excerpts.
- An external embedding provider is intentionally not enabled by default. If one is added later, sending chunk text externally must be an explicit configuration choice with the provider's privacy terms reviewed.
- Name recognition is heuristic and may include organizations or miss uncommon name formats.
- Text-based PDFs are supported; scanned PDFs need OCR before upload.
- This is a prototype without user accounts or document-level access control. Do not expose it directly to the public internet.
