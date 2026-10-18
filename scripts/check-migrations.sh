#!/bin/sh
# Prove every migration can go up, fully down, and up again (AC-1.4).
# Uses a throwaway database, so your local data in `arthalens` is never touched.
# Prerequisite: the stack has been built and postgres is running (docker compose up -d).
set -eu

cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

DB=arthalens_migcheck
URL="postgres://app_migrate:${APP_MIGRATE_DB_PASSWORD}@postgres:5432/${DB}?sslmode=disable"

as_super() { docker compose exec -T postgres psql -U postgres -d "$1" -v ON_ERROR_STOP=1 -qc "$2"; }
dbmate() {
  docker compose run --rm --no-deps -e DATABASE_URL="$URL" migrate \
    --migrations-dir /db/migrations --no-dump-schema "$@"
}

cleanup() { as_super postgres "DROP DATABASE IF EXISTS $DB" >/dev/null 2>&1 || true; }
trap cleanup EXIT

cleanup
as_super postgres "CREATE DATABASE $DB OWNER app_migrate"
as_super "$DB" "REVOKE ALL ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO app_api, app_ai;"

COUNT=$(ls database/migrations/*.sql | wc -l | tr -d ' ')
echo "== up ($COUNT migrations)"; dbmate up
echo "== down x$COUNT"
i=0; while [ "$i" -lt "$COUNT" ]; do dbmate rollback; i=$((i + 1)); done
LEFT=$(docker compose exec -T postgres psql -U postgres -d "$DB" -tAc \
  "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename <> 'schema_migrations'")
[ "$LEFT" = "0" ] || { echo "FAIL: $LEFT tables left after full rollback"; exit 1; }
echo "== up again"; dbmate up
echo "PASS: migrations go up, fully down, and up again"
