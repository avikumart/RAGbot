#!/usr/bin/env sh
set -eu

npm test
docker build --target test -t personagraph-api-test ./backend
docker run --rm personagraph-api-test
docker compose config --quiet

