-- migrate:up

-- Milestone 4: research jobs, reports, sections, claims, citations, progress events, usage.
-- Everything here is tenant-owned and protected by row-level security. Child rows carry the
-- tenant and reference (report_id, tenant_id) together, so a row can't point at a report
-- of another tenant.
-- Writers: backend/ creates reports, jobs and the first event; ai/ does everything else.

CREATE TABLE research_reports (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         uuid NOT NULL REFERENCES tenants (id),
  owner_user_id     uuid NOT NULL REFERENCES users (id),
  ipo_id            uuid NOT NULL REFERENCES ipos (id),
  -- Pinned at creation: the report is reproducible from this snapshot and its evidence.
  snapshot_id       uuid NOT NULL REFERENCES ipo_snapshots (id),
  evidence_set_id   uuid REFERENCES evidence_sets (id),
  status            text NOT NULL DEFAULT 'pending' CHECK (status IN (
                      'pending', 'running', 'completed', 'completed_degraded', 'failed',
                      'rejected_excluded')),
  error             text CHECK (length(error) <= 1000),
  pipeline_version  text NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now(),
  started_at        timestamptz,
  completed_at      timestamptz,
  deleted_at        timestamptz,
  CONSTRAINT research_reports_tenant_key UNIQUE (id, tenant_id)
);
CREATE INDEX research_reports_owner_idx ON research_reports (tenant_id, owner_user_id, created_at DESC);

-- Exclusion layer L2: reports can only be created for allowed IPOs.
CREATE TRIGGER research_reports_ipo_allowed BEFORE INSERT ON research_reports
  FOR EACH ROW EXECUTE FUNCTION assert_ipo_allowed();

-- The pinned snapshot must belong to the report's IPO.
CREATE FUNCTION check_report_snapshot() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM ipo_snapshots WHERE id = NEW.snapshot_id AND ipo_id = NEW.ipo_id) THEN
    RAISE EXCEPTION 'snapshot % does not belong to ipo %', NEW.snapshot_id, NEW.ipo_id;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER research_reports_snapshot_matches BEFORE INSERT ON research_reports
  FOR EACH ROW EXECUTE FUNCTION check_report_snapshot();

-- Durable job queue (ADR-0004): workers claim with SKIP LOCKED and hold a renewable lease.
CREATE TABLE research_jobs (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id         uuid NOT NULL UNIQUE,
  tenant_id         uuid NOT NULL,
  status            text NOT NULL DEFAULT 'queued' CHECK (status IN (
                      'queued', 'running', 'succeeded', 'failed', 'rejected_excluded')),
  attempt           integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  max_attempts      integer NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
  lease_owner       text,
  lease_expires_at  timestamptz,
  next_run_at       timestamptz NOT NULL DEFAULT now(),
  last_error        text CHECK (length(last_error) <= 1000),
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (report_id, tenant_id) REFERENCES research_reports (id, tenant_id),
  CHECK ((status = 'running') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL))
);
CREATE INDEX research_jobs_claimable_idx ON research_jobs (next_run_at)
  WHERE status IN ('queued', 'running');
CREATE TRIGGER research_jobs_updated_at BEFORE UPDATE ON research_jobs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE research_sections (
  report_id       uuid NOT NULL,
  tenant_id       uuid NOT NULL,
  section         text NOT NULL CHECK (section IN ('A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J')),
  title           text NOT NULL CHECK (length(title) BETWEEN 1 AND 100),
  status          text NOT NULL CHECK (status IN ('ok', 'degraded', 'unavailable')),
  -- 'pending' until the Milestone 5 validator has checked the claims.
  validation      text NOT NULL CHECK (validation IN ('pending', 'deterministic', 'passed')),
  reason          text CHECK (length(reason) <= 500),
  missing         jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(missing) = 'array'),
  prompt_version  text,
  model           text,
  attempt         integer NOT NULL CHECK (attempt >= 1),
  started_at      timestamptz NOT NULL,
  completed_at    timestamptz NOT NULL,
  PRIMARY KEY (report_id, section),
  FOREIGN KEY (report_id, tenant_id) REFERENCES research_reports (id, tenant_id),
  -- A section is only "ok" when its claims were checked; drafts can be at most degraded.
  CONSTRAINT sections_ok_requires_validation CHECK (status <> 'ok' OR validation <> 'pending')
);

