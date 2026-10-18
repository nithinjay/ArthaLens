import type {
  DependencyCheck,
  IpoDetail,
  IpoField,
  ResearchCreated,
  ResearchEvent,
  ResearchEvidence,
  ResearchList,
  ResearchReport,
} from '@arthalens/contracts';
import { loadPolicy } from '@arthalens/policy';
import { buildApp } from '../src/app.js';
import type { Identity } from '../src/identity.js';
import type { EventNotifier } from '../src/research/events.js';
import {
  DISCLAIMERS,
  IdempotencyConflict,
  NotFound,
  type ReportIpo,
  type ResearchRepository,
} from '../src/research/repository.js';
import type {
  AuditEvent,
  IpoIdentity,
  IpoRepository,
  ListedIpo,
  ListFilters,
} from '../src/ipos/repository.js';

export const OK: DependencyCheck = { status: 'ok', latency_ms: 1, detail: null };
export const DOWN = (detail: string): DependencyCheck => ({
  status: 'down',
  latency_ms: null,
  detail,
});

const SOURCE = {
  evidence_id: '00000000-0000-4000-8000-0000000000e1',
  url: 'https://fixtures.arthalens.test/alpha-notice.txt',
  title: '[SYNTHETIC] IPO notice',
  publisher: 'SYNTHETIC FIXTURE',
  published_at: '2026-10-10',
  authority: 'official_exchange',
  retrieval_method: 'mock_fixture',
  is_synthetic: true,
  version: 1,
  page: null,
} as const;

export function field(value: IpoField['value'], status: IpoField['status'] = 'verified'): IpoField {
  const verified = status === 'verified' || status === 'unverified';
  return {
    status,
    value: status === 'conflict' || status === 'unavailable' ? null : value,
    checked_at: '2026-10-18T06:00:00.000Z',
    source: verified ? SOURCE : null,
    quote: verified ? `quote for ${String(value)}` : null,
    note: null,
  };
}

export function ipo(id: string, name: string, extra: Partial<ListedIpo> = {}): ListedIpo {
  return {
    id,
    slug: name.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
    company_name: name,
    normalized_name: name.toLowerCase(),
    status: 'open',
    status_as_of: '2026-10-18',
    snapshot_version: 1,
    snapshot_created_at: '2026-10-18T06:00:00.000Z',
    is_synthetic: true,
    fields: { lot_size: field(50), price_band_low: field('28500') },
    ...extra,
  };
}

/** In-memory IpoRepository. `identities` can hold rows the list never returns (withdrawn). */
export class FakeIpoRepo implements IpoRepository {
  audits: AuditEvent[] = [];
  lastFilters: ListFilters | undefined;
  constructor(
    public rows: ListedIpo[] = [],
    public identities: IpoIdentity[] = [],
  ) {}

  async list(filters: ListFilters): Promise<ListedIpo[]> {
    this.lastFilters = filters;
    return this.rows.slice(0, filters.limit);
  }

  async identity(id: string): Promise<IpoIdentity | null> {
    const row = this.rows.find((r) => r.id === id);
    if (row) return { id, company_name: row.company_name, exclusion_status: 'allowed' };
    return this.identities.find((i) => i.id === id) ?? null;
  }

  async detail(id: string): Promise<IpoDetail | null> {
    const row = this.rows.find((r) => r.id === id);
    if (!row) return null;
    const { normalized_name: _n, ...rest } = row;
    return { ...rest, observations: [] };
  }

  async audit(event: AuditEvent): Promise<void> {
    this.audits.push(event);
  }
}

export const DEV = {
  tenantId: '00000000-0000-4000-8000-0000000000aa',
  userId: '00000000-0000-4000-8000-0000000000ab',
} as const;

interface StoredReport {
  owner: Identity;
  ipoId: string;
  companyName: string;
  exclusion: string;
  report: ResearchReport;
  events: ResearchEvent[];
  deleted: boolean;
}

/** In-memory ResearchRepository with the same ownership rules as the Postgres one. */
export class FakeResearchRepo implements ResearchRepository {
  reports = new Map<string, StoredReport>();
  keys = new Map<string, { ipoId: string; response: ResearchCreated }>();
  private n = 0;

  constructor(private readonly ipos: FakeIpoRepo) {}

  private own(identity: Identity, id: string): StoredReport | null {
    const r = this.reports.get(id);
    return r &&
      !r.deleted &&
      r.owner.tenantId === identity.tenantId &&
      r.owner.userId === identity.userId
      ? r
      : null;
  }

