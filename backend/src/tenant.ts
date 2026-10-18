import type pg from 'pg';
import type { Identity } from './identity.js';

/**
 * Run `fn` in one transaction scoped to the caller's tenant (ADR-0011). Row-level security uses
 * these settings, so every query inside sees only this tenant's rows. SET LOCAL semantics
 * (is_local = true) mean the values vanish at commit and can't leak to the next pool user.
 */
export async function withTenant<T>(
  pool: pg.Pool,
  identity: Identity,
  fn: (client: pg.PoolClient) => Promise<T>,
): Promise<T> {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    await client.query(
      "SELECT set_config('app.tenant_id', $1, true), set_config('app.user_id', $2, true)",
      [identity.tenantId, identity.userId],
    );
    const result = await fn(client);
    await client.query('COMMIT');
    return result;
  } catch (err) {
    await client.query('ROLLBACK').catch(() => undefined);
    throw err;
  } finally {
    client.release();
  }
}
