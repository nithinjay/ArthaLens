# Project Checklist

Legend: **done** = written/implemented · **tested** = verified by a test or check that was actually run · **planned** = not started · **unverified** = assumption not yet confirmed

_Last updated: 2026-10-18_

## Milestone 0: Requirements and architecture (approved 2026-10-17)

| Item | State | Location |
|---|---|---|
| Requirements, lifecycle, architecture, DFD, threat model, source strategy | done | [requirements.md](requirements.md), [architecture/](architecture/), [security/threat-model.md](security/threat-model.md) |
| ADRs 0001–0013 | done (Accepted) | [decisions/](decisions/README.md) |
| Acceptance criteria | done | [acceptance-criteria.md](acceptance-criteria.md) |
| Open questions Q1, Q2, Q6 | resolved | [requirements.md §6](requirements.md) |
| Mermaid diagrams render | unverified | Not rendered in a session; check on GitHub |

## Milestone 1: Project foundation (merged 2026-10-18, PR #1)

| AC | Item | State | Evidence (run 2026-10-17) |
|---|---|---|---|
| 1.1 | Compose stack: postgres → migrate → ai → backend → frontend, all healthy | tested | `docker compose up --build -d`; `docker compose ps` all healthy, migrate exited 0 |
| 1.2 | `/healthz` + `/readyz` on backend and ai | tested | `pnpm smoke` |
| 1.3 | backend → ai internal call with service token; 401 without/with wrong token | tested | `pnpm smoke` + 8 pytest cases + 7 Vitest cases (real HTTP fake server) |
| 1.4 | Migrations up → full rollback → up | tested | `scripts/check-migrations.sh`: **caught a real bug** (policy dependency in down migration), fixed, now PASS |
| 1.5 | Typecheck, lint, unit tests in both languages | tested | TS: typecheck + ESLint + Prettier clean; Vitest backend 36/36, frontend 5/5. Python: ruff + mypy strict clean; pytest 21/21 |
| 1.5 | Contract generation (Pydantic → JSON Schema → TS) and drift check | tested | `pnpm contracts:gen` reproduces committed files; `ai/tests/test_contracts.py` drift test |
| 1.6 | No secrets in committable files; `.env` gitignored | tested | `pnpm secrets:scan` → no leaks; negative control (planted fake key) detected; `git check-ignore .env` |
| 1.6 | No secrets in container logs | tested | grep of `docker compose logs` for service token and DB password → 0 matches |
| 1.7 | Least-privilege DB roles; append-only audit; RLS tenant isolation | tested | `pnpm smoke` (6 database checks with synthetic tenants) |
| — | Honest degradation: AI down → backend `degraded` (200); DB down → `down` (503) | tested | Live: stopped ai container → `degraded`, restarted → `ok`. DB-down path covered by unit tests only |
| — | Frontend loading / ok / degraded / down / error+retry states | tested | Vitest 5/5 (jsdom). Not yet checked in a real browser or with axe |
| — | Security headers: helmet on API, strict CSP on frontend | tested | Vitest + `pnpm smoke` |
| — | Request-id propagation browser → backend → ai | tested | Unit tests on both services; nginx sets `X-Request-Id` (not separately asserted end-to-end) |

### Not in Milestone 1 (by design)
- ai-worker container, object storage → M4/M3 ([ADR-0014](decisions/0014-milestone-1-implementation-refinements.md))
- Authentication, sessions, rate limiting, CSRF → M8 (`users` table has no RLS yet; sign-in lookups need the M8 auth design)
- CI pipeline (GitHub Actions) → M11, or earlier if you want it

## Milestone 2: IPO data ingestion (awaiting your verification)

