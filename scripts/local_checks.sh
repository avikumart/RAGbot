#!/usr/bin/env sh
set -eu

npm run lint
npm test
npm run test:e2e
docker build --target test -t personagraph-api-test ./backend
docker run --rm personagraph-api-test
docker compose config --quiet

CHECKS_PROJECT=personagraph-checks
cleanup_postgres() {
  docker compose -p "$CHECKS_PROJECT" down --volumes --remove-orphans
}
trap cleanup_postgres EXIT INT TERM

POSTGRES_DB=personagraph_test docker compose -p "$CHECKS_PROJECT" up -d --wait postgres
docker run --rm \
  --network "${CHECKS_PROJECT}_default" \
  -e TEST_POSTGRES_URL=postgresql://personagraph:personagraph@postgres:5432/personagraph_test \
  personagraph-api-test \
  pytest -q tests/test_postgres_integration.py
