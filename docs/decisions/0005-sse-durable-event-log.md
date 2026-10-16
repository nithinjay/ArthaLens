# ADR-0005: SSE backed by a durable, replayable event log

**Status:** Proposed · **Date:** 2026-10-17

## Context
Users watch research progress live. Browsers disconnect, users navigate away, and API instances restart. The work happens in a different service (AI worker) from the one that holds the HTTP connection (API).

## Decision
- The worker appends `research_events(report_id, seq BIGINT, type, payload JSONB, created_at)`, with `seq` monotonic per report, and issues `pg_notify('research_events', report_id)`.
- The API SSE endpoint: authorize → replay events where `seq > Last-Event-ID` → `LISTEN` and stream new ones → heartbeat every 15 s → close after a terminal event.
- Each SSE message `id:` is the `seq`, so `EventSource` reconnects resume automatically.
- Payloads are status metadata only (no source text, no secrets) and are validated against a schema.

## Consequences
- + Reconnect and reload "just work", and the job is independent of any connection.
- + Any API instance can serve any stream, with no sticky sessions.
- + The event log doubles as an audit trail of the run.
- − `NOTIFY` payloads are small, which is fine since we only notify IDs. Each API instance holds one `LISTEN` connection.
- − The table grows, so a retention job prunes events for old reports (keeping terminal ones).

## Alternatives
- **WebSockets:** bidirectional, which we don't need. SSE is simpler and proxy-friendly.
- **In-memory pub/sub:** loses events on restart and needs sticky routing.
- **Polling:** simpler but laggy and wasteful. It is kept as the fallback when SSE is blocked by a proxy.
