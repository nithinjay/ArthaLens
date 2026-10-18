#!/bin/sh
# Run the full Python suite in a Linux container: unit + OCR (tesseract) + database
# integration tests, against a throwaway database that is created, migrated and dropped.
# Your local `arthalens` database is never touched.
#   sh scripts/test-integration.sh              # everything
#   sh scripts/test-integration.sh -m integration
set -eu
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

DB=arthalens_it
as_super() { docker compose exec -T postgres psql -U postgres -d "$1" -v ON_ERROR_STOP=1 -qc "$2"; }
cleanup() { as_super postgres "DROP DATABASE IF EXISTS $DB WITH (FORCE)" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker compose up -d --wait postgres >/dev/null
docker compose build -q migrate ai-test
cleanup
as_super postgres "CREATE DATABASE $DB OWNER app_migrate"
as_super "$DB" "REVOKE ALL ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO app_api, app_ai;"
docker compose run --rm --no-deps \
  -e DATABASE_URL="postgres://app_migrate:${APP_MIGRATE_DB_PASSWORD}@postgres:5432/${DB}?sslmode=disable" \
  migrate --migrations-dir /db/migrations --no-dump-schema up >/dev/null

docker compose --profile test run --rm --no-deps \
  -e TEST_DB_AI_URL="postgresql://app_ai:${APP_AI_DB_PASSWORD}@postgres:5432/${DB}" \
  -e TEST_DB_API_URL="postgresql://app_api:${APP_API_DB_PASSWORD}@postgres:5432/${DB}" \
  -e TEST_DB_ADMIN_URL="postgresql://app_migrate:${APP_MIGRATE_DB_PASSWORD}@postgres:5432/${DB}" \
  ai-test /venv/bin/pytest "$@"
