# Personagraph

Personagraph is a local-first prototype for asking questions about people mentioned in personal documents. It accepts PDF, DOCX, TXT, and Markdown files, indexes likely names and supporting passages, retrieves person-specific context, and returns answers with expandable citations.

The default experience is fully usable without an API key or model download. It uses deterministic grounded synthesis over a lightweight hybrid retrieval index. If Ollama is connected, the same retrieved evidence is passed to a local language model and the API falls back safely when that model is unavailable.

## Run locally with Docker

Requirements: Docker Desktop with Compose.

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

## Optional Ollama generation

The zero-setup mode already retrieves and synthesizes citsd answers. To use a local Ollama model instead:

```bash
docker compose -f docker-compose.yml -f docker-compose.ollama.yml --profile ollama up -d ollama
docker compose -f docker-compose.yml -f docker-compose.ollama.yml exec ollama ollama pull llama3.2:3b
docker compose -f docker-compose.yml -f docker-compose.ollama.yml --profile ollama up --build
```

Change `OLLAMA_MODEL` in a local `.env` file if you prefer another installed model.

## Test cases

Run the frontend server-render test, backend API tests, and Compose validation in containers:

```bash
./scripts/local_checks.sh
```

The API tests cover document persistence, person extraction, cited retrieval, per-document scoping, empty-library behavior, and unsupported file handling.

## Architecture

- `app/`: responsive React/vinext browser client
- `backend/app/`: FastAPI ingestion, SQLite storage, person-aware retrieval, and optional Ollama generation
- `backend/tests/`: end-to-end API tests using a temporary data directory
- `docker-compose.yml`: production-shaped local web/API images and persistent volume

Retrieval is intentionally lightweight for a personal prototype: BM25-style lexical ranking plus exact person boosts. This keeps the first run private, predictable, and fast. For a larger corpus, the retrieval module is the seam to replace with a vector database and embedding model.

## Privacy and limitations

- Uploaded bytes and the index stay in the local Docker volume unless you explicitly configure an external model endpoint.
- Name recognition is heuristic and may include organizations or miss uncommon name formats.
- Text-based PDFs are supported; scanned PDFs need OCR before upload.
- This is a prototype without user accounts or document-level access control. Do not expose it directly to the public internet.

