# Personagraph

Personagraph is a local-first prototype for asking questions about people mentioned in personal documents. It accepts PDF, DOCX, TXT, and Markdown files, indexes likely names and supporting passages, retrieves person-specific context, and returns answers with expandable citations.

The default experience is fully usable without an API key or model download. It uses deterministic grounded synthesis over a lightweight hybrid retrieval index. When a Cerebras API key is configured, the same retrieved evidence is sent to the `gpt-oss-120b` model for generation. The API falls back safely to local grounded synthesis if Cerebras is not configured or unavailable.

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

Try the included `examples/people-notes.txt`, or upload one of your own documents. Files and the SQLite index persist in the `personagraph_data` Docker volume.

To stop the app:

```bash
docker compose down
```

To also erase uploaded documents and the local index:

```bash
docker compose down --volumes
```

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

Run the frontend server-render test, backend API tests, and Compose validation in containers:

```bash
./scripts/local_checks.sh
```

The API tests cover document persistence, person extraction, cited retrieval, per-document scoping, empty-library behavior, and unsupported file handling.

Pull requests run `.github/workflows/ci.yml`, which performs three independent checks:

- FastAPI endpoint and mocked Cerebras request-contract tests
- SQLite schema, foreign-key, persistence, and cascade-delete tests
- Frontend lint, build, and server-rendering tests

The Cerebras tests are network-isolated and never require an API key or consume API credits.

## Architecture

- `app/`: responsive React/vinext browser client
- `backend/app/`: FastAPI ingestion, SQLite storage, person-aware retrieval, and optional Cerebras generation
- `backend/tests/`: end-to-end API tests using a temporary data directory
- `docker-compose.yml`: production-shaped local web/API images and persistent volume

Retrieval is intentionally lightweight for a personal prototype: BM25-style lexical ranking plus exact person boosts. This keeps the first run private, predictable, and fast. For a larger corpus, the retrieval module is the seam to replace with a vector database and embedding model.

## Privacy and limitations

- Uploaded bytes and the SQLite index stay in the local Docker volume.
- When `CEREBRAS_API_KEY` is configured, each question and its retrieved source excerpts are sent to the Cerebras API. The application does not send the complete document unless its full contents happen to be selected as retrieved excerpts.
- Name recognition is heuristic and may include organizations or miss uncommon name formats.
- Text-based PDFs are supported; scanned PDFs need OCR before upload.
- This is a prototype without user accounts or document-level access control. Do not expose it directly to the public internet.
