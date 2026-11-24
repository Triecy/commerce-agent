#!/usr/bin/env bash
# Verify the core stack: pgvector is installed in Postgres and Redis answers PING.
# Usage: deploy/scripts/stack-check.sh "<docker compose command prefix>"
set -euo pipefail

COMPOSE="$1"
SQL="SELECT extversion FROM pg_extension WHERE extname = 'vector'"

version="$($COMPOSE exec -T postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAc \"$SQL\"")"
if [[ -z "$version" ]]; then
  echo "postgres: pgvector extension NOT installed" >&2
  exit 1
fi
echo "postgres: healthy, pgvector $version installed"

if [[ "$($COMPOSE exec -T redis redis-cli ping)" != *PONG* ]]; then
  echo "redis: no PONG" >&2
  exit 1
fi
echo "redis: healthy (PONG)"
