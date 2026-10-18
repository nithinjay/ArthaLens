-- migrate:up

-- Shared helper: keep updated_at current on every UPDATE.
CREATE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- Session context for row-level security (ADR-0011).
-- The API runs `SET LOCAL app.tenant_id = '...'` / `app.user_id` inside each transaction.
-- These helpers return NULL when unset, so policies fail closed (NULL = x is never true).
CREATE FUNCTION current_tenant_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.tenant_id', true), '')::uuid
$$;

CREATE FUNCTION current_app_user_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.user_id', true), '')::uuid
$$;

GRANT EXECUTE ON FUNCTION current_tenant_id(), current_app_user_id() TO app_api, app_ai;

-- migrate:down

DROP FUNCTION current_app_user_id();
DROP FUNCTION current_tenant_id();
DROP FUNCTION set_updated_at();
