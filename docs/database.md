# Database

Personagraph uses two data layers with distinct responsibilities.

| Store | Authority | Contents | Recovery |
| --- | --- | --- | --- |
| PostgreSQL | Authoritative | Documents, stored-file metadata, extracted chunks, people, index state, conversations, messages, citation snapshots, and cleanup queue. | Back up and restore the `postgres_data` volume or use PostgreSQL-native backups. |
| Qdrant | Rebuildable | Embeddings, content hashes, model metadata, scope metadata, and PostgreSQL document/chunk references. | Recreate the collection and run vector backfill. |

Managed uploaded files remain under `/data/uploads` in the API container and
persist in the separate `personagraph_data` volume.

## PostgreSQL lifecycle

Docker Compose starts a health-checked PostgreSQL 17 service before the API. The
API reads `DATABASE_URL`, applies all pending Alembic revisions during startup,
then retries queued managed-file cleanup. `/api/health` reports the database as
`postgresql`.

The baseline schema is
`backend/alembic/versions/001_initial_schema.py`. Future changes must add a new
ordered revision; never edit a revision that may have been applied. From an
environment with backend dependencies installed:

```bash
cd backend
DATABASE_URL=postgresql://personagraph:personagraph@localhost:5432/personagraph alembic current
alembic revision -m "describe the schema change"
```

Review generated migrations, including downgrade behavior, before running
`alembic upgrade head`. The historical ordered migrations in
`backend/app/migrations.py` are retained unchanged for legacy SQLite import and
compatibility tests; they no longer manage the production schema.

Deleting a document first commits the PostgreSQL removal and a cleanup record.
File removal and Qdrant deletion happen afterward as best-effort work, so a
transient filesystem or vector outage cannot reverse the committed deletion.
Startup and later deletes retry pending managed-file cleanup.

## One-time SQLite import

Before upgrading an existing deployment, stop writes and back up the
`personagraph_data` volume. The source SQLite database must have been opened by
the previous application version once so all three legacy migrations are
present. Build the new API, start PostgreSQL, and import into an empty target:

```bash
docker compose build api
docker compose up -d postgres
docker compose run --rm api python -m app.sqlite_import /data/personagraph.db
```

The importer applies Alembic revision 001, refuses a non-empty PostgreSQL
target, copies all current tables in one transaction, preserves chunk IDs used
by Qdrant, and advances the PostgreSQL identity sequence. It prints per-table
row counts on success and never deletes the SQLite source. Start the full stack
after verifying the counts:

```bash
docker compose up --build
```

## Vector lifecycle

Vector data is stored in the Compose `qdrant_data` volume. PostgreSQL remains
the source for excerpt text and document scoping, even when a Qdrant hit is
used. The `vector_index_state` table tracks `pending`, `indexing`, `ready`,
`needs_reindex`, and `disabled` states.

Run this after restoring data, importing SQLite, repairing vectors, or
intentionally changing vector configuration:

```bash
docker compose run --rm api python -m app.vector_admin backfill
```

Do not change model dimensions in an existing collection. Choose a new
`QDRANT_COLLECTION`, set the matching `EMBEDDING_DIMENSIONS`, verify results,
then retire the old collection.

## Frontend D1 schema

`frontend/db/schema.ts` and `frontend/drizzle/` are separate from the API's
PostgreSQL database. They are an opt-in hosted D1 example, not the source of
truth for application documents or conversations. Generate its migrations with:

```bash
npm run db:generate
```
