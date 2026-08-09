# Database

Personagraph uses two different data layers with distinct responsibilities.

| Store | Authority | Contents | Recovery |
| --- | --- | --- | --- |
| SQLite | Authoritative | Documents, stored-file metadata, extracted chunks, people, index state, conversations, messages, and citation snapshots. | Back up the `personagraph_data` volume. |
| Qdrant | Rebuildable | Embeddings, content hashes, model metadata, scope metadata, and SQLite document/chunk references. | Recreate the collection and run vector backfill. |

## SQLite lifecycle

SQLite is stored as `/data/personagraph.db` in the API container and persists in the Compose `personagraph_data` volume. Uploaded files are stored beneath `/data/uploads`. `Store.initialize()` applies migrations and retries any queued file cleanup when the API starts.

Schema migrations live in `backend/app/migrations.py` and are tracked using SQLite `PRAGMA user_version`. Migrations execute in order inside a transaction. To change the schema, append a new migration version to the `MIGRATIONS` tuple; never alter a migration that may already have been applied.

Deleting a document first commits the SQLite removal and a cleanup record. File removal and Qdrant deletion happen afterward as best-effort work, so a transient filesystem or vector outage cannot reverse the committed deletion. Startup and later deletes retry pending managed-file cleanup.

## Vector lifecycle

Vector data is stored in the Compose `qdrant_data` volume. SQLite remains the source for excerpt text and document scoping, even when a Qdrant hit is used. The `vector_index_state` table tracks `pending`, `indexing`, `ready`, `needs_reindex`, and `disabled` states.

Run this after restoring data, repairing vectors, or intentionally changing vector configuration:

```bash
docker compose run --rm api python -m app.vector_admin backfill
```

Do not change model dimensions in an existing collection. Choose a new `QDRANT_COLLECTION`, set the matching `EMBEDDING_DIMENSIONS`, verify results, then retire the old collection.

## Frontend D1 schema

`frontend/db/schema.ts` and `frontend/drizzle/` are separate from the API's SQLite database. They are an opt-in hosted D1 example, not the source of truth for application documents or conversations. Generate its migrations with:

```bash
npm run db:generate
```
