# Personagraph documentation

Start with the [system architecture](architecture.md) for the end-to-end design,
trust boundaries, data flow, and deployment topology. Component references are:

- [Backend](backend.md): FastAPI service, ingestion, retrieval, and operations.
- [Frontend](frontend.md): browser application, proxy boundary, and validation commands.
- [Database](database.md): authoritative PostgreSQL records, Alembic migrations, and rebuildable vector data.

For a complete local stack, copy `.env.example` to `.env` if optional settings are needed, then run `docker compose up --build` from the repository root.
