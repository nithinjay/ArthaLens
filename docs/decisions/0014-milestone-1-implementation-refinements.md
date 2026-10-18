# ADR-0014: Milestone 1 implementation refinements

**Status:** Accepted · **Date:** 2026-10-17 · **Refines:** ADR-0002, ADR-0004, ADR-0007, ADR-0012

## Context
Building the foundation settled several choices that Milestone 0 left open, and hit a few environment constraints. This ADR records them so the accepted ADRs stay unchanged.

## Decisions

| Topic | Decision | Why |
|---|---|---|
| Node version | **Node 22 LTS** (`.nvmrc` = 22.23.2), same in Docker | Node 20 reached end-of-life in April 2026; Vitest 5 requires Node 22+ |
| pnpm | **pnpm 12.14.0 via Corepack**; settings in `pnpm-workspace.yaml` (`saveExact`, `engineStrict`) | pnpm 12 no longer reads these from `.npmrc` |
| Install scripts | Denied by default; **only `esbuild` allowed** (`allowBuilds`) | Supply-chain hygiene (threat model T-51) |
| TypeScript | **6.0.3** | typescript-eslint supports `<6.1`; TS 7 not yet supported by the lint toolchain |
| Contract runtime validation (refines ADR-0007) | Generated package exports **TS types + the JSON Schema as a const**; runtime validation uses **Ajv (JSON Schema 2020-12)** instead of generated Zod | One artefact (the JSON Schema Pydantic emits) drives types, validation, Fastify serialisation and OpenAPI; avoids a lossy JSON-Schema→Zod conversion |
| Fastify schemas (refines ADR-0002) | Response schemas use the generated JSON Schema; Fastify's serialiser **drops undeclared fields** (tested). Zod type provider is added with the first user-input route (M2/M8). Zod already validates environment config | Nothing in M1 accepts a request body |
| Python DB driver (resolves ADR-0012) | **psycopg 3** (async) | Sync + async in one driver, LISTEN/NOTIFY for SSE (ADR-0005), maintained binary wheels |
| Backend query builder | Kysely deferred to M8 (first backend-owned queries) | M1 runs only `SELECT 1` |
| Migrations & DB init | Migrations and the role-creation script are **copied into images**, not bind-mounted | Docker Desktop on macOS can't mount paths under `/Library`; image-baked files also behave the same in CI and production |
| Postgres host port | **5433** by default (`POSTGRES_HOST_PORT`) | Avoids clashing with a locally installed Postgres on 5432 |
| Readiness semantics | Backend: database down → `down` (503); AI down → `degraded` (200) | Accounts, history and calculators keep working when research is unavailable |
| Deferred containers | `ai-worker` arrives with the job queue (M4); object storage (MinIO) when source snapshots are stored (M3/M4) | No placeholder processes that do nothing |
| Frontend in Compose | nginx serves the production build and proxies `/api` (same origin, strict CSP). Hot reload via `pnpm dev:frontend` | Avoids Linux/macOS native-binary clashes from bind-mounting `node_modules` |
| Secret scanning | gitleaks scans **exactly the files git would commit**, streamed into the container | Avoids false positives from gitignored `.env` and needs no file sharing |

## Consequences
- Contributors need Node 22 and `corepack enable pnpm` (documented in the local-development runbook).
- Adding a migration requires `docker compose up --build migrate`, a small cost for portability.
