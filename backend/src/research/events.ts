import type { FastifyReply, FastifyRequest } from 'fastify';
import pg from 'pg';
import type { ResearchEvent } from '@arthalens/contracts';
import type { Identity } from '../identity.js';
import { TERMINAL_EVENTS, type ResearchRepository } from './repository.js';

/** Something that says "report X has new events". Payloads carry only the report id. */
export interface EventNotifier {
  subscribe(reportId: string, onNotify: () => void): () => void;
}

/**
 * One LISTEN connection per backend instance, fanned out to SSE subscribers (ADR-0005).
 * Notifications are only wake-ups: events are always read back through the tenant-scoped
 * repository, so a notification can never leak another tenant's data.
 */
export class PgEventHub implements EventNotifier {
  private client: pg.Client | null = null;
  private starting: Promise<void> | null = null;
  private closed = false;
  private readonly subscribers = new Map<string, Set<() => void>>();

  constructor(
    private readonly connectionString: string,
    private readonly log: { warn: (obj: object, msg: string) => void },
  ) {}

  subscribe(reportId: string, onNotify: () => void): () => void {
    const set = this.subscribers.get(reportId) ?? new Set();
    set.add(onNotify);
    this.subscribers.set(reportId, set);
    void this.ensureStarted();
    return () => {
      set.delete(onNotify);
      if (set.size === 0) this.subscribers.delete(reportId);
    };
  }

  private ensureStarted(): Promise<void> {
    if (this.client || this.closed) return Promise.resolve();
    this.starting ??= this.start().finally(() => {
      this.starting = null;
    });
    return this.starting;
  }

  private async start(): Promise<void> {
    const client = new pg.Client({ connectionString: this.connectionString });
    client.on('notification', (msg) => {
      if (msg.payload) this.subscribers.get(msg.payload)?.forEach((notify) => notify());
    });
    client.on('error', (err) => {
      // SSE streams also poll on every heartbeat, so a lost listener delays events but
      // never loses them. Reconnect on the next subscription.
      this.log.warn({ err }, 'research event listener lost; streams fall back to polling');
      this.client = null;
      client.end().catch(() => undefined);
    });
    try {
      await client.connect();
      await client.query('LISTEN research_events');
      this.client = client;
    } catch (err) {
      this.log.warn({ err }, 'could not start research event listener; streams will poll');
      await client.end().catch(() => undefined);
    }
  }

  async close(): Promise<void> {
    this.closed = true;
    await this.client?.end().catch(() => undefined);
    this.client = null;
  }
}

function frame(event: ResearchEvent): string {
  // `id` lets EventSource resume with Last-Event-ID after a disconnect.
  return `id: ${event.seq}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
}

/** Parse the resume point: Last-Event-ID header first, then ?after=. */
export function resumeAfter(request: FastifyRequest): number {
  const raw = request.headers['last-event-id'] ?? (request.query as { after?: string }).after;
  const value = Number(Array.isArray(raw) ? raw[0] : raw);
  return Number.isSafeInteger(value) && value > 0 ? value : 0;
}

export interface StreamOptions {
  repo: ResearchRepository;
  notifier: EventNotifier;
  identity: Identity;
  reportId: string;
  heartbeatMs: number;
}

/**
 * Stream a report's events over SSE: replay everything after the resume point, then follow.
 * Subscribing before replaying means nothing published in between is missed; reads are
 * serialised so events go out once, in order. Closes after a terminal event.
 */
export async function streamEvents(
  request: FastifyRequest,
  reply: FastifyReply,
  { repo, notifier, identity, reportId, heartbeatMs }: StreamOptions,
): Promise<void> {
  reply.hijack();
  const res = reply.raw;
  res.writeHead(200, {
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-cache, no-transform',
    connection: 'keep-alive',
    'x-accel-buffering': 'no', // tell proxies not to buffer
    'x-request-id': request.id,
  });

  let last = resumeAfter(request);
  let open = true;
  let reading = false;
  let again = false;

  const finish = () => {
    if (!open) return;
    open = false;
    clearInterval(heartbeat);
    unsubscribe();
    res.end();
  };

  const pump = async (): Promise<void> => {
    if (reading) {
      again = true;
      return;
    }
    reading = true;
    try {
      do {
        again = false;
        const events = await repo.events(identity, reportId, last);
        for (const event of events) {
          if (!open) return;
          res.write(frame(event));
          last = event.seq;
          if (TERMINAL_EVENTS.has(event.type)) {
            finish();
            return;
          }
        }
      } while (again && open);
    } catch (err) {
      request.log.error({ err }, 'event stream read failed');
      finish();
    } finally {
      reading = false;
    }
  };

  const unsubscribe = notifier.subscribe(reportId, () => void pump());
  const heartbeat = setInterval(() => {
    if (!open) return;
    res.write(': keep-alive\n\n');
    void pump(); // also a polling fallback if the LISTEN connection is down
  }, heartbeatMs);
  request.raw.on('close', finish);

  await pump();
}
