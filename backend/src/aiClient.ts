import { Ajv2020 } from 'ajv/dist/2020.js';
import {
  ServiceHealthSchema,
  type DependencyCheck,
  type ServiceHealth,
} from '@arthalens/contracts';

const ajv = new Ajv2020({ strict: false });
const isServiceHealth = ajv.compile<ServiceHealth>(ServiceHealthSchema);

export interface AiClientOptions {
  baseUrl: string;
  serviceToken: string;
  timeoutMs: number;
  fetchImpl?: typeof fetch;
}

/** Client for the AI service's internal API (`/internal/v1`). */
export class AiClient {
  readonly #baseUrl: string;
  readonly #token: string;
  readonly #timeoutMs: number;
  readonly #fetch: typeof fetch;

  constructor(options: AiClientOptions) {
    this.#baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.#token = options.serviceToken;
    this.#timeoutMs = options.timeoutMs;
    this.#fetch = options.fetchImpl ?? fetch;
  }

  /**
   * Authenticated readiness check. Returns a dependency result rather than throwing,
   * so a failing AI service degrades the backend instead of taking it down.
   */
  async checkHealth(requestId: string): Promise<DependencyCheck> {
    const started = performance.now();
    let res: Response;
    try {
      res = await this.#fetch(`${this.#baseUrl}/internal/v1/health`, {
        headers: {
          authorization: `Bearer ${this.#token}`,
          'x-request-id': requestId,
          accept: 'application/json',
        },
        signal: AbortSignal.timeout(this.#timeoutMs),
        redirect: 'error',
      });
    } catch {
      return down('ai service unreachable');
    }

    if (res.status === 401) return down('ai service rejected service credentials');

    let body: unknown;
    try {
      body = await res.json();
    } catch {
      return down('ai service returned invalid response');
    }
    // Responses from another service are validated like any other untrusted input.
    if (!isServiceHealth(body)) return down('ai service returned invalid response');
    if (!res.ok || body.status !== 'ok') return down('ai service not ready');

    return { status: 'ok', latency_ms: Math.round(performance.now() - started), detail: null };
  }
}

function down(detail: string): DependencyCheck {
  return { status: 'down', latency_ms: null, detail };
}
