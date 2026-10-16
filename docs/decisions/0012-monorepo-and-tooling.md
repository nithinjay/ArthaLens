# ADR-0012: Monorepo layout and toolchain

**Status:** Proposed · **Date:** 2026-10-17

## Decision
- **Monorepo** with the layout in [system-architecture.md §6](../architecture/system-architecture.md#6-repository-structure-planned-created-in-milestone-1). The three deployable parts sit in separate top-level directories: **`frontend/`** (React), **`backend/`** (Fastify API), **`ai/`** (Python AI service). Shared, language-neutral or TS-shared code lives in `packages/`. `docs/` stays at the root. This replaces the brief's suggested `apps/web`, `services/api` and `services/ai` nesting so each part is obvious at a glance.
- pnpm workspace members: `frontend`, `backend`, `packages/*`. `ai/` is a standalone uv project.
- **JS/TS:** pnpm workspaces; TypeScript strict; ESLint + Prettier; Vitest for unit tests; Playwright for e2e.
- **Python:** uv for env/deps (lockfile committed); Ruff (lint + format); mypy (strict on `validation/`, `metrics/`, `policy/`); pytest (+ Hypothesis for property tests).
- **Migrations:** SQL-first files in `database/migrations`, applied with **dbmate** (language-neutral, one binary, works in Docker). This avoids picking an ORM's migration system in one language for a DB shared by both.
- **DB access:** API uses a typed SQL query builder (Kysely) with parameters only. AI uses SQLAlchemy Core or asyncpg with parameters only (choice confirmed at M1).
- **Secrets:** `.env` gitignored; `.env.example` placeholders; gitleaks pre-commit and CI.
- **Versions:** exact versions pinned at M1 and recorded in lockfiles. No floating major versions.

## Consequences
- + One PR can change a contract and both consumers atomically.
- − Two package managers. Accepted, since each is best-in-class for its language.
