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

echo "IPO ingestion (Milestone 2, synthetic fixtures)"
RUN=$(docker compose exec -T ai python -m arthalens_ai.ingestion.cli discover 2>/dev/null | tail -n 1)
js() { printf '%s' "$1" | python3 -c "import json,sys; d=json.load(sys.stdin); print($2)" 2>/dev/null; }
check "fixture ingestion run succeeds" "$(js "$RUN" "d['status']")" succeeded
check "two excluded/look-alike entities quarantined" "$(js "$RUN" "d['quarantined']")" 2
check "no IPO name containing 'jio' stored" \
  "$(psql_as app_migrate "$APP_MIGRATE_DB_PASSWORD" "SELECT count(*) FROM ipos WHERE replace(normalized_name,' ','') ~ 'jio|j1o'")" 0
check "Jio entity recorded in quarantine" \
  "$(psql_as app_migrate "$APP_MIGRATE_DB_PASSWORD" "SELECT count(*) FROM quarantined_entities WHERE raw_name LIKE 'Jio Platforms%'")" 1

API=http://127.0.0.1:3000/api/v1/ipos
LIST=$(body "$API")
check "list returns the 6 synthetic IPOs" "$(js "$LIST" "len(d['items'])")" 6
check "every verified field has source, quote and check time" "$(js "$LIST" "all(f['source'] and f['quote'] and f['checked_at'] for i in d['items'] for f in i['fields'].values() if f['status']=='verified')")" True
check "no value is shown for conflict/unavailable fields" "$(js "$LIST" "all(f['value'] is None for i in d['items'] for f in i['fields'].values() if f['status'] in ('conflict','unavailable'))")" True
check "every item is marked synthetic" "$(js "$LIST" "all(i['is_synthetic'] for i in d['items'])")" True
check "status=open → only Alpha" "$(js "$(body "$API?status=open")" "','.join(i['company_name'] for i in d['items'])")" "Synthetic Alpha Foods Limited"
check "issue_type=sme → only Gamma" "$(js "$(body "$API?issue_type=sme")" "','.join(i['company_name'] for i in d['items'])")" "Synthetic Gamma Textiles Limited"
P1=$(body "$API?limit=4")
CURSOR=$(js "$P1" "d['next_cursor']")
check "pagination: page 2 holds the remaining 2" "$(js "$(body "$API?limit=4&cursor=$CURSOR")" "len(d['items'])")" 2
for term in jio "Jio%20Platforms" "J1O" "reliance%20jio"; do
  R=$(body "$API?q=$term")
  check "search '$term' → 0 items + ENTITY_EXCLUDED notice" "$(js "$R" "str(len(d['items'])) + ' ' + d['notice']['code']")" "0 ENTITY_EXCLUDED"
done
check "search 'alpha' → 1 item" "$(js "$(body "$API?q=alpha")" "len(d['items'])")" 1

EPS=$(js "$LIST" "[i['id'] for i in d['items'] if 'Epsilon' in i['company_name']][0]")
DET=$(body "$API/$EPS")
check "detail: Epsilon lot size is a conflict" "$(js "$DET" "d['fields']['lot_size']['status']")" conflict
# 2 open + 2 close + 2 lot size + 2 price bands x (low, high) = 10
check "detail: every source observation is listed" "$(js "$DET" "len(d['observations'])")" 10

WID=00000000-0000-4000-8000-0000000000dd
psql_as app_migrate "$APP_MIGRATE_DB_PASSWORD" "INSERT INTO ipos (id, slug, company_name, normalized_name, policy_version, exclusion_status) VALUES ('$WID','smoke-withdrawn','Smoke Withdrawn Entity','smoke withdrawn entity',1,'withdrawn_by_policy') ON CONFLICT (id) DO NOTHING" >/dev/null
check "direct access to a policy-withdrawn IPO → 403" "$(code "$API/$WID")" 403
check "403 carries code ENTITY_EXCLUDED" "$(js "$(body "$API/$WID")" "d['code']")" ENTITY_EXCLUDED
check "blocked access is audited" \
  "$(psql_as app_migrate "$APP_MIGRATE_DB_PASSWORD" "SELECT (count(*) > 0)::text FROM audit_events WHERE action='policy.exclusion_blocked' AND target_id='$WID'")" true
check "withdrawn IPO is absent from the list" "$(js "$(body "$API")" "'$WID' in [i['id'] for i in d['items']]")" False
psql_as app_migrate "$APP_MIGRATE_DB_PASSWORD" "DELETE FROM audit_events WHERE target_id='$WID'; DELETE FROM ipos WHERE id='$WID'" >/dev/null
check "unknown IPO id → 404" "$(code "$API/00000000-0000-4000-8000-000000000999")" 404
check "IPO list through the frontend proxy → 200" "$(code http://127.0.0.1:8080/api/v1/ipos)" 200

echo
echo "Smoke test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
