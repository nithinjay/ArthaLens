# ADR-0001: Hybrid TypeScript API + Python AI service

**Status:** Accepted · **Date:** 2026-10-17

## Context
The brief prescribes React/TS on the front, Node/TS for the application API, and Python/FastAPI/ADK for AI. Two backends add cost, so the split has to pay for itself.

## Decision
Keep two backend services with a hard responsibility boundary:
- **backend/ (TS):** identity, tenancy, authorization, user-owned data, public API, calculator authority, SSE relay.
- **ai/ (Python):** ingestion, retrieval, evidence, LLM orchestration, metrics, validation, composition.
- **frontend/ (TS):** the React UI. It talks only to `backend/`.

Each lives in its own top-level directory with its own dependencies, Dockerfile and tests ([ADR-0012](0012-monorepo-and-tooling.md)).

They communicate through **PostgreSQL** (job rows, event log, results) plus a small **internal HTTP API** for synchronous needs such as health checks and on-demand IPO refresh. That API is versioned (`/internal/v1`) and authenticated with a service token.

## Consequences
- + Python gets ADK, PDF/OCR, `Decimal`, Pydantic. TS gets shared Zod/types between browser and API.
- + Users' personal financial data never enters the process that talks to LLMs and the open web.
- − Two toolchains, two test suites, risk of contract drift → mitigated by [ADR-0007](0007-contracts-and-schemas.md) and the single-owner-per-rule table in the architecture doc.
- − Two services writing one database → mitigated by per-table write ownership and separate DB roles.

## Alternatives
- **All Python (FastAPI for everything):** simpler ops, but loses shared TS types with React and goes against the brief.
- **All TS (with an LLM SDK in Node):** ADK and the document-parsing ecosystem are weaker or absent.
- **Microservices per agent:** premature; adds network failure modes with no benefit at this scale.
