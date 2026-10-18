-- migrate:up

-- Milestone 2: IPO entity model, versioned snapshots with per-field provenance,
-- minimal evidence documents, ingestion runs and the exclusion quarantine.
-- Write owner for every table here: ai/ (app_ai). backend/ (app_api) reads only.

CREATE TABLE ingestion_runs (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider     text NOT NULL,
  status       text NOT NULL DEFAULT 'running'
               CHECK (status IN ('running', 'succeeded', 'partial', 'failed')),
  counts       jsonb NOT NULL DEFAULT '{}'::jsonb,
  error        text CHECK (length(error) <= 2000),
  started_at   timestamptz NOT NULL DEFAULT now(),
  finished_at  timestamptz,
  CHECK ((status = 'running') = (finished_at IS NULL))
);

-- Retrieved source documents. Append-only. Milestone 3 adds passages, page anchors and
-- report-scoped ids (d1, d2, ...); this is the minimum needed to cite IPO fields.
CREATE TABLE evidence_documents (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content_sha256    text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  canonical_url     text NOT NULL CHECK (canonical_url ~ '^https?://' AND length(canonical_url) <= 2000),
  title             text NOT NULL CHECK (length(title) BETWEEN 1 AND 500),
  publisher         text NOT NULL CHECK (length(publisher) BETWEEN 1 AND 300),
  published_at      date,
  retrieved_at      timestamptz NOT NULL,
  source_type       text NOT NULL CHECK (source_type IN (
                      'exchange_notice', 'offer_document', 'regulator_publication',
                      'registrar_notice', 'issuer_website', 'news', 'other')),
  authority         text NOT NULL CHECK (authority IN (
                      'official_exchange', 'official_regulator', 'issuer_filing',
                      'official_registrar', 'licensed_market_data', 'credible_news',
                      'unofficial')),
  retrieval_method  text NOT NULL CHECK (retrieval_method IN ('mock_fixture', 'manual_import', 'live_fetch')),
  provider          text NOT NULL,
  mime_type         text NOT NULL,
  byte_size         bigint NOT NULL CHECK (byte_size >= 0),
  -- Extracted text, kept privately for quote verification. Never returned by the API:
  -- app_api has no SELECT on this column (see grants below).
  text_content      text NOT NULL,
  -- What the API may show. SEBI material is linked, not republished (ADR-0015).
  display_rights    text NOT NULL CHECK (display_rights IN ('full_text', 'excerpt', 'metadata_only')),
  is_synthetic      boolean NOT NULL DEFAULT false,
  created_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT evidence_documents_content_url_key UNIQUE (content_sha256, canonical_url)
);

CREATE TABLE ipos (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug                 text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  company_name         text NOT NULL CHECK (length(company_name) BETWEEN 1 AND 300),
  normalized_name      text NOT NULL UNIQUE,
  exclusion_status     text NOT NULL DEFAULT 'allowed'
                       CHECK (exclusion_status IN ('allowed', 'withdrawn_by_policy')),
  policy_version       integer NOT NULL CHECK (policy_version >= 1),
  current_snapshot_id  uuid,
  is_synthetic         boolean NOT NULL DEFAULT false,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  -- Exclusion layer L2 backstop (ADR-0008). Coarse on purpose: the real matcher runs in
  -- ai/ before insert. This only guarantees that a name containing "jio" can never be stored,
  -- even if the application layer is bypassed or buggy.
  CONSTRAINT ipos_exclusion_backstop CHECK (
    regexp_replace(lower(normalize(company_name, NFKC)), '[^a-z0-9]', '', 'g') !~ 'jio'
    AND replace(normalized_name, ' ', '') !~ 'jio'
  )
);

CREATE TRIGGER ipos_updated_at BEFORE UPDATE ON ipos
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Immutable, versioned view of an IPO at a point in time. Research reports (M4) pin one.
CREATE TABLE ipo_snapshots (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ipo_id               uuid NOT NULL REFERENCES ipos (id) ON DELETE RESTRICT,
  version              integer NOT NULL CHECK (version >= 1),
  derived_status       text NOT NULL CHECK (derived_status IN (
                         'upcoming', 'open', 'closed', 'allotment', 'listed',
                         'withdrawn', 'postponed', 'unverified')),
  -- The IST calendar date the status was derived for. Status is never extrapolated.
  status_as_of         date NOT NULL,
  content_fingerprint  text NOT NULL CHECK (content_fingerprint ~ '^[0-9a-f]{64}$'),
  ingestion_run_id     uuid REFERENCES ingestion_runs (id),
  created_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ipo_snapshots_ipo_version_key UNIQUE (ipo_id, version)
);

ALTER TABLE ipos ADD CONSTRAINT ipos_current_snapshot_fkey
  FOREIGN KEY (current_snapshot_id) REFERENCES ipo_snapshots (id);

