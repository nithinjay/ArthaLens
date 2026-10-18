#!/bin/sh
# End-to-end smoke test for the running local stack (Milestone 1 acceptance criteria).
# Prerequisite: docker compose up --build   (in another terminal, or with -d)
set -u

cd "$(dirname "$0")/.."
[ -f .env ] || { echo "No .env — run: pnpm env:init"; exit 1; }
set -a; . ./.env; set +a

PASS=0; FAIL=0
pass() { PASS=$((PASS + 1)); printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; }
check() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (expected $3, got $2)"; fi; }
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$@"; }
body() { curl -s --max-time 5 "$@"; }
psql_as() { # role, password, sql
  docker compose exec -T -e PGPASSWORD="$2" postgres \
    psql -h 127.0.0.1 -U "$1" -d arthalens -v ON_ERROR_STOP=1 -tAc "$3" 2>&1
}

echo "AI service"
check "ai /healthz → 200" "$(code http://127.0.0.1:8000/healthz)" 200
check "ai /readyz → 200 (database reachable)" "$(code http://127.0.0.1:8000/readyz)" 200
check "ai /internal/v1/health without token → 401" "$(code http://127.0.0.1:8000/internal/v1/health)" 401
check "ai /internal/v1/health with wrong token → 401" \
  "$(code -H 'Authorization: Bearer wrong-token' http://127.0.0.1:8000/internal/v1/health)" 401
check "ai /internal/v1/health with service token → 200" \
  "$(code -H "Authorization: Bearer $AI_SERVICE_TOKEN" http://127.0.0.1:8000/internal/v1/health)" 200

echo "Backend"
check "backend /healthz → 200" "$(code http://127.0.0.1:3000/healthz)" 200
READY=$(body http://127.0.0.1:3000/readyz)
json_get() { printf '%s' "$READY" | python3 -c "import json,sys; d=json.load(sys.stdin); print($1)" 2>/dev/null; }
check "backend /readyz overall status" "$(json_get "d['status']")" ok
check "backend → database check" "$(json_get "d['checks']['database']['status']")" ok
check "backend → ai internal call (authenticated)" "$(json_get "d['checks']['ai']['status']")" ok
check "backend /api/v1/openapi.json → 200" "$(code http://127.0.0.1:3000/api/v1/openapi.json)" 200
check "backend unknown route → 404" "$(code http://127.0.0.1:3000/api/v1/nope)" 404

echo "Frontend (nginx)"
check "frontend / → 200" "$(code http://127.0.0.1:8080/)" 200
check "frontend proxies /api/v1/health → 200" "$(code http://127.0.0.1:8080/api/v1/health)" 200
case "$(curl -sI --max-time 5 http://127.0.0.1:8080/)" in
  *"Content-Security-Policy"*) pass "frontend sends a Content-Security-Policy" ;;
  *) fail "frontend sends a Content-Security-Policy" ;;
esac

echo "Database privileges"
case "$(psql_as app_api "$APP_API_DB_PASSWORD" 'CREATE TABLE smoke_should_fail (id int)')" in
  *"permission denied"*) pass "app_api cannot create tables" ;;
  *) fail "app_api cannot create tables" ;;
esac
case "$(psql_as app_ai "$APP_AI_DB_PASSWORD" 'SELECT count(*) FROM users')" in
  *"permission denied"*) pass "app_ai cannot read users (not its table)" ;;
  *) fail "app_ai cannot read users (not its table)" ;;
esac
case "$(psql_as app_api "$APP_API_DB_PASSWORD" 'DELETE FROM audit_events')" in
  *"permission denied"*) pass "app_api cannot delete audit events (append-only)" ;;
  *) fail "app_api cannot delete audit events (append-only)" ;;
esac

echo "Row-level security"
# Two synthetic tenants with one member each; app_api scoped to tenant A must not see B.
SEED="
BEGIN;
DELETE FROM memberships WHERE tenant_id IN ('00000000-0000-4000-8000-00000000000a','00000000-0000-4000-8000-00000000000b');
DELETE FROM tenants WHERE id IN ('00000000-0000-4000-8000-00000000000a','00000000-0000-4000-8000-00000000000b');
DELETE FROM users WHERE email IN ('smoke-a@example.test','smoke-b@example.test');
INSERT INTO tenants (id, name, kind) VALUES
  ('00000000-0000-4000-8000-00000000000a','SYNTHETIC tenant A','personal'),
  ('00000000-0000-4000-8000-00000000000b','SYNTHETIC tenant B','personal');
INSERT INTO users (id, email) VALUES
  ('00000000-0000-4000-8000-0000000000a1','smoke-a@example.test'),
  ('00000000-0000-4000-8000-0000000000b1','smoke-b@example.test');
INSERT INTO memberships (tenant_id, user_id, role_id)
  SELECT t, u, (SELECT id FROM roles WHERE key='owner') FROM (VALUES
    ('00000000-0000-4000-8000-00000000000a'::uuid,'00000000-0000-4000-8000-0000000000a1'::uuid),
    ('00000000-0000-4000-8000-00000000000b'::uuid,'00000000-0000-4000-8000-0000000000b1'::uuid)) v(t,u);
COMMIT;"
SEED_OUT=$(psql_as app_migrate "$APP_MIGRATE_DB_PASSWORD" "$SEED")
case "$SEED_OUT" in *ERROR*) fail "seed synthetic tenants ($SEED_OUT)" ;; esac
check "no tenant set → 0 memberships visible" \
  "$(psql_as app_api "$APP_API_DB_PASSWORD" 'SELECT count(*) FROM memberships')" 0
check "tenant A set → sees only its own membership" \
  "$(psql_as app_api "$APP_API_DB_PASSWORD" "SELECT set_config('app.tenant_id','00000000-0000-4000-8000-00000000000a',false); SELECT count(*) FROM memberships" | tail -n 1)" 1
check "tenant A set → tenant B's row not visible by id" \
  "$(psql_as app_api "$APP_API_DB_PASSWORD" "SELECT set_config('app.tenant_id','00000000-0000-4000-8000-00000000000a',false); SELECT count(*) FROM tenants WHERE id='00000000-0000-4000-8000-00000000000b'" | tail -n 1)" 0
psql_as app_migrate "$APP_MIGRATE_DB_PASSWORD" "
DELETE FROM memberships WHERE tenant_id IN ('00000000-0000-4000-8000-00000000000a','00000000-0000-4000-8000-00000000000b');
DELETE FROM tenants WHERE id IN ('00000000-0000-4000-8000-00000000000a','00000000-0000-4000-8000-00000000000b');
DELETE FROM users WHERE email IN ('smoke-a@example.test','smoke-b@example.test');" >/dev/null

echo
echo "Smoke test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
