import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { FromSchema } from 'json-schema-to-ts';
import { IpoDetailSchema, IpoListSchema, type IpoList } from '@arthalens/contracts';
import { evaluate, normalizeName, type ExclusionPolicy } from '@arthalens/policy';
import { sendProblem } from '../plugins/problem.js';
import type { IpoIdentity, IpoRepository } from './repository.js';

export interface IpoRouteDeps {
  repo: IpoRepository;
  policy: ExclusionPolicy;
}

const UUID_PATTERN = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

const listQuerySchema = {
  type: 'object',
  additionalProperties: false,
  properties: {
    status: {
      type: 'string',
      enum: [
        'upcoming',
        'open',
        'closed',
        'allotment',
        'listed',
        'withdrawn',
        'postponed',
        'unverified',
      ],
    },
    issue_type: { type: 'string', enum: ['mainboard', 'sme'] },
    exchange: { type: 'string', enum: ['NSE', 'BSE'] },
    q: { type: 'string', minLength: 1, maxLength: 100 },
    limit: { type: 'integer', minimum: 1, maximum: 100, default: 20 },
    cursor: { type: 'string', maxLength: 500, pattern: '^[A-Za-z0-9_-]+$' },
  },
} as const;
type ListQuery = FromSchema<typeof listQuerySchema>;

const ipoParamsSchema = {
  type: 'object',
  required: ['ipoId'],
  properties: { ipoId: { type: 'string', pattern: UUID_PATTERN } },
} as const;

const PROBLEM_SCHEMA = {
  type: 'object',
  properties: {
    type: { type: 'string' },
    title: { type: 'string' },
    status: { type: 'integer' },
    detail: { type: 'string' },
    instance: { type: 'string' },
    request_id: { type: 'string' },
    code: { type: 'string' },
  },
} as const;

// Cursor = base64url(JSON [normalized_name, id]) of the last item on the previous page.
export function encodeCursor(normalizedName: string, id: string): string {
  return Buffer.from(JSON.stringify([normalizedName, id])).toString('base64url');
}

export function decodeCursor(cursor: string): { normalizedName: string; id: string } | null {
  try {
    const value: unknown = JSON.parse(Buffer.from(cursor, 'base64url').toString('utf8'));
    if (
      Array.isArray(value) &&
      value.length === 2 &&
      typeof value[0] === 'string' &&
      typeof value[1] === 'string' &&
      new RegExp(UUID_PATTERN).test(value[1])
    ) {
      return { normalizedName: value[0], id: value[1] };
    }
  } catch {
    // fall through
  }
  return null;
}

declare module 'fastify' {
  interface FastifyRequest {
    ipo?: IpoIdentity;
  }
}

export async function ipoRoutes(app: FastifyInstance, deps: IpoRouteDeps): Promise<void> {
  const { repo, policy } = deps;

  app.get(
    '/api/v1/ipos',
    {
      schema: {
        summary: 'List and filter IPOs',
        description:
          'Only allowed IPOs are returned. Every critical field carries its own status, ' +
          'source and check time. A search naming an excluded entity returns no items and a notice.',
        tags: ['ipos'],
        querystring: listQuerySchema,
        response: { 200: { $ref: `${IpoListSchema.$id}#` }, 400: PROBLEM_SCHEMA },
      },
    },
    async (request: FastifyRequest<{ Querystring: ListQuery }>, reply) => {
      const q = request.query;
      const after = q.cursor === undefined ? undefined : decodeCursor(q.cursor);
      if (after === null) return sendProblem(request, reply, 400, 'invalid cursor');

      // Exclusion L3 (search): a query that names an excluded entity is answered with a
      // notice and nothing else, even if no such record exists.
      if (q.q !== undefined) {
        const verdict = evaluate(policy, { name: q.q });
        if (verdict.decision !== 'allowed') {
          request.log.info({ rule_id: verdict.rule_id }, 'search matched exclusion policy');
          const body: IpoList = {
            schema_version: 'ipo-list.v1',
            items: [],
            next_cursor: null,
            notice: { code: 'ENTITY_EXCLUDED', message: verdict.user_message ?? '' },
          };
          return body;
        }
      }

      const limit = q.limit ?? 20;
      const rows = await repo.list({
        ...(q.status && { status: q.status }),
        ...(q.issue_type && { issueType: q.issue_type }),
        ...(q.exchange && { exchange: q.exchange }),
        ...(q.q !== undefined && { nameContains: normalizeName(q.q) }),
        ...(after && { after }),
        limit: limit + 1,
      });
      // Defence in depth: re-check every row, even though the database should never hold one.
      const allowed = rows.filter(
        (r) => evaluate(policy, { name: r.company_name }).decision === 'allowed',
      );
      const page = allowed.slice(0, limit);
      const last = page.at(-1);
      const body: IpoList = {
        schema_version: 'ipo-list.v1',
        items: page,
        next_cursor:
          rows.length > limit && last ? encodeCursor(last.normalized_name, last.id) : null,
        notice: null,
      };
      return body;
    },
  );

  // Everything addressed to one IPO lives in this scope, so the exclusion guard (L3) runs
  // before any handler. Research, calculator and evidence routes (M4, M7) go here too.
  await app.register(async (scope) => {
    scope.addHook('preHandler', async (request: FastifyRequest, reply: FastifyReply) => {
      const { ipoId } = request.params as { ipoId: string };
      const ipo = await repo.identity(ipoId);
      if (!ipo) return sendProblem(request, reply, 404, 'IPO not found');
      const verdict = evaluate(policy, { name: ipo.company_name });
      if (ipo.exclusion_status !== 'allowed' || verdict.decision !== 'allowed') {
        await repo
          .audit({
            action: 'policy.exclusion_blocked',
            target_type: 'ipo',
            target_id: ipo.id,
            request_id: request.id,
            metadata: {
              layer: 'api',
              rule_id: verdict.rule_id,
              decision: verdict.decision,
              stored_status: ipo.exclusion_status,
              route: request.routeOptions.url,
            },
          })
          .catch((err: unknown) => request.log.error({ err }, 'audit write failed'));
        const message =
          verdict.user_message ?? policy.rules[0]?.user_message ?? 'This IPO is excluded.';
        return sendProblem(request, reply, 403, message, 'ENTITY_EXCLUDED');
      }
      request.ipo = ipo;
    });

    scope.get(
      '/api/v1/ipos/:ipoId',
      {
        schema: {
          summary: 'IPO detail with per-field provenance and all source observations',
          tags: ['ipos'],
          params: ipoParamsSchema,
          response: {
            200: { $ref: `${IpoDetailSchema.$id}#` },
            403: PROBLEM_SCHEMA,
            404: PROBLEM_SCHEMA,
          },
        },
      },
      async (request: FastifyRequest<{ Params: { ipoId: string } }>, reply) => {
        const detail = await repo.detail(request.params.ipoId);
        if (!detail) return sendProblem(request, reply, 404, 'IPO not found');
        return detail;
      },
    );
  });
}
