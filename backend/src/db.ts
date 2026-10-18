import pg from 'pg';
import type { DependencyCheck } from '@arthalens/contracts';

/**
 * Connection pool for the `app_api` role. Repositories and tenant-scoped transactions
 * (SET LOCAL app.tenant_id, ADR-0011) arrive with the first user-facing tables in Milestone 8.
 */
export function createPool(databaseUrl: string, timeoutMs: number): pg.Pool {
  return new pg.Pool({
    connectionString: databaseUrl,
    max: 10,
    connectionTimeoutMillis: timeoutMs,
    statement_timeout: timeoutMs,
  });
}

export async function checkDatabase(pool: pg.Pool): Promise<DependencyCheck> {
  const started = performance.now();
  try {
    await pool.query('SELECT 1');
    return { status: 'ok', latency_ms: Math.round(performance.now() - started), detail: null };
  } catch {
    // Driver errors can include host names; callers only get a generic message.
    return { status: 'down', latency_ms: null, detail: 'database unreachable' };
  }
}
