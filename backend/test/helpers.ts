import type { DependencyCheck } from '@arthalens/contracts';
import { buildApp } from '../src/app.js';

export const OK: DependencyCheck = { status: 'ok', latency_ms: 1, detail: null };
export const DOWN = (detail: string): DependencyCheck => ({
  status: 'down',
  latency_ms: null,
  detail,
});

export async function testApp(opts: { db?: DependencyCheck; ai?: DependencyCheck } = {}) {
  const seenRequestIds: string[] = [];
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
    },
  );
  return { app, seenRequestIds };
}
