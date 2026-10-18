#!/bin/sh
# Create the local development tenant and user that AUTH_MODE=dev signs in as (until
# Milestone 8). Idempotent. Never used in production: the backend refuses AUTH_MODE=dev there.
set -eu
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
TENANT=${DEV_TENANT_ID:-00000000-0000-4000-8000-000000000d01}
USER=${DEV_USER_ID:-00000000-0000-4000-8000-000000000d02}
docker compose exec -T -e PGPASSWORD="$APP_MIGRATE_DB_PASSWORD" postgres \
  psql -h 127.0.0.1 -U app_migrate -d arthalens -v ON_ERROR_STOP=1 -q <<SQL
INSERT INTO tenants (id, name, kind) VALUES ('$TENANT', 'Local development (SYNTHETIC)', 'personal')
  ON CONFLICT (id) DO NOTHING;
INSERT INTO users (id, email, display_name) VALUES ('$USER', 'dev@arthalens.test', 'Local developer')
  ON CONFLICT (id) DO NOTHING;
INSERT INTO memberships (tenant_id, user_id, role_id)
  SELECT '$TENANT', '$USER', id FROM roles WHERE key = 'owner'
  ON CONFLICT (tenant_id, user_id) DO NOTHING;
SQL
echo "dev tenant $TENANT and user $USER are ready"
