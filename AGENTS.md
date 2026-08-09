# Repository guide

## Project layout

- `frontend/` contains the React/Vinext application, frontend tests, static assets, worker entrypoint, and optional D1 schema.
- `backend/` contains the FastAPI service and its Python test suite.
- `docs/` contains maintained architecture and operations documentation.
- `scripts/` contains repository automation; `examples/` contains sample content only.

## Working conventions

- Run JavaScript commands from the repository root through the scripts in `package.json`; they enter `frontend/` when needed.
- Keep application source, tests, and generated D1 migrations out of the repository root.
- Keep the backend SQLite schema as ordered migrations in `backend/app/migrations.py`. Append migrations—never edit an applied migration.
- Do not commit secrets. Copy `.env.example` to `.env` only for local use.

## Verification

- `npm run lint`
- `npm test`
- `npm run test:e2e`
- `./scripts/local_checks.sh` runs the complete local suite, including container checks.
