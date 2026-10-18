import type pg from 'pg';
import type {
  FieldObservation,
  IpoDetail,
  IpoField,
  IpoSummary,
  SourceRef,
} from '@arthalens/contracts';

export type IpoStatus = IpoSummary['status'];
export type FieldName = FieldObservation['field'];

export interface ListFilters {
  status?: IpoStatus;
  issueType?: 'mainboard' | 'sme';
  exchange?: 'NSE' | 'BSE';
  /** Already normalised with the policy's normalizeName. */
  nameContains?: string;
  after?: { normalizedName: string; id: string };
  limit: number;
}

export interface IpoIdentity {
  id: string;
  company_name: string;
  exclusion_status: 'allowed' | 'withdrawn_by_policy';
}

export interface ListedIpo extends IpoSummary {
  normalized_name: string;
}

export interface AuditEvent {
  action: string;
  target_type: string;
  target_id: string | null;
  request_id: string;
  metadata: Record<string, unknown>;
}

/** Read-only access to IPO data owned by ai/ (app_api has SELECT only). */
export interface IpoRepository {
  list(filters: ListFilters): Promise<ListedIpo[]>;
  identity(id: string): Promise<IpoIdentity | null>;
  detail(id: string): Promise<IpoDetail | null>;
  audit(event: AuditEvent): Promise<void>;
}

// Rows -------------------------------------------------------------------------------------

interface IpoRow {
  id: string;
  slug: string;
  company_name: string;
  normalized_name: string;
  is_synthetic: boolean;
  snapshot_id: string;
  version: number;
  derived_status: IpoStatus;
  status_as_of: string;
  snapshot_created_at: Date;
}

interface SourceCols {
  e_id: string | null;
  canonical_url: string | null;
  title: string | null;
  publisher: string | null;
  published_at: string | null;
  authority: SourceRef['authority'] | null;
  retrieval_method: SourceRef['retrieval_method'] | null;
  e_synthetic: boolean | null;
  display_rights: 'full_text' | 'excerpt' | 'metadata_only' | null;
}

interface FieldRow extends SourceCols {
  snapshot_id: string;
  field: FieldName;
  value: IpoField['value'];
  status: IpoField['status'];
  evidence_quote: string | null;
  checked_at: Date | null;
  note: string | null;
}

interface ObservationRow extends SourceCols {
  field: FieldName;
  value: IpoField['value'];
  raw_value: string;
  evidence_quote: string;
  quote_verified: boolean;
  parse_error: string | null;
  observed_at: Date;
}

// Only citation columns: app_api has no SELECT on evidence_documents.text_content.
const SOURCE_COLUMNS = `
  e.id AS e_id, e.canonical_url, e.title, e.publisher, e.published_at, e.authority,
  e.retrieval_method, e.is_synthetic AS e_synthetic, e.display_rights`;

const IPO_COLUMNS = `
  i.id, i.slug, i.company_name, i.normalized_name, i.is_synthetic,
  s.id AS snapshot_id, s.version, s.derived_status, s.status_as_of,
  s.created_at AS snapshot_created_at`;

// SQL is built once from constants; values are always bound as $n parameters.
const LIST_SQL = `SELECT ${IPO_COLUMNS}
         FROM ipos i JOIN ipo_snapshots s ON s.id = i.current_snapshot_id
        WHERE i.exclusion_status = 'allowed'
          AND ($1::text IS NULL OR s.derived_status = $1)
          AND ($2::text IS NULL OR i.normalized_name LIKE '%' || $2 || '%' ESCAPE '\\')
          AND ($3::text IS NULL OR EXISTS (
                SELECT 1 FROM ipo_snapshot_fields x
                 WHERE x.snapshot_id = s.id AND x.field = 'issue_type'
                   AND x.status = 'verified' AND x.value = to_jsonb($3::text)))
          AND ($4::text IS NULL OR EXISTS (
                SELECT 1 FROM ipo_snapshot_fields x
                 WHERE x.snapshot_id = s.id AND x.field = 'exchanges'
                   AND x.status = 'verified' AND x.value @> jsonb_build_array($4::text)))
          AND ($5::text IS NULL OR (i.normalized_name, i.id) > ($5::text, $6::uuid))
        ORDER BY i.normalized_name, i.id
        LIMIT $7`;

const DETAIL_SQL = `SELECT ${IPO_COLUMNS}
  FROM ipos i JOIN ipo_snapshots s ON s.id = i.current_snapshot_id
 WHERE i.id = $1 AND i.exclusion_status = 'allowed'`;

const OBSERVATIONS_SQL = `SELECT o.field, o.value, o.raw_value, o.evidence_quote, o.quote_verified,
       o.parse_error, o.observed_at, ${SOURCE_COLUMNS}
  FROM ipo_field_observations o JOIN evidence_documents e ON e.id = o.evidence_id
 WHERE o.snapshot_id = $1
 ORDER BY o.field, o.id`;

