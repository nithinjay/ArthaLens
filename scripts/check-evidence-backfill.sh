#!/bin/sh
# Check migration 20261018000002 against data shaped like Milestone 2 (review findings on PR #3):
#   1. one URL with two different contents -> versions 1 and 2, v2 supersedes v1
#   2. a non-canonical URL -> source_key equals the Python canonical form
#   3. a 9,000-character document -> split into passages, no text lost
#   6. rollback refuses data it can't represent (tenant evidence) instead of deleting it
# Uses a throwaway database; your local data is never touched.
set -eu
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

DB=arthalens_backfill
URL="postgres://app_migrate:${APP_MIGRATE_DB_PASSWORD}@postgres:5432/${DB}?sslmode=disable"
as_super() { docker compose exec -T postgres psql -U postgres -d "$1" -v ON_ERROR_STOP=1 -qtAc "$2"; }
q() { as_super "$DB" "$1"; }
# Run dbmate against only the migrations up to and including $1 (each run is a fresh
# container, so the subset directory is rebuilt every time).
dbmate_upto() {
  docker compose run --rm --no-deps -e DATABASE_URL="$URL" --entrypoint sh migrate -c \
    "mkdir -p /tmp/m && for f in /db/migrations/*.sql; do b=\$(basename \"\$f\"); [ \"\$b\" \\< \"${1}_~\" ] && cp \"\$f\" /tmp/m/; done; dbmate --migrations-dir /tmp/m --no-dump-schema $2" >/dev/null
}
M2_LAST=20261018000001     # last Milestone 2 migration
LEDGER=20261018000002      # the evidence ledger migration under test
cleanup() { as_super postgres "DROP DATABASE IF EXISTS $DB WITH (FORCE)" >/dev/null 2>&1 || true; }
trap cleanup EXIT
FAIL=0
check() { if [ "$2" = "$3" ]; then echo "  PASS $1"; else echo "  FAIL $1 (expected $3, got $2)"; FAIL=1; fi; }

docker compose build -q migrate
cleanup
as_super postgres "CREATE DATABASE $DB OWNER app_migrate"
q "REVOKE ALL ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO app_api, app_ai;"

# Migrate only up to Milestone 2.
dbmate_upto "$M2_LAST" up

LONG=$(python3 -c "print('SYNTHETIC ' + 'x' * 8990)")
q "INSERT INTO evidence_documents (content_sha256, canonical_url, title, publisher, retrieved_at,
     source_type, authority, retrieval_method, provider, mime_type, byte_size, text_content,
     display_rights, is_synthetic, created_at)
   VALUES
   (repeat('a', 64), 'https://X.test/notice?b=2&a=1&utm_source=m', 'v1', 'p', '2026-10-01', 'exchange_notice',
    'official_exchange', 'mock_fixture', 't', 'text/plain', 1, 'first', 'excerpt', true, '2026-10-01'),
   (repeat('b', 64), 'https://X.test/notice?b=2&a=1&utm_source=m', 'v2', 'p', '2026-10-05', 'exchange_notice',
    'official_exchange', 'mock_fixture', 't', 'text/plain', 1, 'second', 'excerpt', true, '2026-10-05'),
   (repeat('c', 64), 'https://x.test/long', 'long', 'p', '2026-10-02', 'offer_document',
    'issuer_filing', 'mock_fixture', 't', 'text/plain', 9000, '$LONG', 'excerpt', true, '2026-10-02')"

echo "== migrate Milestone 2 data to the evidence ledger"
dbmate_upto "$LEDGER" up
EXPECTED_KEY=$(cd ai && uv run python -c "from arthalens_ai.evidence.canonical import source_key; print(source_key('https://X.test/notice?b=2&a=1&utm_source=m'))")
check "same URL, two contents -> versions 1,2" "$(q "SELECT string_agg(version::text, ',' ORDER BY version) FROM evidence_documents WHERE title IN ('v1','v2')")" "1,2"
check "v2 supersedes v1" "$(q "SELECT (d2.supersedes_id = d1.id)::text FROM evidence_documents d1, evidence_documents d2 WHERE d1.title='v1' AND d2.title='v2'")" "true"
check "backfilled key = Python canonical key" "$(q "SELECT DISTINCT source_key FROM evidence_documents WHERE title='v1'")" "$EXPECTED_KEY"
check "9,000 chars -> 3 passages" "$(q "SELECT count(*) FROM evidence_passages WHERE content_sha256 = repeat('c', 64)")" "3"
check "no text lost" "$(q "SELECT sum(length(text)) FROM evidence_passages WHERE content_sha256 = repeat('c', 64)")" "9000"

echo "== rollback refuses tenant-private evidence"
TENANT=$(q "INSERT INTO tenants (name, kind) VALUES ('SYNTHETIC backfill tenant', 'personal') RETURNING id")
q "INSERT INTO evidence_documents (content_sha256, canonical_url, source_key, version, title, publisher,
     retrieved_at, source_type, authority, retrieval_method, provider, display_rights, visibility, tenant_id)
   VALUES (repeat('a', 64), 'https://x.test/private', 'upload:$TENANT:' || repeat('a', 64), 1, 'private', 'p',
     now(), 'other', 'unofficial', 'upload', 't', 'excerpt', 'tenant', '$TENANT')"
if dbmate_upto "$LEDGER" rollback 2>/dev/null; then
  echo "  FAIL rollback with tenant evidence should have been refused"; FAIL=1
else
  check "rollback refused; tenant evidence still private" "$(q "SELECT visibility FROM evidence_documents WHERE title='private'")" "tenant"
fi

echo "== rollback succeeds when the data fits the old shape"
q "BEGIN; SET LOCAL arthalens.evidence_retention = 'on'; DELETE FROM evidence_documents WHERE title = 'private'; COMMIT;"
dbmate_upto "$LEDGER" rollback
check "text restored after rollback" "$(q "SELECT length(text_content) FROM evidence_documents WHERE canonical_url = 'https://x.test/long'")" "9000"

[ "$FAIL" -eq 0 ] && echo "PASS: evidence backfill" || { echo "FAIL: evidence backfill"; exit 1; }
