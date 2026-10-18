# ArthaLens

Evidence-grounded IPO research and stock intelligence for Indian markets (NSE/BSE).
**Educational tool, not investment advice.** It never submits IPO applications or trades.

> Status: **Milestone 3 (evidence ledger).** IPO data with per-field, per-page provenance; an immutable, versioned, tenant-isolated evidence ledger; sandboxed PDF parsing with OCR; Jio exclusion at every layer. No research reports or UI yet. See [docs/CHECKLIST.md](docs/CHECKLIST.md).

## Layout

| Directory | What |
|---|---|
| `frontend/` | React + Vite + TypeScript web UI |
| `backend/` | Node + Fastify + TypeScript public API (identity, tenancy, calculator, SSE relay) |
| `ai/` | Python + FastAPI (+ Google ADK from Milestone 4): ingestion, evidence, research, validation |
| `packages/contracts` | TypeScript types + JSON Schemas generated from the Python contracts |
| `packages/policy` | Jio exclusion rules + shared test vectors (used by backend/ and ai/) |
| `database/` | SQL migrations (dbmate) |
| `infrastructure/` | Dockerfiles/config (Terraform and Helm in Milestone 11) |
| `scripts/` | env setup, smoke test, migration check, secret scan |
| `docs/` | Brief, requirements, architecture, threat model, ADRs, runbooks |

## Quick start

```sh
nvm use && corepack enable pnpm
pnpm install && uv sync --project ai
pnpm env:init
docker compose up --build -d
pnpm smoke
```

Open http://localhost:8080. Full guide: [docs/runbooks/local-development.md](docs/runbooks/local-development.md).