const FIELDS_SQL = `SELECT f.snapshot_id, f.field, f.value, f.status, f.evidence_quote, f.checked_at,
       f.note, ${SOURCE_COLUMNS}
  FROM ipo_snapshot_fields f LEFT JOIN evidence_documents e ON e.id = f.evidence_id
 WHERE f.snapshot_id = ANY($1::uuid[])`;

function sourceOf(row: SourceCols): SourceRef | null {
  if (!row.e_id) return null;
  return {
    evidence_id: row.e_id,
    url: row.canonical_url ?? '',
    title: row.title ?? '',
    publisher: row.publisher ?? '',
    published_at: row.published_at,
    authority: row.authority ?? 'unofficial',
    retrieval_method: row.retrieval_method ?? 'manual_import',
    is_synthetic: row.e_synthetic ?? false,
  };
}

/** Respect display rights: a metadata-only source is cited and linked, never quoted. */
function visibleQuote(row: SourceCols, quote: string | null): string | null {
  return row.display_rights === 'metadata_only' ? null : quote;
}

function toSummary(row: IpoRow, fields: Map<string, FieldRow[]>): ListedIpo {
  const out = {} as IpoSummary['fields'];
  for (const f of fields.get(row.snapshot_id) ?? []) {
    out[f.field] = {
      status: f.status,
      value: f.value,
      checked_at: f.checked_at ? f.checked_at.toISOString() : null,
      source: sourceOf(f),
      quote: visibleQuote(f, f.evidence_quote),
      note: f.note,
    };
  }
  return {
    id: row.id,
    slug: row.slug,
    company_name: row.company_name,
    normalized_name: row.normalized_name,
    status: row.derived_status,
    status_as_of: row.status_as_of,
    snapshot_version: row.version,
    snapshot_created_at: row.snapshot_created_at.toISOString(),
    is_synthetic: row.is_synthetic,
    fields: out,
  };
}

export class PgIpoRepository implements IpoRepository {
  constructor(private readonly pool: pg.Pool) {}

  async list(f: ListFilters): Promise<ListedIpo[]> {
    const { rows } = await this.pool.query<IpoRow>(LIST_SQL, [
      f.status ?? null,
      f.nameContains === undefined ? null : escapeLike(f.nameContains),
      f.issueType ?? null,
      f.exchange ?? null,
      f.after?.normalizedName ?? null,
      f.after?.id ?? null,
      f.limit,
    ]);
    const fields = await this.fieldsFor(rows.map((r) => r.snapshot_id));
    return rows.map((r) => toSummary(r, fields));
  }

  async identity(id: string): Promise<IpoIdentity | null> {
    const { rows } = await this.pool.query<IpoIdentity>(
      'SELECT id, company_name, exclusion_status FROM ipos WHERE id = $1',
      [id],
    );
    return rows[0] ?? null;
  }

  async detail(id: string): Promise<IpoDetail | null> {
    const { rows } = await this.pool.query<IpoRow>(DETAIL_SQL, [id]);
    const row = rows[0];
    if (!row) return null;
    const summary = toSummary(row, await this.fieldsFor([row.snapshot_id]));
    const obs = await this.pool.query<ObservationRow>(OBSERVATIONS_SQL, [row.snapshot_id]);
    const observations: FieldObservation[] = obs.rows.flatMap((o) => {
      const source = sourceOf(o);
      if (!source) return [];
      return [
        {
          field: o.field,
          value: o.value,
          raw_value: o.raw_value,
          quote: visibleQuote(o, o.evidence_quote) ?? '',
          quote_verified: o.quote_verified,
          parse_error: o.parse_error,
          observed_at: o.observed_at.toISOString(),
          source,
        },
      ];
    });
    const { normalized_name: _omit, ...publicSummary } = summary;
    return { ...publicSummary, observations };
  }

  async audit(e: AuditEvent): Promise<void> {
    await this.pool.query(
      `INSERT INTO audit_events (action, target_type, target_id, request_id, metadata)
       VALUES ($1, $2, $3, $4, $5)`,
      [e.action, e.target_type, e.target_id, e.request_id, JSON.stringify(e.metadata)],
    );
  }

  private async fieldsFor(snapshotIds: string[]): Promise<Map<string, FieldRow[]>> {
    const byId = new Map<string, FieldRow[]>();
    if (snapshotIds.length === 0) return byId;
    const { rows } = await this.pool.query<FieldRow>(FIELDS_SQL, [snapshotIds]);
    for (const row of rows) {
      const list = byId.get(row.snapshot_id) ?? [];
      list.push(row);
      byId.set(row.snapshot_id, list);
    }
    return byId;
  }
}

/** Escape LIKE wildcards so a search for "50%" matches the literal text. */
export function escapeLike(text: string): string {
  return text.replace(/[\\%_]/g, (c) => `\\${c}`);
}
