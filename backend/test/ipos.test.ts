import { Ajv2020 } from 'ajv/dist/2020.js';
import { describe, expect, it } from 'vitest';
import { IpoDetailSchema, IpoListSchema } from '@arthalens/contracts';
import { decodeCursor, encodeCursor } from '../src/ipos/routes.js';
import { escapeLike } from '../src/ipos/repository.js';
import { FakeIpoRepo, field, ipo, testApp } from './helpers.js';

const ajv = new Ajv2020({ strict: false });
const validList = ajv.compile(IpoListSchema);
const validDetail = ajv.compile(IpoDetailSchema);

const ALPHA = '00000000-0000-4000-8000-00000000000a';
const BETA = '00000000-0000-4000-8000-00000000000b';
const WITHDRAWN = '00000000-0000-4000-8000-0000000000dd';

describe('GET /api/v1/ipos', () => {
  it('returns IPOs with per-field provenance, matching the contract', async () => {
    const { app } = await testApp({ ipoRepo: new FakeIpoRepo([ipo(ALPHA, 'Synthetic Alpha')]) });
    const res = await app.inject({ method: 'GET', url: '/api/v1/ipos' });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(validList(body)).toBe(true);
    expect(body.items[0].fields.lot_size).toMatchObject({
      status: 'verified',
      value: 50,
      source: { publisher: 'SYNTHETIC FIXTURE', is_synthetic: true },
    });
    expect(body.notice).toBeNull();
  });

  it('never serialises internal columns', async () => {
    const { app } = await testApp({ ipoRepo: new FakeIpoRepo([ipo(ALPHA, 'Synthetic Alpha')]) });
    const res = await app.inject({ method: 'GET', url: '/api/v1/ipos' });
    expect(res.body).not.toContain('normalized_name');
  });

  it('passes filters through with the search normalised', async () => {
    const repo = new FakeIpoRepo();
    const { app } = await testApp({ ipoRepo: repo });
    await app.inject({
      method: 'GET',
      url: '/api/v1/ipos?status=open&issue_type=sme&exchange=NSE&q=Alpha%20FOODS&limit=5',
    });
    expect(repo.lastFilters).toEqual({
      status: 'open',
      issueType: 'sme',
      exchange: 'NSE',
      nameContains: 'alpha foods',
      limit: 6, // one extra row to know whether another page exists
    });
  });

  it.each([
    'status=bogus',
    'exchange=NYSE',
    'limit=0',
    'limit=101',
    `q=${'x'.repeat(101)}`,
    'cursor=not!valid',
  ])('rejects invalid query %s with problem+json', async (qs) => {
    const { app } = await testApp();
    const res = await app.inject({ method: 'GET', url: `/api/v1/ipos?${qs}` });
    expect(res.statusCode).toBe(400);
    expect(res.headers['content-type']).toMatch(/problem\+json/);
  });

  it('rejects a well-formed but undecodable cursor', async () => {
    const { app } = await testApp();
    const res = await app.inject({ method: 'GET', url: '/api/v1/ipos?cursor=abc' });
    expect(res.statusCode).toBe(400);
    expect(res.json().detail).toBe('invalid cursor');
  });

  it('paginates with a cursor from the last item', async () => {
    const repo = new FakeIpoRepo([ipo(ALPHA, 'Synthetic Alpha'), ipo(BETA, 'Synthetic Beta')]);
    const { app } = await testApp({ ipoRepo: repo });
    const res = await app.inject({ method: 'GET', url: '/api/v1/ipos?limit=1' });
    const body = res.json();
    expect(body.items).toHaveLength(1);
    expect(decodeCursor(body.next_cursor)).toEqual({
      normalizedName: 'synthetic alpha',
      id: ALPHA,
    });
  });
});

