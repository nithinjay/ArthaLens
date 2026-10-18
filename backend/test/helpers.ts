import type { DependencyCheck, IpoDetail, IpoField } from '@arthalens/contracts';
import { loadPolicy } from '@arthalens/policy';
import { buildApp } from '../src/app.js';
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

export async function testApp(
  opts: { db?: DependencyCheck; ai?: DependencyCheck; ipoRepo?: FakeIpoRepo } = {},
) {
  const seenRequestIds: string[] = [];
  const ipoRepo = opts.ipoRepo ?? new FakeIpoRepo();
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
    },
  );
  return { app, seenRequestIds, ipoRepo };
}
