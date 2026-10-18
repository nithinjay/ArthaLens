import { createHash } from 'node:crypto';
import type pg from 'pg';
import type {
  ReportCitation,
  ReportClaim,
  ReportSection,
  ResearchCreated,
  ResearchEvent,
  ResearchEvidence,
  ResearchList,
  ResearchReport,
  ResearchSummary,
} from '@arthalens/contracts';
import type { Identity } from '../identity.js';
import { withTenant } from '../tenant.js';

export const PIPELINE_VERSION = 'm4.1';
export const TERMINAL_EVENTS = new Set(['job.completed', 'job.failed', 'job.rejected']);

export const DISCLAIMERS = [
  'Educational research only. This is not investment advice and does not recommend subscribing to, buying or avoiding any security.',
  'Only claims marked verified have been checked against their sources. Other claims are drafts awaiting validation.',
  'IPO allotment is never guaranteed. Check the latest official documents before making any decision.',
];

const DISPLAY: Record<ReportSection['status'], ReportSection['display_status']> = {
  ok: 'Verified',
  degraded: 'Partial',
  unavailable: 'Not found',
};

export class IdempotencyConflict extends Error {
  override name = 'IdempotencyConflict';
}
export class NotFound extends Error {
  override name = 'NotFound';
}

export interface ReportIpo {
  ipo_id: string;
  company_name: string;
  exclusion_status: string;
}

export interface ResearchRepository {
  create(identity: Identity, ipoId: string, idempotencyKey?: string): Promise<ResearchCreated>;
  reportIpo(identity: Identity, reportId: string): Promise<ReportIpo | null>;
  report(identity: Identity, reportId: string): Promise<ResearchReport | null>;
  list(
    identity: Identity,
    limit: number,
    before?: { createdAt: string; id: string },
  ): Promise<ResearchList>;
  events(identity: Identity, reportId: string, afterSeq: number): Promise<ResearchEvent[]>;
  evidence(identity: Identity, reportId: string): Promise<ResearchEvidence | null>;
  softDelete(identity: Identity, reportId: string): Promise<boolean>;
}

const eventsUrl = (id: string) => `/api/v1/research/${id}/events`;
const iso = (d: Date | null) => (d ? d.toISOString() : null);

// SQL is built from constants only; values are always bound as $n parameters.
const OWN_REPORT = `r.id = $1 AND r.owner_user_id = current_setting('app.user_id')::uuid
  AND r.deleted_at IS NULL`;

const REPORT_SQL = `SELECT r.id, r.ipo_id, i.company_name, i.is_synthetic, s.version AS snapshot_version,
       r.status, r.created_at, r.started_at, r.completed_at
  FROM research_reports r JOIN ipos i ON i.id = r.ipo_id JOIN ipo_snapshots s ON s.id = r.snapshot_id
 WHERE ${OWN_REPORT}`;

const SECTIONS_SQL = `SELECT section, title, status, validation, reason, missing, model, prompt_version
  FROM research_sections WHERE report_id = $1 ORDER BY section`;

const CLAIMS_SQL = `SELECT c.id, c.section, c.position, c.text, c.claim_type, c.status, c.status_reason,
       cc.label, cc.document_id, cc.page, cc.quote, d.title, d.publisher, d.canonical_url,
       d.authority, d.is_synthetic, d.display_rights
  FROM evidence_claims c
  LEFT JOIN claim_citations cc ON cc.claim_id = c.id
  LEFT JOIN evidence_documents d ON d.id = cc.document_id
 WHERE c.report_id = $1
 ORDER BY c.section, c.position, cc.label`;

const EVIDENCE_SQL = `SELECT it.label, d.id AS document_id, d.title, d.publisher, d.canonical_url,
       d.published_at, d.retrieved_at, d.authority, d.source_type, d.version, d.is_synthetic,
       (SELECT count(*) FROM claim_citations cc JOIN evidence_claims c ON c.id = cc.claim_id
         WHERE c.report_id = r.id AND cc.document_id = d.id)::int AS cited_by_claims
  FROM research_reports r
  JOIN evidence_set_items it ON it.set_id = r.evidence_set_id
  JOIN evidence_documents d ON d.id = it.document_id
 WHERE ${OWN_REPORT}
 ORDER BY it.position`;

const REPORT_IPO_SQL = `SELECT r.ipo_id, i.company_name, i.exclusion_status
  FROM research_reports r JOIN ipos i ON i.id = r.ipo_id WHERE ${OWN_REPORT}`;

const EVENTS_SQL = `SELECT e.seq, e.type, e.payload, e.created_at
  FROM research_events e JOIN research_reports r ON r.id = e.report_id
 WHERE ${OWN_REPORT} AND e.seq > $2
 ORDER BY e.seq LIMIT 1000`;

