import { createServer, type IncomingHttpHeaders, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { afterEach, describe, expect, it } from 'vitest';
import { AiClient } from '../src/aiClient.js';

const TOKEN = 't'.repeat(40); // synthetic test value

const healthyBody = {
  schema_version: 'service-health.v1',
  service: 'ai',
  status: 'ok',
  version: '0.1.0',
  checks: { database: { status: 'ok', latency_ms: 1, detail: null } },
};

let server: Server | undefined;
afterEach(() => server?.close());

/** Start a real HTTP server standing in for the AI service. */
async function fakeAi(
  handler: (headers: IncomingHttpHeaders) => { status: number; body: string; delayMs?: number },
): Promise<{ url: string; requests: IncomingHttpHeaders[] }> {
  const requests: IncomingHttpHeaders[] = [];
  server = createServer((req, res) => {
    requests.push(req.headers);
    const { status, body, delayMs = 0 } = handler(req.headers);
    setTimeout(() => {
      res.writeHead(status, { 'content-type': 'application/json' }).end(body);
    }, delayMs);
  });
  await new Promise<void>((resolve) => server!.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as AddressInfo;
  return { url: `http://127.0.0.1:${port}`, requests };
}

const client = (url: string, timeoutMs = 1000) =>
  new AiClient({ baseUrl: url, serviceToken: TOKEN, timeoutMs });

describe('AiClient.checkHealth', () => {
  it('sends the bearer token and request id, and reports ok', async () => {
    const ai = await fakeAi((h) =>
      h.authorization === `Bearer ${TOKEN}`
        ? { status: 200, body: JSON.stringify(healthyBody) }
        : { status: 401, body: '{}' },
    );
    const result = await client(ai.url).checkHealth('trace-12345678');
    expect(result.status).toBe('ok');
    expect(ai.requests[0]?.['x-request-id']).toBe('trace-12345678');
  });

  it('reports rejected credentials on 401', async () => {
    const ai = await fakeAi(() => ({ status: 401, body: '{"detail":"nope"}' }));
    const result = await client(ai.url).checkHealth('trace-12345678');
    expect(result).toEqual({
      status: 'down',
      latency_ms: null,
      detail: 'ai service rejected service credentials',
    });
  });

  it('reports not ready when the ai service is up but its database is down', async () => {
    const body = {
      ...healthyBody,
      status: 'down',
      checks: { database: { status: 'down', latency_ms: null, detail: 'database unreachable' } },
    };
    const ai = await fakeAi(() => ({ status: 503, body: JSON.stringify(body) }));
    expect((await client(ai.url).checkHealth('trace-12345678')).detail).toBe(
      'ai service not ready',
    );
  });

  it.each([
    ['non-JSON', 'not json'],
    ['wrong shape', JSON.stringify({ hello: 'world' })],
    ['extra fields', JSON.stringify({ ...healthyBody, injected: true })],
  ])('rejects a %s response', async (_label, body) => {
    const ai = await fakeAi(() => ({ status: 200, body }));
    expect((await client(ai.url).checkHealth('trace-12345678')).detail).toBe(
      'ai service returned invalid response',
    );
  });

  it('times out instead of hanging', async () => {
    const ai = await fakeAi(() => ({
      status: 200,
      body: JSON.stringify(healthyBody),
      delayMs: 500,
    }));
    const started = Date.now();
    const result = await client(ai.url, 100).checkHealth('trace-12345678');
    expect(result.detail).toBe('ai service unreachable');
    expect(Date.now() - started).toBeLessThan(400);
  });

  it('reports unreachable when nothing is listening', async () => {
    const result = await client('http://127.0.0.1:1').checkHealth('trace-12345678');
    expect(result.detail).toBe('ai service unreachable');
  });

  it('never includes the token in its result', async () => {
    const ai = await fakeAi(() => ({ status: 401, body: '{}' }));
    const result = await client(ai.url).checkHealth('trace-12345678');
    expect(JSON.stringify(result)).not.toContain(TOKEN);
  });
});
