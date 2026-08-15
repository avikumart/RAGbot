# Personagraph documentation

Start with the [system architecture](architecture.md) for the end-to-end design,
trust boundaries, data flow, and deployment topology. Component references are:

- [Backend](backend.md): FastAPI service, ingestion, retrieval, and operations.
- [Frontend](frontend.md): browser application, proxy boundary, and validation commands.
- [Database](database.md): authoritative SQLite records, migrations, and rebuildable vector data.
- [Architecture decision records](adr/README.md): durable design decisions and the
  workflow for proposing new ones.

For a complete local stack, copy `.env.example` to `.env` if optional settings are needed, then run `docker compose up --build` from the repository root.
