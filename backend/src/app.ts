import Fastify, { type FastifyInstance } from 'fastify';
import helmet from '@fastify/helmet';
import swagger from '@fastify/swagger';
import { randomUUID } from 'node:crypto';
import type { IncomingMessage } from 'node:http';
import { IpoDetailSchema, IpoListSchema, ServiceHealthSchema } from '@arthalens/contracts';
import type { Config } from './config.js';
import { registerProblemHandlers } from './plugins/problem.js';
import { ipoRoutes, type IpoRouteDeps } from './ipos/routes.js';
import { healthRoutes, type HealthDeps } from './routes/health.js';
import { VERSION } from './version.js';

const REQUEST_ID_HEADER = 'x-request-id';
const REQUEST_ID_PATTERN = /^[A-Za-z0-9-]{8,64}$/;

/** Reuse a well-formed incoming request id (for cross-service tracing); otherwise mint one. */
export function requestIdFor(req: IncomingMessage): string {
  const incoming = req.headers[REQUEST_ID_HEADER];
  return typeof incoming === 'string' && REQUEST_ID_PATTERN.test(incoming)
    ? incoming
    : randomUUID();
}

export interface AppDeps {
  health: HealthDeps;
  ipos: IpoRouteDeps;
}

export async function buildApp(
  config: Pick<Config, 'LOG_LEVEL' | 'NODE_ENV'>,
  deps: AppDeps,
): Promise<FastifyInstance> {
  const app = Fastify({
    logger: {
      level: config.LOG_LEVEL,
      // Never log credentials, even at debug level.
      redact: {
        paths: ['req.headers.authorization', 'req.headers.cookie', 'res.headers["set-cookie"]'],
        censor: '[REDACTED]',
      },
    },
    genReqId: requestIdFor,
    requestIdHeader: false,
    trustProxy: false,
  });

  app.addHook('onSend', async (request, reply) => {
    reply.header(REQUEST_ID_HEADER, request.id);
  });

  await app.register(helmet, {
    // The API returns JSON only; the frontend sets its own CSP for HTML.
    contentSecurityPolicy: { directives: { defaultSrc: ["'none'"], frameAncestors: ["'none'"] } },
  });

  await app.register(swagger, {
    openapi: {
      openapi: '3.1.0',
      info: {
        title: 'ArthaLens API',
        version: VERSION,
        description: 'Educational IPO research API. Not investment advice.',
      },
    },
  });

  app.addSchema(ServiceHealthSchema);
  app.addSchema(IpoListSchema);
  app.addSchema(IpoDetailSchema);
  registerProblemHandlers(app);

  await app.register(async (scope) => healthRoutes(scope, deps.health));
  await app.register(async (scope) => ipoRoutes(scope, deps.ipos));

  app.get('/api/v1/openapi.json', { schema: { hide: true } }, async () => app.swagger());

  return app;
}
