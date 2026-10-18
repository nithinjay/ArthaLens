import { Ajv2020 } from 'ajv/dist/2020.js';
import { describe, expect, it } from 'vitest';
import { ServiceHealthSchema } from '@arthalens/contracts';
import { readinessStatus } from '../src/routes/health.js';
import { DOWN, OK, testApp } from './helpers.js';

const validate = new Ajv2020({ strict: false }).compile(ServiceHealthSchema);

describe('GET /healthz', () => {
  it('returns ok without checking dependencies', async () => {
    const { app, seenRequestIds } = await testApp({ db: DOWN('x'), ai: DOWN('x') });
    const res = await app.inject({ method: 'GET', url: '/healthz' });
    expect(res.statusCode).toBe(200);
    expect(validate(res.json())).toBe(true);
    expect(res.json()).toMatchObject({ service: 'backend', status: 'ok', checks: {} });
    expect(seenRequestIds).toHaveLength(0);
  });
});

describe.each(['/readyz', '/api/v1/health'])('GET %s', (url) => {
  it('is ok (200) when database and ai are up', async () => {
    const { app } = await testApp();
    const res = await app.inject({ method: 'GET', url });
    expect(res.statusCode).toBe(200);
    expect(validate(res.json())).toBe(true);
    expect(res.json().status).toBe('ok');
  });

  it('is degraded (200) when only ai is down', async () => {
    const { app } = await testApp({ ai: DOWN('ai service unreachable') });
    const res = await app.inject({ method: 'GET', url });
    expect(res.statusCode).toBe(200);
    expect(res.json().status).toBe('degraded');
    expect(res.json().checks.ai.detail).toBe('ai service unreachable');
  });

  it('is down (503) when the database is down', async () => {
    const { app } = await testApp({ db: DOWN('database unreachable') });
    const res = await app.inject({ method: 'GET', url });
    expect(res.statusCode).toBe(503);
    expect(validate(res.json())).toBe(true);
    expect(res.json().status).toBe('down');
  });
});

describe('readinessStatus', () => {
  it.each([
    [OK, OK, 'ok'],
    [OK, DOWN('a'), 'degraded'],
    [DOWN('d'), OK, 'down'],
    [DOWN('d'), DOWN('a'), 'down'],
  ] as const)('db=%j ai=%j → %s', (database, ai, expected) => {
    expect(readinessStatus({ database, ai })).toBe(expected);
  });

  it('treats a missing check as not ok', () => {
    expect(readinessStatus({})).toBe('down');
    expect(readinessStatus({ database: OK })).toBe('degraded');
  });
});

describe('response serialization', () => {
  it('strips fields not in the contract', async () => {
    const leaky = { ...OK, internal_host: 'db.internal:5432' } as typeof OK;
    const { app } = await testApp({ db: leaky });
    const res = await app.inject({ method: 'GET', url: '/readyz' });
    expect(res.body).not.toContain('db.internal');
  });
});
