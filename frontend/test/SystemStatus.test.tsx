import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ServiceHealth } from '@arthalens/contracts';
import { SystemStatus } from '../src/SystemStatus';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderWithFetch(response: Response | Error) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      if (response instanceof Error) throw response;
      return response;
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SystemStatus />
    </QueryClientProvider>,
  );
}

const health = (overrides: Partial<ServiceHealth>): ServiceHealth => ({
  schema_version: 'service-health.v1',
  service: 'backend',
  status: 'ok',
  version: '0.1.0',
  checks: {
    database: { status: 'ok', latency_ms: 3, detail: null },
    ai: { status: 'ok', latency_ms: 5, detail: null },
  },
  ...overrides,
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

describe('SystemStatus', () => {
  it('shows a loading state first', () => {
    renderWithFetch(json(health({})));
    expect(screen.getByRole('status').textContent).toMatch(/Checking services/);
  });

  it('shows all dependencies when healthy', async () => {
    renderWithFetch(json(health({})));
    expect(await screen.findByText('All systems operational')).toBeTruthy();
    expect(screen.getByText(/Database: OK/)).toBeTruthy();
    expect(screen.getByText(/Research service: OK/)).toBeTruthy();
  });

  it('shows a degraded state with the failing dependency', async () => {
    renderWithFetch(
      json(
        health({
          status: 'degraded',
          checks: {
            database: { status: 'ok', latency_ms: 3, detail: null },
            ai: { status: 'down', latency_ms: null, detail: 'ai service unreachable' },
          },
        }),
      ),
    );
    expect(await screen.findByText('Partially available')).toBeTruthy();
    expect(screen.getByText(/Research service: Down/)).toBeTruthy();
    expect(screen.getByText(/ai service unreachable/)).toBeTruthy();
  });

  it('treats a 503 with a health body as data, not an error', async () => {
    renderWithFetch(json(health({ status: 'down' }), 503));
    expect(await screen.findByText('Unavailable')).toBeTruthy();
  });

  it('shows an error with retry when the API is unreachable', async () => {
    renderWithFetch(new TypeError('Failed to fetch'));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/Could not reach/);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
  });
});
