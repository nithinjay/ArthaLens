import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import {
  ServiceHealthSchema,
  type DependencyCheck,
  type ServiceHealth,
} from '@arthalens/contracts';
import { VERSION } from '../version.js';

export interface HealthDeps {
  checkDatabase: () => Promise<DependencyCheck>;
  checkAi: (requestId: string) => Promise<DependencyCheck>;
}

const SCHEMA_REF = { $ref: `${ServiceHealthSchema.$id}#` } as const;

/**
 * Readiness rules:
 * - database down → `down` (503): the backend can't serve anything useful.
 * - ai down       → `degraded` (200): accounts, history and calculators still work;
 *                   only new research is affected.
 */
export function readinessStatus(checks: Record<string, DependencyCheck>): ServiceHealth['status'] {
  if (checks['database']?.status !== 'ok') return 'down';
  if (checks['ai']?.status !== 'ok') return 'degraded';
  return 'ok';
}

export async function healthRoutes(app: FastifyInstance, deps: HealthDeps): Promise<void> {
  const readiness = async (request: FastifyRequest): Promise<ServiceHealth> => {
    const [database, ai] = await Promise.all([deps.checkDatabase(), deps.checkAi(request.id)]);
    const checks = { database, ai };
    return {
      schema_version: 'service-health.v1',
      service: 'backend',
      status: readinessStatus(checks),
      version: VERSION,
      checks,
    };
  };

  app.get(
    '/healthz',
    { schema: { summary: 'Liveness', tags: ['health'], response: { 200: SCHEMA_REF } } },
    async (): Promise<ServiceHealth> => ({
      schema_version: 'service-health.v1',
      service: 'backend',
      status: 'ok',
      version: VERSION,
      checks: {},
    }),
  );

  const readyHandler = async (request: FastifyRequest, reply: FastifyReply) => {
    const health = await readiness(request);
    return reply.code(health.status === 'down' ? 503 : 200).send(health);
  };
  const readySchema = {
    tags: ['health'],
    response: { 200: SCHEMA_REF, 503: SCHEMA_REF },
  };

  app.get(
    '/readyz',
    { schema: { ...readySchema, summary: 'Readiness (infrastructure)' } },
    readyHandler,
  );
  app.get(
    '/api/v1/health',
    { schema: { ...readySchema, summary: 'Service status for the web UI' } },
    readyHandler,
  );
}
