# ADR-0004: PostgreSQL as system of record and job queue; no Redis initially

**Status:** Proposed · **Date:** 2026-10-17

## Context
We need durable research jobs (minutes long, must survive restarts), scheduled monitoring (P2), rate limiting, and caching. The brief says to add Redis or other infrastructure only when justified.

## Decision
- PostgreSQL is the system of record (pgvector extension enabled only when vector retrieval is introduced, and justified at that point).
- **Job queue in Postgres:** a `research_jobs` table with status, `lease_expires_at`, `attempt`, `max_attempts`, `next_run_at`. Workers claim with `SELECT … FOR UPDATE SKIP LOCKED`, renew leases while working, and checkpoint per section. Expired leases are reclaimable.
- **Scheduling (P2):** a scheduler loop inserts `monitoring_jobs` with a unique `(stock_id, window_start)` key, which makes reruns no-ops.
- **Rate limiting** for a single API instance: in-process. For multiple instances: a Postgres-backed fixed-window counter. Redis is introduced only if measured load requires it, with a superseding ADR.
- **Retrieval cache:** Postgres table keyed by `(provider, normalized_query, freshness_bucket)`, holding public data only.

## Consequences
- + One stateful dependency to run, back up and secure. Jobs are transactional with the rows they create.
- + Easy to teach and inspect (`SELECT * FROM research_jobs`).
- − Postgres-as-queue tops out at high throughput, but our scale (dozens to thousands of jobs per day) is far below that.
- − We implement leases and backoff ourselves. A Python library may be adopted at M4 if it fits; the table contract stays the same.

## Alternatives
- **Celery + Redis / RQ:** an extra stateful service, and job state is not transactional with DB writes.
- **Temporal:** excellent durable workflows, but heavy infrastructure for Phase 1. Revisit for Stage 7 (HITL).
- **pg-boss (Node):** good, but the consumer is Python.