-- Brief section 13 names these evidence_claims and claim_citations.
CREATE TABLE evidence_claims (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id      uuid NOT NULL,
  tenant_id      uuid NOT NULL,
  section        text NOT NULL,
  position       integer NOT NULL CHECK (position >= 1),
  text           text NOT NULL CHECK (length(text) BETWEEN 1 AND 2000),
  claim_type     text NOT NULL CHECK (claim_type IN (
                   'business', 'financial', 'issue_detail', 'risk', 'governance', 'legal',
                   'market', 'summary', 'other')),
  status         text NOT NULL CHECK (status IN ('verified', 'unverified', 'quarantined')),
  status_reason  text CHECK (length(status_reason) <= 500),
  created_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT evidence_claims_position_key UNIQUE (report_id, section, position),
  CONSTRAINT evidence_claims_tenant_key UNIQUE (id, tenant_id),
  FOREIGN KEY (report_id, section) REFERENCES research_sections (report_id, section),
  FOREIGN KEY (report_id, tenant_id) REFERENCES research_reports (id, tenant_id)
);

CREATE TABLE claim_citations (
  claim_id     uuid NOT NULL,
  tenant_id    uuid NOT NULL,
  label        text NOT NULL CHECK (label ~ '^d[1-9][0-9]*$'),
  document_id  uuid NOT NULL REFERENCES evidence_documents (id),
  page         integer CHECK (page >= 1),
  quote        text CHECK (length(quote) <= 1000),
  PRIMARY KEY (claim_id, label),
  FOREIGN KEY (claim_id, tenant_id) REFERENCES evidence_claims (id, tenant_id)
);

-- Progress log streamed over SSE (ADR-0005). seq is gap-free per report.
CREATE TABLE research_events (
  report_id   uuid NOT NULL,
  tenant_id   uuid NOT NULL,
  seq         bigint NOT NULL CHECK (seq >= 1),
  type        text NOT NULL CHECK (type ~ '^[a-z_]+\.[a-z_]+$'),
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (report_id, seq),
  FOREIGN KEY (report_id, tenant_id) REFERENCES research_reports (id, tenant_id)
);

-- Model usage for cost and quota accounting (brief section 17).
CREATE TABLE usage_records (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id           uuid NOT NULL REFERENCES tenants (id),
  report_id           uuid,
  section             text,
  provider            text NOT NULL,
  model               text NOT NULL,
  input_tokens        integer NOT NULL CHECK (input_tokens >= 0),
  output_tokens       integer NOT NULL CHECK (output_tokens >= 0),
  latency_ms          integer NOT NULL CHECK (latency_ms >= 0),
  -- NULL when no price is configured for the model: never a guessed cost.
  estimated_cost_usd  numeric(12, 6) CHECK (estimated_cost_usd >= 0),
  outcome             text NOT NULL CHECK (outcome IN ('ok', 'invalid_output', 'timeout', 'error', 'budget')),
  created_at          timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (report_id, tenant_id) REFERENCES research_reports (id, tenant_id)
);
CREATE INDEX usage_records_tenant_idx ON usage_records (tenant_id, created_at DESC);

-- Idempotency keys (brief section 12): scoped to tenant, user, operation and target.
CREATE TABLE idempotency_keys (
  tenant_id     uuid NOT NULL REFERENCES tenants (id),
  user_id       uuid NOT NULL REFERENCES users (id),
  operation     text NOT NULL,
  key           text NOT NULL CHECK (key ~ '^[A-Za-z0-9_-]{8,128}$'),
  request_hash  text NOT NULL,
  response      jsonb NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, user_id, operation, key)
);