describe('Jio exclusion at the API (layer L3)', () => {
  it.each(['jio', 'Jio Platforms', 'RELIANCE JIO', 'J1O Platforms', 'jiomart'])(
    'search for %j returns a notice and no items',
    async (term) => {
      const repo = new FakeIpoRepo([ipo(ALPHA, 'Synthetic Alpha')]);
      const { app } = await testApp({ ipoRepo: repo });
      const res = await app.inject({
        method: 'GET',
        url: `/api/v1/ipos?q=${encodeURIComponent(term)}`,
      });
      expect(res.statusCode).toBe(200);
      const body = res.json();
      expect(validList(body)).toBe(true);
      expect(body.items).toEqual([]);
      expect(body.notice).toMatchObject({ code: 'ENTITY_EXCLUDED' });
      expect(repo.lastFilters).toBeUndefined(); // the database was never queried
    },
  );

  it('drops a matching row even if the repository returns one', async () => {
    const leaked = ipo('00000000-0000-4000-8000-0000000000ff', 'Jio Platforms Limited');
    const repo = new FakeIpoRepo([ipo(ALPHA, 'Synthetic Alpha'), leaked]);
    const { app } = await testApp({ ipoRepo: repo });
    const res = await app.inject({ method: 'GET', url: '/api/v1/ipos' });
    expect(res.json().items.map((i: { id: string }) => i.id)).toEqual([ALPHA]);
  });

  it('blocks direct access to an IPO withdrawn by policy, and audits it', async () => {
    const repo = new FakeIpoRepo(
      [],
      [{ id: WITHDRAWN, company_name: 'Renamed Entity', exclusion_status: 'withdrawn_by_policy' }],
    );
    const { app } = await testApp({ ipoRepo: repo });
    const res = await app.inject({ method: 'GET', url: `/api/v1/ipos/${WITHDRAWN}` });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toMatchObject({ code: 'ENTITY_EXCLUDED', status: 403 });
    expect(res.json().detail).toMatch(/excluded from ArthaLens/);
    expect(repo.audits).toEqual([
      expect.objectContaining({
        action: 'policy.exclusion_blocked',
        target_id: WITHDRAWN,
        metadata: expect.objectContaining({ layer: 'api' }),
      }),
    ]);
  });

  it('blocks a stored IPO whose name the current policy matches', async () => {
    const id = '00000000-0000-4000-8000-0000000000ee';
    const repo = new FakeIpoRepo(
      [],
      [{ id, company_name: 'Jio Platforms Limited', exclusion_status: 'allowed' }],
    );
    const { app } = await testApp({ ipoRepo: repo });
    const res = await app.inject({ method: 'GET', url: `/api/v1/ipos/${id}` });
    expect(res.statusCode).toBe(403);
    expect(res.json().code).toBe('ENTITY_EXCLUDED');
  });

  it('guards every route registered in the per-IPO scope, not just detail', async () => {
    const repo = new FakeIpoRepo(
      [],
      [{ id: WITHDRAWN, company_name: 'X', exclusion_status: 'withdrawn_by_policy' }],
    );
    const { app } = await testApp({ ipoRepo: repo });
    // Research (M4) and calculator (M7) routes will live under this path in the same scope;
    // unknown sub-paths must never fall through to an unguarded handler.
    const res = await app.inject({ method: 'POST', url: `/api/v1/ipos/${WITHDRAWN}/research` });
    expect([403, 404]).toContain(res.statusCode);
    expect(res.body).not.toContain('"items"');
  });
});

describe('GET /api/v1/ipos/:ipoId', () => {
  it('returns detail matching the contract', async () => {
    const repo = new FakeIpoRepo([
      ipo(ALPHA, 'Synthetic Alpha', {
        fields: { lot_size: field(null, 'conflict'), ofs_size: field(null, 'unavailable') },
      }),
    ]);
    const { app } = await testApp({ ipoRepo: repo });
    const res = await app.inject({ method: 'GET', url: `/api/v1/ipos/${ALPHA}` });
    expect(res.statusCode).toBe(200);
    expect(validDetail(res.json())).toBe(true);
    expect(res.json().fields.lot_size).toMatchObject({ status: 'conflict', value: null });
  });

  it('404s an unknown id', async () => {
    const { app } = await testApp();
    const res = await app.inject({ method: 'GET', url: `/api/v1/ipos/${BETA}` });
    expect(res.statusCode).toBe(404);
  });

  it('400s a malformed id before touching the repository', async () => {
    const { app } = await testApp();
    const res = await app.inject({ method: 'GET', url: "/api/v1/ipos/1'%20OR%201=1" });
    expect(res.statusCode).toBe(400);
  });
});

describe('helpers', () => {
  it('round-trips cursors and rejects tampered ones', () => {
    const c = encodeCursor('synthetic alpha', ALPHA);
    expect(decodeCursor(c)).toEqual({ normalizedName: 'synthetic alpha', id: ALPHA });
    expect(decodeCursor(Buffer.from('["x","not-a-uuid"]').toString('base64url'))).toBeNull();
    expect(decodeCursor('%%%')).toBeNull();
  });

  it('escapes LIKE wildcards', () => {
    expect(escapeLike('50%_off\\')).toBe('50\\%\\_off\\\\');
  });
});