const REPORT_EXISTS_SQL = `SELECT 1 FROM research_reports r WHERE ${OWN_REPORT}`;

const SOFT_DELETE_SQL = `UPDATE research_reports r SET deleted_at = now() WHERE ${OWN_REPORT}`;

const LIST_SQL = `SELECT r.id, r.ipo_id, i.company_name, r.status, r.created_at, r.completed_at
  FROM research_reports r JOIN ipos i ON i.id = r.ipo_id
 WHERE r.owner_user_id = current_setting('app.user_id')::uuid AND r.deleted_at IS NULL
   AND ($1::timestamptz IS NULL OR (r.created_at, r.id) < ($1::timestamptz, $2::uuid))
 ORDER BY r.created_at DESC, r.id DESC
 LIMIT $3`;

interface ClaimRow {
  id: string;
  section: string;
  text: string;
  claim_type: ReportClaim['claim_type'];
  status: ReportClaim['status'];
  status_reason: string | null;
  label: string | null;
  document_id: string | null;
  page: number | null;
  quote: string | null;
  title: string | null;
  publisher: string | null;
  canonical_url: string | null;
  authority: ReportCitation['authority'] | null;
  is_synthetic: boolean | null;
  display_rights: string | null;
}

export class PgResearchRepository implements ResearchRepository {
  constructor(private readonly pool: pg.Pool) {}

  async create(identity: Identity, ipoId: string, key?: string): Promise<ResearchCreated> {
    const requestHash = createHash('sha256').update(`research.create:${ipoId}`).digest('hex');
    try {
      return await this.createOnce(identity, ipoId, requestHash, key);
    } catch (err) {
      // Two requests raced with the same key: the loser replays the winner's answer.
      if (key && (err as { code?: string }).code === '23505') {
        return this.createOnce(identity, ipoId, requestHash, key);
      }
      throw err;
    }
  }

  private createOnce(identity: Identity, ipoId: string, requestHash: string, key?: string) {
    return withTenant(this.pool, identity, async (db) => {
      if (key) {
        const seen = await db.query<{ request_hash: string; response: ResearchCreated }>(
          `SELECT request_hash, response FROM idempotency_keys
            WHERE tenant_id = $1 AND user_id = $2 AND operation = 'research.create' AND key = $3`,
          [identity.tenantId, identity.userId, key],
        );
        const prior = seen.rows[0];
        if (prior) {
          if (prior.request_hash !== requestHash) {
            throw new IdempotencyConflict(
              'Idempotency-Key was already used for a different request',
            );
          }
          return { ...prior.response, created: false };
        }
      }
      const ipo = await db.query<{ current_snapshot_id: string | null }>(
        "SELECT current_snapshot_id FROM ipos WHERE id = $1 AND exclusion_status = 'allowed'",
        [ipoId],
      );
      const snapshotId = ipo.rows[0]?.current_snapshot_id;
      if (!snapshotId) throw new NotFound('IPO has no snapshot to research');

      const report = await db.query<{ id: string; status: ResearchCreated['status'] }>(
        `INSERT INTO research_reports (tenant_id, owner_user_id, ipo_id, snapshot_id, pipeline_version)
         VALUES ($1, $2, $3, $4, $5) RETURNING id, status`,
        [identity.tenantId, identity.userId, ipoId, snapshotId, PIPELINE_VERSION],
      );
      const created = report.rows[0];
      if (!created) throw new Error('report insert returned nothing');
      await db.query('INSERT INTO research_jobs (report_id, tenant_id) VALUES ($1, $2)', [
        created.id,
        identity.tenantId,
      ]);
      await db.query(
        `INSERT INTO research_events (report_id, tenant_id, seq, type, payload)
         VALUES ($1, $2, 1, 'job.queued', $3)`,
        [created.id, identity.tenantId, JSON.stringify({ ipo_id: ipoId, snapshot_id: snapshotId })],
      );
      await db.query("SELECT pg_notify('research_events', $1)", [created.id]);
      const response: ResearchCreated = {
        report_id: created.id,
        status: created.status,
        events_url: eventsUrl(created.id),
        created: true,
      };
      if (key) {
        await db.query(
          `INSERT INTO idempotency_keys (tenant_id, user_id, operation, key, request_hash, response)
           VALUES ($1, $2, 'research.create', $3, $4, $5)`,
          [identity.tenantId, identity.userId, key, requestHash, JSON.stringify(response)],
        );
      }
      return response;
    });
  }

  reportIpo(identity: Identity, reportId: string): Promise<ReportIpo | null> {
    return withTenant(this.pool, identity, async (db) => {
      const { rows } = await db.query<ReportIpo>(REPORT_IPO_SQL, [reportId]);
      return rows[0] ?? null;
    });
  }

