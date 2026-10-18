# ADR-0007: Contract source of truth and code generation

**Status:** Accepted · **Date:** 2026-10-17

## Context
Two languages exchange typed data: job payloads, report/section/claim/evidence shapes, and events. Hand-maintained duplicate types will drift.

## Decision
- **AI-owned shapes** (Report, Section, Claim, Evidence, ResearchEvent, IpoSnapshot): **Pydantic is the source of truth** → export JSON Schema → generate TS types and Zod validators into `packages/contracts` (`pnpm contracts:gen`).
- **Public API shapes:** Zod schemas in the API (reusing generated contract types) → OpenAPI 3.1 via `@fastify/swagger`, published at `/api/v1/openapi.json`.
- **Versioning:** each contract carries `schema_version`. Breaking changes mean a new version, and readers accept N and N-1 during migration.
- **CI drift check:** regenerate and fail if the git diff is non-empty. Contract tests run fixture payloads through both the Pydantic and Zod validators.
- Prompts, model settings and provider configs are also versioned files (`prompts/<section>/v3.md`), and their version is stored on each section result.

## Consequences
- + One definition per shape; type errors surface at build time.
- − Codegen step in the build. The generator choice (e.g. `json-schema-to-zod`) will be confirmed at M1.
