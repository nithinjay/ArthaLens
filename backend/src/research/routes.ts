import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { FromSchema } from 'json-schema-to-ts';
import {
  ResearchCreatedSchema,
  ResearchEvidenceSchema,
  ResearchListSchema,
  ResearchReportSchema,
} from '@arthalens/contracts';
import { evaluate, type ExclusionPolicy } from '@arthalens/policy';
import {
  CURSOR_SCHEMA,
  PROBLEM_SCHEMA as PROBLEM,
  UUID_PATTERN,
  decodeCursor,
  isPgTimestamp,
} from '../http.js';
import { identityOf, requireIdentity, type IdentityConfig } from '../identity.js';
import type { AuditEvent } from '../ipos/repository.js';
import { sendProblem } from '../plugins/problem.js';
import { streamEvents, type EventNotifier } from './events.js';
import { IdempotencyConflict, NotFound, type ResearchRepository } from './repository.js';

export interface ResearchRouteDeps {
  repo: ResearchRepository;
  notifier: EventNotifier;
  policy: ExclusionPolicy;
  identity: IdentityConfig;
  audit: (event: AuditEvent) => Promise<void>;
  heartbeatMs?: number;
}

const ref = (schema: { $id: string }) => ({ $ref: `${schema.$id}#` });
const createHeaders = {
  type: 'object',
  properties: {
    'idempotency-key': { type: 'string', pattern: '^[A-Za-z0-9_-]{8,128}$' },
  },
} as const;

const listQuery = {
  type: 'object',
  additionalProperties: false,
  properties: {
    limit: { type: 'integer', minimum: 1, maximum: 100, default: 20 },
    cursor: CURSOR_SCHEMA,
  },
} as const;

const reportParams = {
  type: 'object',
  required: ['reportId'],
  properties: { reportId: { type: 'string', pattern: UUID_PATTERN } },
} as const;

/**
 * POST /api/v1/ipos/{ipoId}/research. Registered inside the per-IPO scope, so the IPO
 * exclusion guard (layer L3) has already run.
 */
export function researchCreateRoute(deps: ResearchRouteDeps) {
  return async (scope: FastifyInstance): Promise<void> => {
    scope.post(
      '/api/v1/ipos/:ipoId/research',
      {
        preHandler: requireIdentity(deps.identity),
        schema: {
          summary: 'Start a research report for an IPO',
          description:
            'Returns 202 with the report id. Send an Idempotency-Key header to make retries safe: ' +
            'the same key returns the same report (200, created=false).',
          tags: ['research'],
          headers: createHeaders,
          response: {
            200: ref(ResearchCreatedSchema),
            202: ref(ResearchCreatedSchema),
            409: PROBLEM,
          },
        },
      },
      async (
        request: FastifyRequest<{
          Params: { ipoId: string };
          Headers: FromSchema<typeof createHeaders>;
        }>,
        reply,
      ) => {
        try {
          const result = await deps.repo.create(
            identityOf(request),
            request.params.ipoId,
            request.headers['idempotency-key'],
          );
          return reply.code(result.created ? 202 : 200).send(result);
        } catch (err) {
          if (err instanceof IdempotencyConflict)
            return sendProblem(request, reply, 409, err.message);
          if (err instanceof NotFound) return sendProblem(request, reply, 404, err.message);
          throw err;
        }
      },
    );
  };
}

