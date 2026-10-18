-- migrate:up

-- Milestone 3: evidence ledger (brief section 9, ADR-0016).
--   evidence_contents   content-addressed bytes metadata (one row per SHA-256)
--   evidence_passages   page-anchored text extracted from a content
--   evidence_documents  a source record (URL + metadata) pointing at one content; versioned
--   evidence_retrievals append-only log of every retrieval, including unchanged re-fetches
--   evidence_sets/items stable per-report labels d1, d2, ...
-- Everything is immutable: rows are only ever inserted (retention purge excepted).

CREATE TABLE evidence_contents (
  sha256             text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  mime_type          text NOT NULL CHECK (mime_type IN ('text/plain', 'text/html', 'application/pdf')),
  byte_size          bigint NOT NULL CHECK (byte_size >= 0),
  page_count         integer CHECK (page_count >= 0),  -- NULL for unpaginated formats
  extraction_method  text NOT NULL CHECK (extraction_method IN ('plain_text', 'html', 'pdf_text', 'pdf_text_ocr')),
  extractor_version  text NOT NULL,
  -- Object-storage key for the raw bytes, when retained. Never served by the API.
  storage_key        text CHECK (storage_key ~ '^sha256/[0-9a-f]{2}/[0-9a-f]{64}$'),
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence_passages (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_sha256  text NOT NULL REFERENCES evidence_contents (sha256),
  page_number     integer CHECK (page_number >= 1),     -- NULL when the format has no pages
  passage_index   integer NOT NULL CHECK (passage_index >= 0),
  text            text NOT NULL CHECK (length(text) <= 4000),
  extraction      text NOT NULL CHECK (extraction IN ('text', 'ocr')),
  -- Mean Tesseract word confidence (0-100), only for OCR'd passages.
  ocr_confidence  numeric(5, 2) CHECK (ocr_confidence BETWEEN 0 AND 100),
  CONSTRAINT passages_ocr_confidence_iff_ocr CHECK ((extraction = 'ocr') = (ocr_confidence IS NOT NULL))
);
CREATE UNIQUE INDEX evidence_passages_position_key
  ON evidence_passages (content_sha256, coalesce(page_number, 0), passage_index);

-- Canonical source key. Must match ai/arthalens_ai/evidence/canonical.py exactly; the shared
-- vectors in ai/tests/test_evidence_integration.py check both. Rules: lower-case scheme and
-- host, drop trailing dot, userinfo, default port and fragment; empty path -> "/"; drop empty,
-- utm_* and tracking query parameters; sort the rest as raw "k=v" strings (byte order).
CREATE FUNCTION canonical_source_key(url text) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
  m text[];
  scheme text;
  host text;
  port text;
  path text;
  query text;
BEGIN
  m := regexp_match(btrim(url),
    '^([A-Za-z][A-Za-z0-9+.-]*)://(?:[^@/?#]*@)?([^:/?#]*)(?::([0-9]*))?([^?#]*)(?:\?([^#]*))?(?:#.*)?$');
  IF m IS NULL THEN
    RETURN NULL;
  END IF;
  scheme := lower(m[1]);
  host := rtrim(lower(m[2]), '.');
  IF scheme NOT IN ('http', 'https') OR host = '' THEN
    RETURN NULL;
  END IF;
  port := nullif(m[3], '');
  IF port IS NOT NULL AND port::integer = (CASE scheme WHEN 'https' THEN 443 ELSE 80 END) THEN
    port := NULL;
  END IF;
  path := CASE WHEN coalesce(m[4], '') = '' THEN '/' ELSE m[4] END;
  SELECT string_agg(pair, '&' ORDER BY pair COLLATE "C") INTO query
    FROM unnest(string_to_array(coalesce(m[5], ''), '&')) AS pair
   WHERE pair <> ''
     AND lower(split_part(pair, '=', 1)) NOT LIKE 'utm\_%'
     AND lower(split_part(pair, '=', 1)) NOT IN ('fbclid', 'gclid', 'mc_cid', 'mc_eid', 'ref', 'ref_src');
  RETURN scheme || '://' || host || coalesce(':' || port, '') || path || coalesce('?' || query, '');
END;
$$;

-- Backfill contents and passages from Milestone 2 documents before reshaping the table.
INSERT INTO evidence_contents (sha256, mime_type, byte_size, extraction_method, extractor_version)
SELECT DISTINCT ON (content_sha256) content_sha256, mime_type, byte_size,
       CASE mime_type WHEN 'text/html' THEN 'html' WHEN 'application/pdf' THEN 'pdf_text' ELSE 'plain_text' END,
       'm2-backfill'
  FROM evidence_documents
 ORDER BY content_sha256, created_at;

-- Milestone 2 kept one text blob per document, without pages. Split it into passages of at
-- most 4000 characters so nothing is lost (page_number stays NULL: the pages are unknown).
INSERT INTO evidence_passages (content_sha256, page_number, passage_index, text, extraction)
SELECT d.content_sha256, NULL::integer, n - 1, substr(d.text_content, (n - 1) * 4000 + 1, 4000), 'text'
  FROM (SELECT DISTINCT ON (content_sha256) content_sha256, text_content
          FROM evidence_documents ORDER BY content_sha256, created_at) AS d
 CROSS JOIN LATERAL generate_series(1, greatest(1, ceil(length(d.text_content) / 4000.0)::integer)) AS n;

ALTER TABLE evidence_documents
  ADD COLUMN source_key     text,
  ADD COLUMN version        integer,
  ADD COLUMN supersedes_id  uuid REFERENCES evidence_documents (id),
  ADD COLUMN visibility     text NOT NULL DEFAULT 'public' CHECK (visibility IN ('public', 'tenant')),
  ADD COLUMN tenant_id      uuid REFERENCES tenants (id);

-- Milestone 2 allowed several contents per URL. They become versions in retrieval order, each
-- superseding the one before.
WITH keyed AS (
  SELECT id, coalesce(canonical_source_key(canonical_url), canonical_url) AS k,
         row_number() OVER w AS v, lag(id) OVER w AS prev
    FROM evidence_documents
  WINDOW w AS (PARTITION BY coalesce(canonical_source_key(canonical_url), canonical_url)
               ORDER BY retrieved_at, created_at, id)
)
UPDATE evidence_documents d SET source_key = keyed.k, version = keyed.v, supersedes_id = keyed.prev
  FROM keyed WHERE keyed.id = d.id;

ALTER TABLE evidence_documents
  ALTER COLUMN source_key SET NOT NULL,
  ALTER COLUMN version SET NOT NULL,
  ADD CONSTRAINT evidence_documents_version_check CHECK (version >= 1),
  ADD CONSTRAINT evidence_documents_content_fkey
    FOREIGN KEY (content_sha256) REFERENCES evidence_contents (sha256),
  ADD CONSTRAINT evidence_documents_tenant_iff_private
    CHECK ((visibility = 'tenant') = (tenant_id IS NOT NULL)),
  -- Tenant documents live in their tenant's key namespace, so a tenant's copy of a URL can
  -- never collide with (or reveal itself to) the public version chain of that URL.
  ADD CONSTRAINT evidence_documents_key_namespace CHECK (
    CASE visibility
      WHEN 'public' THEN source_key !~ '^(upload|tenant):'
      ELSE source_key LIKE 'upload:' || tenant_id::text || ':%'
        OR source_key LIKE 'tenant:' || tenant_id::text || ':%'
    END),
  -- Versions are a timeline per source: v1, v2, ... A reverted document gets a new version.
  ADD CONSTRAINT evidence_documents_version_key UNIQUE (source_key, version),
  ADD CONSTRAINT evidence_documents_supersedes_older CHECK ((supersedes_id IS NULL) = (version = 1)),
  DROP CONSTRAINT evidence_documents_content_url_key,
  DROP COLUMN text_content,
  DROP COLUMN mime_type,
  DROP COLUMN byte_size;

CREATE TABLE evidence_retrievals (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  document_id       uuid NOT NULL REFERENCES evidence_documents (id),
  retrieved_at      timestamptz NOT NULL,
  retrieval_method  text NOT NULL CHECK (retrieval_method IN ('mock_fixture', 'manual_import', 'live_fetch', 'upload')),
  provider          text NOT NULL,
  ingestion_run_id  uuid REFERENCES ingestion_runs (id),
  -- Non-sensitive request facts only: final URL, HTTP status, content type, length, ETag.
  request_metadata  jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX evidence_retrievals_document_idx ON evidence_retrievals (document_id, retrieved_at DESC);

INSERT INTO evidence_retrievals (document_id, retrieved_at, retrieval_method, provider)
SELECT id, retrieved_at, retrieval_method, provider FROM evidence_documents;

ALTER TABLE evidence_documents DROP CONSTRAINT evidence_documents_retrieval_method_check;
ALTER TABLE evidence_documents ADD CONSTRAINT evidence_documents_retrieval_method_check
  CHECK (retrieval_method IN ('mock_fixture', 'manual_import', 'live_fetch', 'upload'));

CREATE TABLE evidence_sets (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid REFERENCES tenants (id),  -- NULL: built from public evidence only
  purpose        text NOT NULL CHECK (purpose IN ('ipo_snapshot', 'research_report', 'test')),
  next_position  integer NOT NULL DEFAULT 1 CHECK (next_position >= 1),
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence_set_items (
  set_id       uuid NOT NULL REFERENCES evidence_sets (id),
  position     integer NOT NULL CHECK (position >= 1),
  label        text GENERATED ALWAYS AS ('d' || position::text) STORED,
  document_id  uuid NOT NULL REFERENCES evidence_documents (id),
  added_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (set_id, position),
  CONSTRAINT evidence_set_items_document_key UNIQUE (set_id, document_id),
  CONSTRAINT evidence_set_items_label_key UNIQUE (set_id, label)
);

ALTER TABLE ipo_snapshots ADD COLUMN evidence_set_id uuid REFERENCES evidence_sets (id);
ALTER TABLE ipo_snapshot_fields ADD COLUMN evidence_page integer CHECK (evidence_page >= 1);
ALTER TABLE ipo_field_observations ADD COLUMN evidence_page integer CHECK (evidence_page >= 1);

-- Immutability ---------------------------------------------------------------------------
-- Blocks UPDATE, DELETE and TRUNCATE for every role, including the table owner. The only
-- exception is a DELETE in a session that explicitly opts in to retention purging.
CREATE FUNCTION forbid_evidence_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('arthalens.evidence_retention', true) = 'on' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'EVIDENCE_IMMUTABLE: % on % is not allowed', TG_OP, TG_TABLE_NAME
    USING ERRCODE = 'raise_exception';
END;
$$;

-- One permitted change: attaching retained bytes to content that had none (storage_key
-- NULL -> value, every other column unchanged). It adds a snapshot; it alters no evidence.
CREATE FUNCTION guard_evidence_content_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.storage_key IS NULL AND NEW.storage_key IS NOT NULL
     AND ROW(NEW.sha256, NEW.mime_type, NEW.byte_size, NEW.page_count, NEW.extraction_method,
             NEW.extractor_version, NEW.created_at)
         IS NOT DISTINCT FROM
         ROW(OLD.sha256, OLD.mime_type, OLD.byte_size, OLD.page_count, OLD.extraction_method,
             OLD.extractor_version, OLD.created_at) THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'EVIDENCE_IMMUTABLE: UPDATE on evidence_contents is not allowed'
    USING ERRCODE = 'raise_exception';
END;
$$;
CREATE TRIGGER evidence_contents_immutable BEFORE UPDATE ON evidence_contents
  FOR EACH ROW EXECUTE FUNCTION guard_evidence_content_update();
CREATE TRIGGER evidence_contents_no_delete BEFORE DELETE ON evidence_contents
  FOR EACH ROW EXECUTE FUNCTION forbid_evidence_mutation();
CREATE TRIGGER evidence_contents_no_truncate BEFORE TRUNCATE ON evidence_contents
  FOR EACH STATEMENT EXECUTE FUNCTION forbid_evidence_mutation();

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['evidence_passages', 'evidence_documents',
                           'evidence_retrievals', 'evidence_set_items'] LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I
                    FOR EACH ROW EXECUTE FUNCTION forbid_evidence_mutation()', t || '_immutable', t);
    EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I
                    FOR EACH STATEMENT EXECUTE FUNCTION forbid_evidence_mutation()', t || '_no_truncate', t);
  END LOOP;
END;
$$;

-- An evidence set may only advance its counter.
CREATE FUNCTION guard_evidence_set_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.id <> OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.purpose <> OLD.purpose
     OR NEW.created_at <> OLD.created_at OR NEW.next_position <> OLD.next_position + 1 THEN
    RAISE EXCEPTION 'EVIDENCE_IMMUTABLE: evidence_sets may only advance next_position by one';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER evidence_sets_guard BEFORE UPDATE ON evidence_sets
  FOR EACH ROW EXECUTE FUNCTION guard_evidence_set_update();
CREATE TRIGGER evidence_sets_immutable_delete BEFORE DELETE ON evidence_sets
  FOR EACH ROW EXECUTE FUNCTION forbid_evidence_mutation();

-- A set may only cite documents its tenant is allowed to see. Foreign-key checks ignore RLS,
-- so this has to be explicit.
CREATE FUNCTION check_evidence_set_item() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  set_tenant uuid;
  doc_visibility text;
  doc_tenant uuid;
BEGIN
  SELECT tenant_id INTO set_tenant FROM evidence_sets WHERE id = NEW.set_id;
  SELECT visibility, tenant_id INTO doc_visibility, doc_tenant
    FROM evidence_documents WHERE id = NEW.document_id;
  IF doc_visibility IS NULL THEN
    RAISE EXCEPTION 'EVIDENCE_NOT_VISIBLE: document % is not visible here', NEW.document_id;
  END IF;
  IF doc_visibility = 'tenant' AND doc_tenant IS DISTINCT FROM set_tenant THEN
    RAISE EXCEPTION 'EVIDENCE_NOT_VISIBLE: document % belongs to another tenant', NEW.document_id;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER evidence_set_items_visibility BEFORE INSERT ON evidence_set_items
  FOR EACH ROW EXECUTE FUNCTION check_evidence_set_item();

-- Row-level security (ADR-0011): public evidence is shared; tenant evidence is private.
ALTER TABLE evidence_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_contents ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_passages ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_retrievals ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_set_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY evidence_documents_read ON evidence_documents FOR SELECT
  USING (visibility = 'public' OR tenant_id = current_tenant_id());
CREATE POLICY evidence_documents_write ON evidence_documents FOR INSERT
  WITH CHECK (visibility = 'public' OR tenant_id = current_tenant_id());

-- Content and passages are visible through any document the caller may see.
CREATE POLICY evidence_contents_read ON evidence_contents FOR SELECT
  USING (EXISTS (SELECT 1 FROM evidence_documents d WHERE d.content_sha256 = sha256));
CREATE POLICY evidence_passages_read ON evidence_passages FOR SELECT
  USING (EXISTS (SELECT 1 FROM evidence_documents d WHERE d.content_sha256 = evidence_passages.content_sha256));

-- Contents and passages are written ONLY through this function. A plain INSERT can't work
-- under RLS: INSERT ... ON CONFLICT applies the SELECT policy to the new row, and a new content
-- isn't referenced by a visible document yet. Checking for existence first would itself be
-- filtered by RLS (content known only through another tenant's private document looks
-- absent). The function runs as the table owner, does exactly one idempotent insert, and
-- reports whether the bytes were new. Constraints and immutability triggers still apply.
CREATE FUNCTION evidence_put_content(
  p_sha256 text, p_mime_type text, p_byte_size bigint, p_page_count integer,
  p_extraction_method text, p_extractor_version text, p_storage_key text, p_passages jsonb
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  inserted integer;
BEGIN
  INSERT INTO evidence_contents (sha256, mime_type, byte_size, page_count, extraction_method,
                                 extractor_version, storage_key)
  VALUES (p_sha256, p_mime_type, p_byte_size, p_page_count, p_extraction_method,
          p_extractor_version, p_storage_key)
  ON CONFLICT (sha256) DO NOTHING;
  GET DIAGNOSTICS inserted = ROW_COUNT;
  IF inserted = 0 THEN
    -- Known bytes: their passages already exist and are immutable. If the bytes are now
    -- retained for the first time, record where (the only update the guard allows).
    IF p_storage_key IS NOT NULL THEN
      UPDATE evidence_contents SET storage_key = p_storage_key
       WHERE sha256 = p_sha256 AND storage_key IS NULL;
    END IF;
    RETURN false;
  END IF;
  INSERT INTO evidence_passages (content_sha256, page_number, passage_index, text, extraction,
                                 ocr_confidence)
  SELECT p_sha256, (e->>'page_number')::integer, (e->>'passage_index')::integer, e->>'text',
         e->>'extraction', (e->>'ocr_confidence')::numeric
    FROM jsonb_array_elements(p_passages) AS e;
  RETURN true;
END;
$$;
REVOKE ALL ON FUNCTION evidence_put_content(text, text, bigint, integer, text, text, text, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION evidence_put_content(text, text, bigint, integer, text, text, text, jsonb) TO app_ai;

CREATE POLICY evidence_retrievals_read ON evidence_retrievals FOR SELECT
  USING (EXISTS (SELECT 1 FROM evidence_documents d WHERE d.id = document_id));
CREATE POLICY evidence_retrievals_write ON evidence_retrievals FOR INSERT
  WITH CHECK (EXISTS (SELECT 1 FROM evidence_documents d WHERE d.id = document_id));

CREATE POLICY evidence_sets_access ON evidence_sets
  USING (tenant_id IS NULL OR tenant_id = current_tenant_id())
  WITH CHECK (tenant_id IS NULL OR tenant_id = current_tenant_id());
CREATE POLICY evidence_set_items_read ON evidence_set_items FOR SELECT
  USING (EXISTS (SELECT 1 FROM evidence_sets s WHERE s.id = set_id));
CREATE POLICY evidence_set_items_write ON evidence_set_items FOR INSERT
  WITH CHECK (EXISTS (SELECT 1 FROM evidence_sets s WHERE s.id = set_id));

-- Grants: only ai/ writes evidence (brief section 9), and only by INSERT.
GRANT SELECT ON evidence_contents, evidence_passages TO app_ai;  -- writes via evidence_put_content
GRANT SELECT, INSERT ON evidence_retrievals, evidence_sets, evidence_set_items TO app_ai;
GRANT UPDATE (next_position) ON evidence_sets TO app_ai;
GRANT SELECT (version, visibility, tenant_id) ON evidence_documents TO app_api;
GRANT UPDATE (evidence_set_id) ON ipo_snapshots TO app_ai;

-- migrate:down

REVOKE UPDATE (evidence_set_id) ON ipo_snapshots FROM app_ai;
ALTER TABLE ipo_field_observations DROP COLUMN evidence_page;
ALTER TABLE ipo_snapshot_fields DROP COLUMN evidence_page;
ALTER TABLE ipo_snapshots DROP COLUMN evidence_set_id;

DROP FUNCTION evidence_put_content(text, text, bigint, integer, text, text, text, jsonb);
DROP TRIGGER evidence_set_items_visibility ON evidence_set_items;
DROP FUNCTION check_evidence_set_item();
DROP TABLE evidence_set_items;
DROP TABLE evidence_sets;
DROP FUNCTION guard_evidence_set_update();

-- Restore the Milestone 2 shape of evidence_documents, then drop the ledger tables.
DROP TRIGGER evidence_contents_immutable ON evidence_contents;
DROP TRIGGER evidence_contents_no_delete ON evidence_contents;
DROP TRIGGER evidence_contents_no_truncate ON evidence_contents;
DROP FUNCTION guard_evidence_content_update();
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['evidence_passages', 'evidence_documents',
                           'evidence_retrievals'] LOOP
    EXECUTE format('DROP TRIGGER %I ON %I', t || '_immutable', t);
    EXECUTE format('DROP TRIGGER %I ON %I', t || '_no_truncate', t);
  END LOOP;
END;
$$;
DROP FUNCTION forbid_evidence_mutation();

DROP POLICY evidence_documents_read ON evidence_documents;
DROP POLICY evidence_documents_write ON evidence_documents;
ALTER TABLE evidence_documents DISABLE ROW LEVEL SECURITY;

-- Refuse to roll back data the Milestone 2 shape can't represent safely: it has no notion of
-- tenant-private evidence (rolling back would make it public) and allows only one document
-- per (content, URL). Deleting rows instead would break foreign keys and lose evidence.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM evidence_documents WHERE visibility = 'tenant') THEN
    RAISE EXCEPTION 'cannot roll back: tenant-private evidence exists and would become public';
  END IF;
  IF EXISTS (SELECT 1 FROM evidence_documents GROUP BY content_sha256, canonical_url HAVING count(*) > 1) THEN
    RAISE EXCEPTION 'cannot roll back: a source has repeated content across versions';
  END IF;
END;
$$;

ALTER TABLE evidence_documents
  ADD COLUMN text_content text,
  ADD COLUMN mime_type text,
  ADD COLUMN byte_size bigint;
UPDATE evidence_documents d SET
  mime_type = c.mime_type,
  byte_size = c.byte_size,
  -- Chunks backfilled from one Milestone 2 text blob rejoin exactly; real passages by newline.
  text_content = coalesce((SELECT string_agg(p.text,
                                    CASE c.extractor_version WHEN 'm2-backfill' THEN '' ELSE E'\n' END
                                    ORDER BY coalesce(p.page_number, 0), p.passage_index)
                             FROM evidence_passages p WHERE p.content_sha256 = c.sha256), '')
  FROM evidence_contents c WHERE c.sha256 = d.content_sha256;
ALTER TABLE evidence_documents
  ALTER COLUMN text_content SET NOT NULL,
  ALTER COLUMN mime_type SET NOT NULL,
  ALTER COLUMN byte_size SET NOT NULL,
  ADD CONSTRAINT evidence_documents_byte_size_check CHECK (byte_size >= 0),
  ADD CONSTRAINT evidence_documents_content_url_key UNIQUE (content_sha256, canonical_url),
  DROP CONSTRAINT evidence_documents_content_fkey,
  DROP CONSTRAINT evidence_documents_key_namespace,
  DROP CONSTRAINT evidence_documents_version_key,
  DROP COLUMN source_key,
  DROP COLUMN version,
  DROP COLUMN supersedes_id,
  DROP COLUMN visibility,
  DROP COLUMN tenant_id;
ALTER TABLE evidence_documents DROP CONSTRAINT evidence_documents_retrieval_method_check;
ALTER TABLE evidence_documents ADD CONSTRAINT evidence_documents_retrieval_method_check
  CHECK (retrieval_method IN ('mock_fixture', 'manual_import', 'live_fetch'));
GRANT SELECT (id, canonical_url, title, publisher, published_at, retrieved_at, source_type,
              authority, retrieval_method, display_rights, is_synthetic)
  ON evidence_documents TO app_api;

DROP TABLE evidence_retrievals;
DROP TABLE evidence_passages;
DROP TABLE evidence_contents;
DROP FUNCTION canonical_source_key(text);
