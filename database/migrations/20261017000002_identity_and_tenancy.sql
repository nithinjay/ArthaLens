-- migrate:up

-- Identity and tenancy foundation (brief §13, ADR-0010, ADR-0011).
-- Research, evidence and stock tables arrive in the milestones that use them.

CREATE TABLE tenants (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
  -- Individuals get a personal tenant, so one model serves individuals and organisations.
  kind        text NOT NULL CHECK (kind IN ('personal', 'organization')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email         text NOT NULL CHECK (email = lower(email) AND length(email) <= 320),
  display_name  text CHECK (length(display_name) <= 200),
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT users_email_key UNIQUE (email)
);

-- RBAC reference data: global role and permission definitions.
CREATE TABLE roles (
  id           smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  key          text NOT NULL UNIQUE,
  description  text NOT NULL
);

CREATE TABLE permissions (
  id           smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  key          text NOT NULL UNIQUE,
  description  text NOT NULL
);

CREATE TABLE role_permissions (
  role_id        smallint NOT NULL REFERENCES roles (id) ON DELETE CASCADE,
  permission_id  smallint NOT NULL REFERENCES permissions (id) ON DELETE CASCADE,
  PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE memberships (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
  user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  role_id     smallint NOT NULL REFERENCES roles (id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT memberships_tenant_user_key UNIQUE (tenant_id, user_id)
);
CREATE INDEX memberships_user_id_idx ON memberships (user_id);

-- Append-only audit trail (threat model T-08). tenant_id is NULL for system events.
CREATE TABLE audit_events (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id      uuid REFERENCES tenants (id) ON DELETE SET NULL,
  actor_user_id  uuid REFERENCES users (id) ON DELETE SET NULL,
  action         text NOT NULL CHECK (action ~ '^[a-z_]+(\.[a-z_]+)+$'),
  target_type    text,
  target_id      text,
  request_id     text,
  metadata       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_events_tenant_created_idx ON audit_events (tenant_id, created_at DESC);

CREATE TRIGGER tenants_updated_at BEFORE UPDATE ON tenants
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER users_updated_at BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER memberships_updated_at BEFORE UPDATE ON memberships
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Row-level security on tenant-owned tables (second layer behind application checks).
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;

-- A user sees tenants they belong to.
CREATE POLICY tenants_member_access ON tenants
  USING (id = current_tenant_id()
         OR id IN (SELECT tenant_id FROM memberships WHERE user_id = current_app_user_id()));

-- Memberships: within the current tenant, or the user's own rows (needed at sign-in,
-- before a tenant is chosen).
CREATE POLICY memberships_tenant_or_self ON memberships
  USING (tenant_id = current_tenant_id() OR user_id = current_app_user_id());

CREATE POLICY audit_events_tenant_read ON audit_events
  FOR SELECT USING (tenant_id = current_tenant_id());
CREATE POLICY audit_events_tenant_insert ON audit_events
  FOR INSERT WITH CHECK (tenant_id IS NULL OR tenant_id = current_tenant_id());

-- Grants follow write ownership (architecture §3): backend/ owns identity and tenancy.
GRANT SELECT, INSERT, UPDATE ON tenants, users, memberships TO app_api;
GRANT SELECT ON roles, permissions, role_permissions TO app_api;
GRANT SELECT, INSERT ON audit_events TO app_api;   -- no UPDATE/DELETE: append-only

-- Reference data. Permissions grow with each milestone.
INSERT INTO roles (key, description) VALUES
  ('owner',  'Full control of the tenant, including members and settings'),
  ('member', 'Can run research and manage their own portfolio data'),
  ('viewer', 'Read-only access to the tenant''s research');

INSERT INTO permissions (key, description) VALUES
  ('research:create',   'Start a research job'),
  ('research:read',     'Read research reports and evidence'),
  ('research:delete',   'Delete research reports'),
  ('portfolio:read',    'Read holdings, watchlist and wishlist'),
  ('portfolio:write',   'Change holdings, watchlist and wishlist'),
  ('tenant:manage',     'Manage tenant members and settings');

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON
  (r.key = 'owner')
  OR (r.key = 'member' AND p.key IN ('research:create', 'research:read', 'research:delete',
                                     'portfolio:read', 'portfolio:write'))
  OR (r.key = 'viewer' AND p.key IN ('research:read'));

-- migrate:down

-- This policy's subquery depends on memberships, so it must go before that table.
DROP POLICY tenants_member_access ON tenants;
DROP TABLE audit_events;
DROP TABLE memberships;
DROP TABLE role_permissions;
DROP TABLE permissions;
DROP TABLE roles;
DROP TABLE users;
DROP TABLE tenants;