  async create(identity: Identity, ipoId: string, key?: string): Promise<ResearchCreated> {
    const scoped = key && `${identity.tenantId}:${identity.userId}:${key}`;
    if (scoped && this.keys.has(scoped)) {
      const prior = this.keys.get(scoped)!;
      if (prior.ipoId !== ipoId) throw new IdempotencyConflict('Idempotency-Key reused');
      return { ...prior.response, created: false };
    }
    const ipo = this.ipos.rows.find((r) => r.id === ipoId);
    if (!ipo) throw new NotFound('IPO has no snapshot to research');
    const id = `00000000-0000-4000-8000-${String(++this.n).padStart(12, '0')}`;
    this.reports.set(id, {
      owner: identity,
      ipoId,
      companyName: ipo.company_name,
      exclusion: 'allowed',
      deleted: false,
      events: [{ seq: 1, type: 'job.queued', payload: {}, created_at: '2026-10-18T06:00:00.000Z' }],
      report: {
        schema_version: 'research-report.v1',
        id,
        ipo_id: ipoId,
        company_name: ipo.company_name,
        snapshot_version: 1,
        status: 'pending',
        is_synthetic: true,
        created_at: '2026-10-18T06:00:00.000Z',
        started_at: null,
        completed_at: null,
        sections: [],
        disclaimers: DISCLAIMERS,
      },
    });
    const response: ResearchCreated = {
      report_id: id,
      status: 'pending',
      events_url: `/api/v1/research/${id}/events`,
      created: true,
    };
    if (scoped) this.keys.set(scoped, { ipoId, response });
    return response;
  }

  async reportIpo(identity: Identity, id: string): Promise<ReportIpo | null> {
    const r = this.own(identity, id);
    return r
      ? { ipo_id: r.ipoId, company_name: r.companyName, exclusion_status: r.exclusion }
      : null;
  }

  async report(identity: Identity, id: string) {
    return this.own(identity, id)?.report ?? null;
  }

  async list(identity: Identity, limit: number): Promise<ResearchList> {
    const items = [...this.reports.values()]
      .filter((r) => this.own(identity, r.report.id))
      .slice(0, limit)
      .map((r) => ({
        id: r.report.id,
        ipo_id: r.ipoId,
        company_name: r.companyName,
        status: r.report.status,
        created_at: r.report.created_at,
        completed_at: r.report.completed_at,
      }));
    return { schema_version: 'research-list.v1', items, next_cursor: null };
  }

  async events(identity: Identity, id: string, after: number) {
    return (this.own(identity, id)?.events ?? []).filter((e) => e.seq > after);
  }

  async evidence(identity: Identity, id: string): Promise<ResearchEvidence | null> {
    return this.own(identity, id)
      ? { schema_version: 'research-evidence.v1', report_id: id, items: [] }
      : null;
  }

  async softDelete(identity: Identity, id: string) {
    const r = this.own(identity, id);
    if (r) r.deleted = true;
    return Boolean(r);
  }

  /** Test helper: append an event the way the worker would. */
  push(id: string, type: string, payload: Record<string, unknown> = {}) {
    const r = this.reports.get(id)!;
    r.events.push({
      seq: r.events.length + 1,
      type,
      payload,
      created_at: '2026-10-18T06:00:01.000Z',
    });
  }
}

export class FakeNotifier implements EventNotifier {
  subs = new Map<string, Set<() => void>>();
  subscribe(id: string, cb: () => void) {
    const set = this.subs.get(id) ?? new Set();
    set.add(cb);
    this.subs.set(id, set);
    return () => set.delete(cb);
  }
  notify(id: string) {
    this.subs.get(id)?.forEach((cb) => cb());
  }
}

export async function testApp(
  opts: {
    db?: DependencyCheck;
    ai?: DependencyCheck;
    ipoRepo?: FakeIpoRepo;
    authMode?: 'dev' | 'none';
    heartbeatMs?: number;
  } = {},
) {
  const seenRequestIds: string[] = [];
  const ipoRepo = opts.ipoRepo ?? new FakeIpoRepo();
  const researchRepo = new FakeResearchRepo(ipoRepo);
  const notifier = new FakeNotifier();
  const app = await buildApp(
    { LOG_LEVEL: 'silent', NODE_ENV: 'test' },
    {
      health: {
        checkDatabase: async () => opts.db ?? OK,
        checkAi: async (requestId) => {
          seenRequestIds.push(requestId);
          return opts.ai ?? OK;
        },
      },
      ipos: { repo: ipoRepo, policy: loadPolicy() },
      research: {
        repo: researchRepo,
        notifier,
        policy: loadPolicy(),
        identity: {
          AUTH_MODE: opts.authMode ?? 'dev',
          DEV_TENANT_ID: DEV.tenantId,
          DEV_USER_ID: DEV.userId,
        },
        audit: (event) => ipoRepo.audit(event),
        heartbeatMs: opts.heartbeatMs ?? 50,
      },
    },
  );
  return { app, seenRequestIds, ipoRepo, researchRepo, notifier };
}
