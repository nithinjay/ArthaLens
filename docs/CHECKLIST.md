# Project Checklist

Legend: **done** = written/implemented · **tested** = verified by a test or check that was actually run · **planned** = not started · **unverified** = assumption not yet confirmed

_Last updated: 2026-10-17_

## Milestone 0: Requirements and architecture (approved 2026-10-17)

| Item | State | Location |
|---|---|---|
| Requirements, lifecycle, architecture, DFD, threat model, source strategy | done | [requirements.md](requirements.md), [architecture/](architecture/), [security/threat-model.md](security/threat-model.md) |
| ADRs 0001–0013 | done (Accepted) | [decisions/](decisions/README.md) |
| Acceptance criteria | done | [acceptance-criteria.md](acceptance-criteria.md) |
| Open questions Q1, Q2, Q6 | resolved | [requirements.md §6](requirements.md) |
| Mermaid diagrams render | unverified | Not rendered in a session; check on GitHub |

## Milestone 1: Project foundation (awaiting your verification)

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
- Exclusion policy (`packages/policy`) → M2

## Unverified assumptions to resolve
- Indian IPO application rules in requirements §4 (verify against SEBI/RHP at M7).
- Terms of use for NSE/BSE/SEBI programmatic access (before M2 live adapters).
- Exact Google ADK APIs and current Gemini model IDs (at M4, against pinned versions).

## Later milestones
| Milestone | State |
|---|---|
| M2 IPO ingestion + exclusion | planned |
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