| AC | Item | State | Evidence (run 2026-10-18) |
|---|---|---|---|
| 2.1 | SearchPort + `fixtures` (synthetic) + `manual` import providers | tested | `ai/tests/test_pipeline.py` (19); live ingestion in Docker against Postgres |
| 2.1 | Live adapter: guarded SEBI single-document fetch, off by default | tested (mock network only) | `ai/tests/test_fetch.py` (36). **Never run against sebi.gov.in**; enabling is requirements Q7 |
| 2.1 | Terms review: NSE forbids automated collection, SEBI permits linking, BSE unconfirmed | done | [ADR-0015](decisions/0015-source-access-and-request-validation.md) |
| 2.2 | Every critical field stored with source document, verbatim quote and check time | tested | DB CHECK `verified_requires_provenance` (rejects bypass attempt); smoke "every verified field has source, quote and check time" |
| 2.2 | "Verified" requires the quote to appear in the stored document | tested | `test_resolve_and_status.py`, `test_pipeline.py::test_every_verified_field_has_grounded_provenance` |
| 2.2 | Field resolution: authority, then recency, conflicts, discrepancies noted | tested | 8 unit tests + fixtures (addendum supersedes; equal-authority conflict shows no value) |
| 2.3 | Status derivation incl. stale "upcoming" → `unverified` | tested | 11 status tests; 6 fixture IPOs land on 6 different statuses (live API) |
| 2.4 | Exclusion matcher: same 26 vectors pass in TS and Python | tested | `packages/policy` Vitest 33/33; pytest `-m policy` 37/37 |
| 2.4 | L5: excluded entities quarantined before any document is read | tested | Fixture points at a non-existent file; run still succeeds. `quarantined_entities` holds name + URL only |
| 2.4 | L2: DB backstop rejects Jio names (incl. full-width) and snapshots of withdrawn IPOs | tested | Direct SQL probes as `app_ai` → CHECK and trigger violations |
| 2.4 | L3: API search notice, row re-check, per-IPO route guard, audit | tested | Backend Vitest (25 IPO tests); smoke (4 searches, 403 + audit row) |
| 2.4 | L6: policy reconcile marks stored IPOs `withdrawn_by_policy` | tested (unit) | In-memory repo test path; Postgres method exercised on every run but has never matched a row |
| 2.5 | SSRF: private/metadata IPs, rebinding, redirects, robots, size, MIME | tested | `test_fetch.py`; peer-address check unit-tested (needs a real socket to run end-to-end) |
| — | INR/date/price-band/lot normalisation (lakh/crore vs million/billion) | tested | `test_normalize.py` (73) |
| — | `GET /api/v1/ipos` (filters, search, cursor pagination) and `GET /api/v1/ipos/{id}` | tested | Backend Vitest + smoke (live, 44/44) |
| — | API role can cite documents but can't read stored text or the quarantine | tested | Column-level grant; SQL probes → permission denied |
| — | Source files in policy/domain/ingestion are ASCII-only (no hidden look-alikes) | tested | `test_source_hygiene.py` |

Totals: pytest 236 · Vitest 99 (backend 61, policy 33, frontend 5) · smoke 44 · migration roundtrip pass · secret scan clean.

### Known limitations (Milestone 2)
- No real IPO data is loaded. Only synthetic fixtures. Real data needs manual import (NSE/BSE) or enabling SEBI fetch (Q7).
- Scanned PDFs yield no text, so their fields stay "Not verified" until OCR (M3/M4). PDF parsing isn't sandboxed yet (threat model T-21, M3).
- IPO identity is the normalised company name; a company that withdraws and refiles shares one IPO record.
- The DB backstop is a coarse `jio` substring check; the precise matcher runs in the services.

## Unverified assumptions to resolve
- Indian IPO application rules in requirements §4 (verify against SEBI/RHP at M7).
- BSE terms of use (treated as manual-only until reviewed).
- Exact Google ADK APIs and current Gemini model IDs (at M4, against pinned versions).

## Later milestones
| Milestone | State |
|---|---|
| M3 Evidence ledger | planned |
| M4 Research orchestration | planned |
| M5 Validation & repair | planned |
| M6 Research UI | planned |
| M7 Calculator | planned |
| M8 Security & reliability | planned |
| M9 Stock intelligence | planned |
| M10 Observability & evals | planned |
| M11 Production deployment | planned |
| M12 Enterprise FDE extensions | planned |