-- One resolved value per field per snapshot, with its provenance.
CREATE TABLE ipo_snapshot_fields (
  snapshot_id     uuid NOT NULL REFERENCES ipo_snapshots (id) ON DELETE CASCADE,
  field           text NOT NULL CHECK (field IN (
                    'open_date', 'close_date', 'listing_date', 'listing_date_basis',
                    'price_band_low', 'price_band_high', 'lot_size',
                    'issue_size', 'fresh_issue_size', 'ofs_size',
                    'exchanges', 'issue_type', 'official_status')),
  value           jsonb,
  status          text NOT NULL CHECK (status IN ('verified', 'unverified', 'conflict', 'unavailable')),
  evidence_id     uuid REFERENCES evidence_documents (id),
  evidence_quote  text CHECK (length(evidence_quote) <= 1000),
  checked_at      timestamptz,
  note            text CHECK (length(note) <= 1000),
  PRIMARY KEY (snapshot_id, field),
  -- A field is "verified" only with a value, a source document, a verbatim quote and a time.
  CONSTRAINT verified_requires_provenance CHECK (
    status <> 'verified'
    OR (value IS NOT NULL AND evidence_id IS NOT NULL AND evidence_quote IS NOT NULL
        AND checked_at IS NOT NULL)),
  -- Never show a value we couldn't establish.
  CONSTRAINT no_value_when_unresolved CHECK (status NOT IN ('conflict', 'unavailable') OR value IS NULL)
);

-- Every source observation behind a snapshot, including the ones that lost or disagreed,
-- so discrepancies can be shown with their dates (source-provider strategy §3).
CREATE TABLE ipo_field_observations (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  snapshot_id     uuid NOT NULL REFERENCES ipo_snapshots (id) ON DELETE CASCADE,
  field           text NOT NULL,
  value           jsonb,
  raw_value       text NOT NULL CHECK (length(raw_value) <= 1000),
  evidence_id     uuid NOT NULL REFERENCES evidence_documents (id),
  evidence_quote  text NOT NULL CHECK (length(evidence_quote) <= 1000),
  quote_verified  boolean NOT NULL,
  parse_error     text CHECK (length(parse_error) <= 500),
  observed_at     timestamptz NOT NULL
);
CREATE INDEX ipo_field_observations_snapshot_idx ON ipo_field_observations (snapshot_id, field);

-- Entities blocked by the exclusion policy. Only the name and source URL are kept:
-- no documents, fields or research are ever stored for them.
CREATE TABLE quarantined_entities (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_kind       text NOT NULL CHECK (entity_kind IN ('ipo', 'stock')),
  raw_name          text NOT NULL CHECK (length(raw_name) <= 300),
  normalized_name   text NOT NULL,
  decision          text NOT NULL CHECK (decision IN ('excluded', 'quarantined')),
  reason            text NOT NULL CHECK (reason IN ('identifier', 'token', 'alias', 'embedded', 'confusable')),
  rule_id           text NOT NULL,
  policy_version    integer NOT NULL,
  provider          text NOT NULL,
  source_url        text CHECK (length(source_url) <= 2000),
  last_ingestion_run_id uuid REFERENCES ingestion_runs (id),
  first_seen_at     timestamptz NOT NULL DEFAULT now(),
  last_seen_at      timestamptz NOT NULL DEFAULT now(),
  seen_count        integer NOT NULL DEFAULT 1 CHECK (seen_count >= 1),
  CONSTRAINT quarantined_entities_key UNIQUE (entity_kind, normalized_name, rule_id)
);

-- Exclusion layer L2 (ADR-0008): any row that depends on an IPO must reference an allowed one.
-- Attached to ipo_snapshots now; research_jobs, calculation scenarios and notification jobs
-- attach the same function when they are created.
CREATE FUNCTION assert_ipo_allowed() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  st text;
BEGIN
  SELECT exclusion_status INTO st FROM ipos WHERE id = NEW.ipo_id;
  IF st IS DISTINCT FROM 'allowed' THEN
    RAISE EXCEPTION 'ENTITY_EXCLUDED: ipo % is not allowed (status %)', NEW.ipo_id, coalesce(st, 'missing')
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER ipo_snapshots_ipo_allowed BEFORE INSERT ON ipo_snapshots
  FOR EACH ROW EXECUTE FUNCTION assert_ipo_allowed();

-- Grants follow write ownership (architecture §3).
GRANT SELECT, INSERT ON evidence_documents TO app_ai;               -- append-only
GRANT SELECT, INSERT, UPDATE ON ipos TO app_ai;
GRANT SELECT, INSERT ON ipo_snapshots, ipo_snapshot_fields, ipo_field_observations TO app_ai;
GRANT SELECT, INSERT, UPDATE ON ingestion_runs, quarantined_entities TO app_ai;

GRANT SELECT ON ipos, ipo_snapshots, ipo_snapshot_fields, ipo_field_observations TO app_api;
-- Column-level: the API can cite a document but cannot read its stored text.
GRANT SELECT (id, canonical_url, title, publisher, published_at, retrieved_at, source_type,
              authority, retrieval_method, display_rights, is_synthetic)
  ON evidence_documents TO app_api;
-- quarantined_entities and ingestion_runs: no access for app_api.

-- migrate:down

DROP TRIGGER ipo_snapshots_ipo_allowed ON ipo_snapshots;
DROP FUNCTION assert_ipo_allowed();
DROP TABLE quarantined_entities;
DROP TABLE ipo_field_observations;
DROP TABLE ipo_snapshot_fields;
ALTER TABLE ipos DROP CONSTRAINT ipos_current_snapshot_fkey;
DROP TABLE ipo_snapshots;
DROP TABLE ipos;
DROP TABLE evidence_documents;
DROP TABLE ingestion_runs;
