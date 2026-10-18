import type { FastifyReply, FastifyRequest } from 'fastify';
import type { Config } from './config.js';
import { sendProblem } from './plugins/problem.js';

/** Who is making the request. Always derived server-side; never taken from the client. */
export interface Identity {
  tenantId: string;
  userId: string;
  /** 'dev' until Milestone 8 replaces it with real sessions (ADR-0010). */
  kind: 'dev';
}

declare module 'fastify' {
  interface FastifyRequest {
    identity?: Identity;
  }
}

export type IdentityConfig = Pick<Config, 'AUTH_MODE' | 'DEV_TENANT_ID' | 'DEV_USER_ID'>;

/** preHandler for routes that need a signed-in user. */
export function requireIdentity(config: IdentityConfig) {
  return async (request: FastifyRequest, reply: FastifyReply): Promise<void> => {
    if (config.AUTH_MODE === 'dev' && config.DEV_TENANT_ID && config.DEV_USER_ID) {
      request.identity = {
        tenantId: config.DEV_TENANT_ID,
        userId: config.DEV_USER_ID,
        kind: 'dev',
      };
      return;
    }
    await sendProblem(
      request,
      reply,
      401,
      'Sign-in is required (not available until Milestone 8).',
    );
  };
}

export function identityOf(request: FastifyRequest): Identity {
  if (!request.identity)
    throw new Error('identity missing: route registered without requireIdentity');
  return request.identity;
}
