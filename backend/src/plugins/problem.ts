import type { FastifyError, FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import { STATUS_CODES } from 'node:http';

/** RFC 9457 problem details. Every error response from /api has this shape. */
export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance: string;
  request_id: string;
}

export function sendProblem(
  request: FastifyRequest,
  reply: FastifyReply,
  status: number,
  detail?: string,
): FastifyReply {
  const problem: Problem = {
    type: 'about:blank',
    title: STATUS_CODES[status] ?? 'Error',
    status,
    ...(detail === undefined ? {} : { detail }),
    instance: request.url,
    request_id: request.id,
  };
  return reply.code(status).type('application/problem+json').send(problem);
}

export function registerProblemHandlers(app: FastifyInstance): void {
  app.setNotFoundHandler((request, reply) => sendProblem(request, reply, 404));

  app.setErrorHandler((error: FastifyError, request, reply) => {
    const status = error.statusCode && error.statusCode >= 400 ? error.statusCode : 500;
    if (status >= 500) {
      // Full error goes to the log (with request id); the client gets nothing internal.
      request.log.error({ err: error }, 'unhandled error');
      return sendProblem(request, reply, status);
    }
    return sendProblem(request, reply, status, error.message);
  });
}
