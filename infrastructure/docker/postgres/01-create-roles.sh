#!/bin/sh
# Runs once, when the Postgres data volume is first initialised (docker-entrypoint-initdb.d).
# Creates least-privilege login roles (ADR-0011, threat model T-11):
#   app_migrate — owns the database and schema; used only by dbmate
#   app_api     — runtime role for backend/ (no DDL, no BYPASSRLS)
#   app_ai      — runtime role for ai/      (no DDL, no BYPASSRLS)
# In production these roles are created by Terraform, not by this script.
set -eu

: "${APP_MIGRATE_DB_PASSWORD:?must be set}"
: "${APP_API_DB_PASSWORD:?must be set}"
: "${APP_AI_DB_PASSWORD:?must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v migrate_pw="$APP_MIGRATE_DB_PASSWORD" \
  -v api_pw="$APP_API_DB_PASSWORD" \
  -v ai_pw="$APP_AI_DB_PASSWORD" <<'SQL'
CREATE ROLE app_migrate LOGIN PASSWORD :'migrate_pw';
CREATE ROLE app_api     LOGIN PASSWORD :'api_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE app_ai      LOGIN PASSWORD :'ai_pw'  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

CREATE DATABASE arthalens OWNER app_migrate;
REVOKE ALL ON DATABASE arthalens FROM PUBLIC;
GRANT CONNECT ON DATABASE arthalens TO app_api, app_ai;
SQL

# Postgres 15+ makes the public schema owned by pg_database_owner (= app_migrate here)
# and denies CREATE to PUBLIC, so runtime roles can't create objects.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname arthalens <<'SQL'
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO app_api, app_ai;
SQL