  report(identity: Identity, reportId: string): Promise<ResearchReport | null> {
    return withTenant(this.pool, identity, async (db) => {
      const head = (await db.query(REPORT_SQL, [reportId])).rows[0];
      if (!head) return null;
      const sections = (await db.query(SECTIONS_SQL, [reportId])).rows;
      const claimRows = (await db.query<ClaimRow>(CLAIMS_SQL, [reportId])).rows;

      const claims = new Map<string, Map<string, ReportClaim>>();
      for (const r of claimRows) {
        const bySection = claims.get(r.section) ?? new Map<string, ReportClaim>();
        claims.set(r.section, bySection);
        let claim = bySection.get(r.id);
        if (!claim) {
          claim = {
            text: r.text,
            claim_type: r.claim_type,
            status: r.status,
            status_reason: r.status_reason,
            citations: [],
          };
          bySection.set(r.id, claim);
        }
        if (r.label && r.document_id) {
          claim.citations.push({
            label: r.label,
            document_id: r.document_id,
            title: r.title ?? '',
            publisher: r.publisher ?? '',
            url: r.canonical_url ?? '',
            page: r.page,
            // Respect display rights: metadata-only sources are cited and linked, not quoted.
            quote: r.display_rights === 'metadata_only' ? null : r.quote,
            authority: r.authority ?? 'unofficial',
            is_synthetic: r.is_synthetic ?? false,
          });
        }
      }
      return {
        schema_version: 'research-report.v1',
        id: head.id,
        ipo_id: head.ipo_id,
        company_name: head.company_name,
        snapshot_version: head.snapshot_version,
        status: head.status,
        is_synthetic: head.is_synthetic,
        created_at: head.created_at.toISOString(),
        started_at: iso(head.started_at),
        completed_at: iso(head.completed_at),
        sections: sections.map((s) => ({
          section: s.section,
          title: s.title,
          status: s.status,
          display_status: DISPLAY[s.status as ReportSection['status']],
          validation: s.validation,
          reason: s.reason,
          missing: s.missing,
          model: s.model,
          prompt_version: s.prompt_version,
          claims: [...(claims.get(s.section)?.values() ?? [])],
        })),
        disclaimers: DISCLAIMERS,
      };
    });
  }

  list(
    identity: Identity,
    limit: number,
    before?: { createdAt: string; id: string },
  ): Promise<ResearchList> {
    return withTenant(this.pool, identity, async (db) => {
      const { rows } = await db.query(LIST_SQL, [
        before?.createdAt ?? null,
        before?.id ?? null,
        limit + 1,
      ]);
      const page: ResearchSummary[] = rows.slice(0, limit).map((r) => ({
        id: r.id,
        ipo_id: r.ipo_id,
        company_name: r.company_name,
        status: r.status,
        created_at: r.created_at.toISOString(),
        completed_at: iso(r.completed_at),
      }));
      const last = page.at(-1);
      const nextCursor =
        rows.length > limit && last
          ? Buffer.from(JSON.stringify([last.created_at, last.id])).toString('base64url')
          : null;
      return { schema_version: 'research-list.v1', items: page, next_cursor: nextCursor };
    });
  }

  events(identity: Identity, reportId: string, afterSeq: number): Promise<ResearchEvent[]> {
    return withTenant(this.pool, identity, async (db) => {
      const { rows } = await db.query(EVENTS_SQL, [reportId, afterSeq]);
      return rows.map((r) => ({
        seq: Number(r.seq),
        type: r.type,
        payload: r.payload,
        created_at: r.created_at.toISOString(),
      }));
    });
  }

  evidence(identity: Identity, reportId: string): Promise<ResearchEvidence | null> {
    return withTenant(this.pool, identity, async (db) => {
      const exists = await db.query(REPORT_EXISTS_SQL, [reportId]);
      if (exists.rowCount === 0) return null;
      const { rows } = await db.query(EVIDENCE_SQL, [reportId]);
      return {
        schema_version: 'research-evidence.v1',
        report_id: reportId,
        items: rows.map((r) => ({
          label: r.label,
          document_id: r.document_id,
          title: r.title,
          publisher: r.publisher,
          url: r.canonical_url,
          published_at: r.published_at,
          retrieved_at: r.retrieved_at.toISOString(),
          authority: r.authority,
          source_type: r.source_type,
          version: r.version,
          is_synthetic: r.is_synthetic,
          cited_by_claims: r.cited_by_claims,
        })),
      };
    });
  }

  softDelete(identity: Identity, reportId: string): Promise<boolean> {
    return withTenant(this.pool, identity, async (db) => {
      const res = await db.query(SOFT_DELETE_SQL, [reportId]);
      return (res.rowCount ?? 0) > 0;
    });
  }
}
