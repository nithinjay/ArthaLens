# Architecture Decision Records

Format: Context → Decision → Consequences → Alternatives considered. ADRs are immutable once **Accepted**. To change one, add a new ADR that supersedes it.

| # | Title | Status |
|---|---|---|
| [0001](0001-hybrid-typescript-python.md) | Hybrid TypeScript API + Python AI service | Accepted |
| [0002](0002-fastify-over-express.md) | Fastify for the application API | Accepted |
| [0003](0003-google-adk-orchestration.md) | Google ADK as orchestration runtime behind our own port | Accepted |
| [0004](0004-postgres-and-job-queue.md) | PostgreSQL as system of record and job queue; no Redis initially | Accepted |
| [0005](0005-sse-durable-event-log.md) | SSE backed by a durable, replayable event log | Accepted |
| [0006](0006-money-and-quantities.md) | Exact money arithmetic: integer paise / NUMERIC / Decimal | Accepted |
| [0007](0007-contracts-and-schemas.md) | Contract source of truth and code generation | Accepted |
| [0008](0008-jio-exclusion-policy.md) | Jio exclusion: policy-as-data, layered, fail-closed | Accepted |
| [0009](0009-deterministic-first-validation.md) | Deterministic-first validation and bounded repair | Accepted |
| [0010](0010-authentication-and-sessions.md) | Server-side sessions behind an IdentityProvider port | Accepted |
| [0011](0011-tenancy-and-rls.md) | Tenant isolation with tenant_id + Postgres RLS | Accepted |
| [0012](0012-monorepo-and-tooling.md) | Monorepo layout and toolchain | Accepted |
| [0013](0013-frontend-stack.md) | Frontend component, form and chart libraries | Accepted |
| [0014](0014-milestone-1-implementation-refinements.md) | Milestone 1 implementation refinements | Accepted |
| [0015](0015-source-access-and-request-validation.md) | Source access per provider; JSON Schema request validation | Accepted |

All accepted on 2026-10-17 (Milestone 0 approval). Changes go in new, superseding ADRs.
