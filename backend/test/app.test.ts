import { describe, expect, it } from 'vitest';
import { testApp } from './helpers.js';

describe('request ids', () => {
  it('propagates a well-formed incoming x-request-id to the response and the ai call', async () => {
    const { app, seenRequestIds } = await testApp();
    const res = await app.inject({
      method: 'GET',
      url: '/readyz',
      headers: { 'x-request-id': 'trace-12345678' },
    });
    expect(res.headers['x-request-id']).toBe('trace-12345678');
    expect(seenRequestIds).toEqual(['trace-12345678']);
  });

  it('replaces a malformed x-request-id', async () => {
    const { app } = await testApp();
    const res = await app.inject({
      method: 'GET',
      url: '/healthz',
      headers: { 'x-request-id': 'bad<script>' },
    });
    expect(res.headers['x-request-id']).toMatch(/^[0-9a-f-]{36}$/);
  });
});

describe('problem+json errors', () => {
  it('returns RFC 9457 problem details for unknown routes', async () => {
    const { app } = await testApp();
    const res = await app.inject({
      method: 'GET',
      url: '/api/v1/nope',
      headers: { 'x-request-id': 'trace-abcdefgh' },
    });
    expect(res.statusCode).toBe(404);
    expect(res.headers['content-type']).toMatch(/^application\/problem\+json/);
    expect(res.json()).toEqual({
      type: 'about:blank',
      title: 'Not Found',
      status: 404,
      instance: '/api/v1/nope',
      request_id: 'trace-abcdefgh',
    });
  });

  it('hides internal error details on 500', async () => {
    const { app } = await testApp();
    app.get('/boom', async () => {
      throw new Error('secret internal detail');
    });
    const res = await app.inject({ method: 'GET', url: '/boom' });
    expect(res.statusCode).toBe(500);
    expect(res.json().title).toBe('Internal Server Error');
    expect(res.body).not.toContain('secret internal detail');
  });
});

describe('security headers', () => {
  it('sets helmet headers on API responses', async () => {
    const { app } = await testApp();
    const res = await app.inject({ method: 'GET', url: '/healthz' });
    expect(res.headers['x-content-type-options']).toBe('nosniff');
    expect(res.headers['content-security-policy']).toContain("default-src 'none'");
  });
});

describe('OpenAPI', () => {
  it('publishes an OpenAPI 3.1 document including the health routes', async () => {
    const { app } = await testApp();
    const res = await app.inject({ method: 'GET', url: '/api/v1/openapi.json' });
    expect(res.statusCode).toBe(200);
    const doc = res.json();
    expect(doc.openapi).toBe('3.1.0');
    expect(Object.keys(doc.paths)).toEqual(
      expect.arrayContaining(['/healthz', '/readyz', '/api/v1/health']),
    );
  });
});
