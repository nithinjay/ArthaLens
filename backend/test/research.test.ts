import type { AddressInfo } from 'node:net';
import { Ajv2020 } from 'ajv/dist/2020.js';
import { afterEach, describe, expect, it } from 'vitest';
import { ResearchCreatedSchema, ResearchReportSchema } from '@arthalens/contracts';
import { DEV, FakeIpoRepo, ipo, testApp } from './helpers.js';

const ajv = new Ajv2020({ strict: false });
const validCreated = ajv.compile(ResearchCreatedSchema);
const validReport = ajv.compile(ResearchReportSchema);

const ALPHA = '00000000-0000-4000-8000-00000000000a';
const WITHDRAWN = '00000000-0000-4000-8000-0000000000dd';

async function appWithAlpha(opts: Parameters<typeof testApp>[0] = {}) {
  return testApp({ ipoRepo: new FakeIpoRepo([ipo(ALPHA, 'Synthetic Alpha')]), ...opts });
}

describe('POST /api/v1/ipos/:ipoId/research', () => {
  it('creates a report and returns 202 with the events url', async () => {
    const { app } = await appWithAlpha();
    const res = await app.inject({ method: 'POST', url: `/api/v1/ipos/${ALPHA}/research` });
    expect(res.statusCode).toBe(202);
    expect(validCreated(res.json())).toBe(true);
    expect(res.json()).toMatchObject({ created: true, status: 'pending' });
    expect(res.json().events_url).toBe(`/api/v1/research/${res.json().report_id}/events`);
  });

  it('replays the same report for the same Idempotency-Key', async () => {
    const { app, researchRepo } = await appWithAlpha();
    const send = () =>
      app.inject({
        method: 'POST',
        url: `/api/v1/ipos/${ALPHA}/research`,
        headers: { 'idempotency-key': 'retry-key-0001' },
      });
    const first = await send();
    const second = await send();
    expect(first.statusCode).toBe(202);
    expect(second.statusCode).toBe(200);
    expect(second.json()).toMatchObject({ report_id: first.json().report_id, created: false });
    expect(researchRepo.reports.size).toBe(1);
  });

  it('rejects reusing a key for a different IPO (409)', async () => {
    const other = '00000000-0000-4000-8000-00000000000b';
    const { app } = await testApp({
      ipoRepo: new FakeIpoRepo([ipo(ALPHA, 'Synthetic Alpha'), ipo(other, 'Synthetic Beta')]),
    });
    const headers = { 'idempotency-key': 'shared-key-0001' };
    await app.inject({ method: 'POST', url: `/api/v1/ipos/${ALPHA}/research`, headers });
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/ipos/${other}/research`,
      headers,
    });
    expect(res.statusCode).toBe(409);
  });

  it('rejects a malformed Idempotency-Key', async () => {
    const { app } = await appWithAlpha();
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/ipos/${ALPHA}/research`,
      headers: { 'idempotency-key': 'bad key!' },
    });
    expect(res.statusCode).toBe(400);
  });

  it('is behind the IPO exclusion guard', async () => {
    const repo = new FakeIpoRepo(
      [],
      [{ id: WITHDRAWN, company_name: 'X', exclusion_status: 'withdrawn_by_policy' }],
    );
    const { app, researchRepo } = await testApp({ ipoRepo: repo });
    const res = await app.inject({ method: 'POST', url: `/api/v1/ipos/${WITHDRAWN}/research` });
    expect(res.statusCode).toBe(403);
    expect(res.json().code).toBe('ENTITY_EXCLUDED');
    expect(researchRepo.reports.size).toBe(0);
  });

  it('requires an identity (401 until sign-in exists)', async () => {
    const { app } = await appWithAlpha({ authMode: 'none' });
    const res = await app.inject({ method: 'POST', url: `/api/v1/ipos/${ALPHA}/research` });
    expect(res.statusCode).toBe(401);
  });

  it('ignores any user or tenant id the client sends', async () => {
    const { app, researchRepo } = await appWithAlpha();
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/ipos/${ALPHA}/research?tenant_id=evil`,
      headers: { 'x-tenant-id': 'evil', 'x-user-id': 'evil' },
      payload: { tenant_id: 'evil', user_id: 'evil' },
    });
    expect(res.statusCode).toBe(202);
    const stored = researchRepo.reports.get(res.json().report_id)!;
    expect(stored.owner).toMatchObject({ tenantId: DEV.tenantId, userId: DEV.userId });
  });
});

describe('GET /api/v1/research/:reportId', () => {
  it('returns the report, matching the contract', async () => {
    const { app } = await appWithAlpha();
    const id = (await app.inject({ method: 'POST', url: `/api/v1/ipos/${ALPHA}/research` })).json()
      .report_id;
    const res = await app.inject({ method: 'GET', url: `/api/v1/research/${id}` });
    expect(res.statusCode).toBe(200);
    expect(validReport(res.json())).toBe(true);
    expect(res.json().disclaimers[0]).toMatch(/not investment advice/);
  });

  it("404s another user's report exactly like a missing one", async () => {
    const { app, researchRepo } = await appWithAlpha();
    const id = (await app.inject({ method: 'POST', url: `/api/v1/ipos/${ALPHA}/research` })).json()
      .report_id;
    researchRepo.reports.get(id)!.owner = {
      tenantId: DEV.tenantId,
      userId: 'someone-else',
      kind: 'dev',
    };
    const theirs = await app.inject({ method: 'GET', url: `/api/v1/research/${id}` });
    const missing = await app.inject({
      method: 'GET',
      url: '/api/v1/research/00000000-0000-4000-8000-000000000999',
    });
    expect(theirs.statusCode).toBe(404);
    expect(theirs.json().detail).toBe(missing.json().detail);
  });

  it('blocks a report whose IPO was later withdrawn by policy', async () => {
    const { app, researchRepo, ipoRepo } = await appWithAlpha();
    const id = (await app.inject({ method: 'POST', url: `/api/v1/ipos/${ALPHA}/research` })).json()
      .report_id;
    researchRepo.reports.get(id)!.exclusion = 'withdrawn_by_policy';
    for (const path of ['', '/events', '/evidence']) {
      const res = await app.inject({ method: 'GET', url: `/api/v1/research/${id}${path}` });
      expect(res.statusCode).toBe(403);
    }
    expect(ipoRepo.audits.map((a) => a.target_type)).toContain('research_report');
  });

  it('lets the owner delete a report even after its IPO is excluded (review #8)', async () => {
    const { app, researchRepo } = await appWithAlpha();
    const id = (await app.inject({ method: 'POST', url: `/api/v1/ipos/${ALPHA}/research` })).json()
      .report_id;
    researchRepo.reports.get(id)!.exclusion = 'withdrawn_by_policy';
    expect((await app.inject({ method: 'GET', url: `/api/v1/research/${id}` })).statusCode).toBe(
      403,
    );
    expect((await app.inject({ method: 'DELETE', url: `/api/v1/research/${id}` })).statusCode).toBe(
      204,
    );
  });

  it("still refuses to delete someone else's report", async () => {
    const { app, researchRepo } = await appWithAlpha();
    const id = (await app.inject({ method: 'POST', url: `/api/v1/ipos/${ALPHA}/research` })).json()
      .report_id;
    researchRepo.reports.get(id)!.owner = { tenantId: 'other', userId: 'other', kind: 'dev' };
    expect((await app.inject({ method: 'DELETE', url: `/api/v1/research/${id}` })).statusCode).toBe(
      404,
    );
    expect(researchRepo.reports.get(id)!.deleted).toBe(false);
  });

  it.each([
    ['not base64 json', 'abc'],
    ['bad timestamp', Buffer.from(JSON.stringify(['yesterday', ALPHA])).toString('base64url')],
    [
      'bad id',
      Buffer.from(JSON.stringify(['2026-10-18 06:00:00.123456+00', 'x'])).toString('base64url'),
    ],
  ])('rejects a malformed history cursor: %s (review #6)', async (_label, cursor) => {
    const { app } = await appWithAlpha();
    const res = await app.inject({ method: 'GET', url: `/api/v1/research?cursor=${cursor}` });
    expect(res.statusCode).toBe(400);
  });

  it('soft-deletes, then hides the report', async () => {
    const { app } = await appWithAlpha();
    const id = (await app.inject({ method: 'POST', url: `/api/v1/ipos/${ALPHA}/research` })).json()
      .report_id;
    expect((await app.inject({ method: 'DELETE', url: `/api/v1/research/${id}` })).statusCode).toBe(
      204,
    );
    expect((await app.inject({ method: 'GET', url: `/api/v1/research/${id}` })).statusCode).toBe(
      404,
    );
    const list = await app.inject({ method: 'GET', url: '/api/v1/research' });
    expect(list.json().items).toEqual([]);
  });
});

// --- SSE: needs a real socket, because inject() can't stream -------------------------------

const servers: { close: () => Promise<void> }[] = [];
afterEach(async () => {
  await Promise.all(servers.splice(0).map((s) => s.close()));
});

async function live(opts: Parameters<typeof testApp>[0] = {}) {
  const ctx = await appWithAlpha(opts);
  await ctx.app.listen({ port: 0, host: '127.0.0.1' });
  servers.push(ctx.app);
  const { port } = ctx.app.server.address() as AddressInfo;
  const create = await ctx.app.inject({ method: 'POST', url: `/api/v1/ipos/${ALPHA}/research` });
  return { ...ctx, base: `http://127.0.0.1:${port}`, id: create.json().report_id as string };
}

/** Read an SSE stream until it ends (or `stopAfter` events), returning parsed frames. */
async function readStream(url: string, headers: Record<string, string> = {}, stopAfter = Infinity) {
  const res = await fetch(url, { headers });
  const frames: { id: number; event: string; data: { seq: number; type: string } }[] = [];
  const decoder = new TextDecoder();
  let buffer = '';
  const reader = res.body!.getReader();
  while (frames.length < stopAfter) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut: number;
    while ((cut = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      if (block.startsWith(':')) continue; // heartbeat
      const field = (name: string) => block.match(new RegExp(`^${name}: (.*)$`, 'm'))?.[1] ?? '';
      frames.push({
        id: Number(field('id')),
        event: field('event'),
        data: JSON.parse(field('data')),
      });
    }
  }
  await reader.cancel().catch(() => undefined);
  return { res, frames };
}

describe('GET /api/v1/research/:reportId/events (SSE)', () => {
  it('replays history, follows live events in order, and closes after the terminal event', async () => {
    const { base, id, researchRepo, notifier } = await live();
    researchRepo.push(id, 'job.started');
    const reading = readStream(`${base}/api/v1/research/${id}/events`);
    setTimeout(() => {
      researchRepo.push(id, 'section.completed', { section: 'A' });
      notifier.notify(id);
      researchRepo.push(id, 'job.completed', { status: 'completed_degraded' });
      notifier.notify(id);
    }, 30);
    const { res, frames } = await reading;
    expect(res.headers.get('content-type')).toMatch(/^text\/event-stream/);
    expect(frames.map((f) => [f.id, f.event])).toEqual([
      [1, 'job.queued'],
      [2, 'job.started'],
      [3, 'section.completed'],
      [4, 'job.completed'],
    ]);
  });

  it('resumes after Last-Event-ID with no gaps or duplicates', async () => {
    const { base, id, researchRepo } = await live();
    for (const t of ['job.started', 'evidence.ready', 'section.completed', 'job.completed']) {
      researchRepo.push(id, t);
    }
    const { frames } = await readStream(`${base}/api/v1/research/${id}/events`, {
      'last-event-id': '2',
    });
    expect(frames.map((f) => f.id)).toEqual([3, 4, 5]);
  });

  it('a reload after completion shows the final state and ends', async () => {
    const { base, id, researchRepo } = await live();
    researchRepo.finish(id);
    const { frames } = await readStream(`${base}/api/v1/research/${id}/events`);
    expect(frames.at(-1)?.event).toBe('job.completed');
  });

  it('keeps delivering through heartbeats even if a notification is missed', async () => {
    const { base, id, researchRepo } = await live({ heartbeatMs: 20 });
    const reading = readStream(`${base}/api/v1/research/${id}/events`);
    setTimeout(() => researchRepo.push(id, 'job.completed'), 40); // no notify() at all
    const { frames } = await reading;
    expect(frames.at(-1)?.event).toBe('job.completed');
  });

  it('resuming after the terminal event closes at once instead of hanging (review #5)', async () => {
    const { base, id, researchRepo } = await live({ heartbeatMs: 10_000 });
    researchRepo.finish(id); // events 1 (queued) and 2 (completed)
    const started = Date.now();
    const { frames } = await readStream(`${base}/api/v1/research/${id}/events`, {
      'last-event-id': '2',
    });
    expect(frames).toEqual([]);
    expect(Date.now() - started).toBeLessThan(2_000); // didn't wait for a heartbeat
  });

  it('a report that is final without a terminal event in sight still closes (review #5)', async () => {
    const { base, id, researchRepo } = await live({ heartbeatMs: 10_000 });
    researchRepo.reports.get(id)!.report.status = 'failed';
    const { frames } = await readStream(`${base}/api/v1/research/${id}/events`);
    expect(frames.map((f) => f.event)).toEqual(['job.queued']);
  });

  it("does not stream another user's report", async () => {
    const { base, id, researchRepo } = await live();
    researchRepo.reports.get(id)!.owner = { tenantId: 'other', userId: 'other', kind: 'dev' };
    const res = await fetch(`${base}/api/v1/research/${id}/events`);
    expect(res.status).toBe(404);
  });
});