export async function researchRoutes(app: FastifyInstance, deps: ResearchRouteDeps): Promise<void> {
  const identity = requireIdentity(deps.identity);

  app.get(
    '/api/v1/research',
    {
      preHandler: identity,
      schema: {
        summary: "The signed-in user's research history",
        tags: ['research'],
        querystring: listQuery,
        response: { 200: ref(ResearchListSchema), 400: PROBLEM },
      },
    },
    async (request: FastifyRequest<{ Querystring: FromSchema<typeof listQuery> }>, reply) => {
      const { limit = 20, cursor } = request.query;
      let before: { createdAt: string; id: string } | undefined;
      if (cursor) {
        const decoded = decodeCursor(cursor, isPgTimestamp);
        if (!decoded) return sendProblem(request, reply, 400, 'invalid cursor');
        before = { createdAt: decoded.key, id: decoded.id };
      }
      return deps.repo.list(identityOf(request), limit, before);
    },
  );

  // Everything addressed to one report: identity first, then ownership and exclusion checks.
  await app.register(async (scope) => {
    scope.addHook('preHandler', identity);
    scope.addHook('preHandler', async (request: FastifyRequest, reply: FastifyReply) => {
      const { reportId } = request.params as { reportId: string };
      const ipo = await deps.repo.reportIpo(identityOf(request), reportId);
      // Another user's (or tenant's) report is indistinguishable from a missing one.
      if (!ipo) return sendProblem(request, reply, 404, 'Report not found');
      // Deleting your own report is always allowed: it exposes nothing about the IPO.
      if (request.method === 'DELETE') return;
      const verdict = evaluate(deps.policy, { name: ipo.company_name });
      if (ipo.exclusion_status !== 'allowed' || verdict.decision !== 'allowed') {
        await deps
          .audit({
            action: 'policy.exclusion_blocked',
            target_type: 'research_report',
            target_id: reportId,
            request_id: request.id,
            metadata: { layer: 'api', rule_id: verdict.rule_id, route: request.routeOptions.url },
          })
          .catch((err: unknown) => request.log.error({ err }, 'audit write failed'));
        const message = verdict.user_message ?? deps.policy.rules[0]?.user_message ?? 'Excluded.';
        return sendProblem(request, reply, 403, message, 'ENTITY_EXCLUDED');
      }
    });

    type ReportRequest = FastifyRequest<{ Params: { reportId: string } }>;

    scope.get(
      '/api/v1/research/:reportId',
      {
        schema: {
          summary: 'A research report: sections, claims and citations (partial while running)',
          tags: ['research'],
          params: reportParams,
          response: { 200: ref(ResearchReportSchema), 403: PROBLEM, 404: PROBLEM },
        },
      },
      async (request: ReportRequest, reply) => {
        const report = await deps.repo.report(identityOf(request), request.params.reportId);
        return report ?? sendProblem(request, reply, 404, 'Report not found');
      },
    );

    scope.get(
      '/api/v1/research/:reportId/events',
      {
        schema: {
          summary: 'Live progress as Server-Sent Events (resume with Last-Event-ID)',
          tags: ['research'],
          params: reportParams,
          querystring: {
            type: 'object',
            properties: { after: { type: 'integer', minimum: 0 } },
          },
        },
      },
      async (request: ReportRequest, reply) =>
        streamEvents(request, reply, {
          repo: deps.repo,
          notifier: deps.notifier,
          identity: identityOf(request),
          reportId: request.params.reportId,
          heartbeatMs: deps.heartbeatMs ?? 15_000,
        }),
    );

    scope.get(
      '/api/v1/research/:reportId/evidence',
      {
        schema: {
          summary: "The report's evidence: labelled source documents (metadata and links only)",
          tags: ['research'],
          params: reportParams,
          response: { 200: ref(ResearchEvidenceSchema), 403: PROBLEM, 404: PROBLEM },
        },
      },
      async (request: ReportRequest, reply) => {
        const evidence = await deps.repo.evidence(identityOf(request), request.params.reportId);
        return evidence ?? sendProblem(request, reply, 404, 'Report not found');
      },
    );

    scope.delete(
      '/api/v1/research/:reportId',
      {
        schema: {
          summary: 'Delete a report (hidden immediately; purged under the retention policy)',
          tags: ['research'],
          params: reportParams,
          response: { 204: { type: 'null' }, 404: PROBLEM },
        },
      },
      async (request: ReportRequest, reply) => {
        const deleted = await deps.repo.softDelete(identityOf(request), request.params.reportId);
        return deleted
          ? reply.code(204).send()
          : sendProblem(request, reply, 404, 'Report not found');
      },
    );
  });
}
