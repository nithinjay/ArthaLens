import type { ServiceHealth } from '@arthalens/contracts';

export class ApiError extends Error {
  override name = 'ApiError';
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/**
 * Fetch backend status. A 503 still carries a valid ServiceHealth body (status "down"),
 * so it is returned as data rather than thrown; the UI shows which dependency failed.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<ServiceHealth> {
  const res = await fetch('/api/v1/health', {
    headers: { accept: 'application/json' },
    ...(signal ? { signal } : {}),
  });
  if (res.ok || res.status === 503) {
    return (await res.json()) as ServiceHealth;
  }
  throw new ApiError(res.status, `Status check failed (HTTP ${res.status})`);
}
