# ADR-0011: Tenant isolation with tenant_id + Postgres RLS

**Status:** Accepted · **Date:** 2026-10-17

## Decision
- Every tenant-owned table has `tenant_id NOT NULL` (and `owner_user_id` where per-user). Composite indexes lead with `tenant_id`.
- Individual users get a personal tenant on sign-up, so the model works the same for individuals and enterprises.
- **Application layer:** repositories require a `TenantContext` from the session, so there is no unscoped query API.
- **Database layer:** RLS policies `USING (tenant_id = current_setting('app.tenant_id')::uuid)`. The API sets `SET LOCAL app.tenant_id` at the start of every transaction. Runtime roles do not have `BYPASSRLS`.
- **Shared public data** (`ipos`, `ipo_snapshots`, public `evidence_documents`, `stocks`) has no tenant and is read-only to `app_api`.
- **Tenant-private evidence** (future user uploads) carries `visibility='tenant'` and is filtered before retrieval returns results (Stage 4).
- **Required tests:** User A (tenant A) cannot read, list, update or delete User B's reports, evidence views, holdings, watchlists, wishlists, alerts or settings, by ID manipulation or by list filters. These are tested at both the API and DB levels (the latter by querying with RLS on and a wrong `app.tenant_id`).

## Consequences
- + Two independent layers; a missed `WHERE` clause is caught by RLS.
- − RLS needs care with connection pooling (`SET LOCAL` inside transactions only) and migrations (run as owner role).
