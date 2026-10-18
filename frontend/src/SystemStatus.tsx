import { useQuery } from '@tanstack/react-query';
import type { DependencyCheck, ServiceHealth } from '@arthalens/contracts';
import { fetchHealth } from './api';

const OVERALL_LABEL: Record<ServiceHealth['status'], string> = {
  ok: 'All systems operational',
  degraded: 'Partially available',
  down: 'Unavailable',
};

const DEPENDENCY_LABEL: Record<string, string> = {
  database: 'Database',
  ai: 'Research service',
};

export function SystemStatus() {
  const query = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: 30_000,
  });

  if (query.isPending) {
    return (
      <p role="status" aria-live="polite">
        Checking services…
      </p>
    );
  }

  if (query.isError) {
    return (
      <div role="alert" className="status status--down">
        <p>Could not reach the ArthaLens API.</p>
        <button type="button" onClick={() => void query.refetch()}>
          Retry
        </button>
      </div>
    );
  }

  const health = query.data;
  return (
    <section aria-labelledby="status-heading" className={`status status--${health.status}`}>
      <h2 id="status-heading">System status</h2>
      <p>
        <strong>{OVERALL_LABEL[health.status]}</strong>
        <span className="muted"> · backend v{health.version}</span>
      </p>
      <ul>
        {Object.entries(health.checks).map(([name, check]) =>
          check ? <DependencyRow key={name} name={name} check={check} /> : null,
        )}
      </ul>
      <p className="muted">
        Last checked {new Date(query.dataUpdatedAt).toLocaleTimeString('en-IN')}
      </p>
    </section>
  );
}

function DependencyRow({ name, check }: { name: string; check: DependencyCheck }) {
  const label = DEPENDENCY_LABEL[name] ?? name;
  return (
    <li>
      <span className={`dot dot--${check.status}`} aria-hidden="true" />
      {label}: {check.status === 'ok' ? 'OK' : 'Down'}
      {check.latency_ms !== null && <span className="muted"> ({check.latency_ms} ms)</span>}
      {check.detail && <span className="muted"> — {check.detail}</span>}
    </li>
  );
}