-- Row-level security on every table above.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['research_reports', 'research_jobs', 'research_sections',
                           'evidence_claims', 'claim_citations', 'research_events',
                           'usage_records', 'idempotency_keys'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %I ON %I USING (tenant_id = current_tenant_id())
                    WITH CHECK (tenant_id = current_tenant_id())', t || '_tenant', t);
  END LOOP;
END;
$$;

-- Workers claim jobs across tenants, so claiming can't go through RLS. This function is the
-- only cross-tenant path: it returns one claimable job (and its tenant) and leases it. The
-- worker then sets app.tenant_id and does all further reads and writes under RLS.
CREATE FUNCTION claim_research_job(p_worker text, p_lease_seconds integer)
RETURNS TABLE (job_id uuid, report_id uuid, tenant_id uuid, attempt integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  RETURN QUERY
  WITH next AS (
    SELECT j.id FROM research_jobs j
     WHERE j.attempt < j.max_attempts
       AND j.next_run_at <= now()
       AND (j.status = 'queued' OR (j.status = 'running' AND j.lease_expires_at < now()))
     ORDER BY j.next_run_at
     LIMIT 1
     FOR UPDATE SKIP LOCKED
  )
  UPDATE research_jobs j SET
    status = 'running', lease_owner = p_worker,
    lease_expires_at = now() + make_interval(secs => p_lease_seconds),
    attempt = j.attempt + 1
    FROM next WHERE j.id = next.id
  RETURNING j.id, j.report_id, j.tenant_id, j.attempt;
END;
$$;
REVOKE ALL ON FUNCTION claim_research_job(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_research_job(text, integer) TO app_ai;

-- Jobs whose lease expired after the last attempt: fail them so they don't stay "running".
CREATE FUNCTION fail_exhausted_research_jobs() RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE n integer;
BEGIN
  UPDATE research_jobs SET status = 'failed', lease_owner = NULL, lease_expires_at = NULL,
         last_error = coalesce(last_error, 'lease expired after the last attempt')
   WHERE status = 'running' AND lease_expires_at < now() AND attempt >= max_attempts;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$$;
REVOKE ALL ON FUNCTION fail_exhausted_research_jobs() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fail_exhausted_research_jobs() TO app_ai;

-- Grants follow write ownership (architecture section 3).
GRANT SELECT, INSERT ON research_reports, research_jobs, idempotency_keys TO app_api;
GRANT UPDATE (deleted_at) ON research_reports TO app_api;
GRANT SELECT ON research_sections, evidence_claims, claim_citations, usage_records TO app_api;
GRANT SELECT, INSERT ON research_events TO app_api;  -- the API writes the first event
-- The evidence endpoint lists the report's labelled documents (RLS still applies).
GRANT SELECT ON evidence_sets, evidence_set_items TO app_api;

GRANT SELECT ON research_reports, research_jobs TO app_ai;
GRANT UPDATE (status, error, evidence_set_id, started_at, completed_at) ON research_reports TO app_ai;
GRANT UPDATE (status, lease_owner, lease_expires_at, next_run_at, last_error) ON research_jobs TO app_ai;
GRANT SELECT, INSERT ON research_sections, evidence_claims, claim_citations, research_events,
                        usage_records TO app_ai;
-- The worker needs the IPO name for exclusion re-checks and the snapshot's evidence set.
-- (app_ai already reads ipos and ipo_snapshots from Milestone 2.)

-- migrate:down

REVOKE SELECT ON evidence_sets, evidence_set_items FROM app_api;
DROP FUNCTION fail_exhausted_research_jobs();
DROP FUNCTION claim_research_job(text, integer);
DROP TABLE idempotency_keys;
DROP TABLE usage_records;
DROP TABLE research_events;
DROP TABLE claim_citations;
DROP TABLE evidence_claims;
DROP TABLE research_sections;
DROP TABLE research_jobs;
DROP TABLE research_reports;
DROP FUNCTION check_report_snapshot();
