# Acceptance Criteria

> Each criterion must be verified by a **run** test or a recorded manual check before it is ticked in [CHECKLIST.md](CHECKLIST.md). Requirement IDs refer to [requirements.md](requirements.md).

## Milestone 0: Requirements and architecture
- [ ] AC-0.1 Requirements doc with numbered FR/NFR, assumptions, open questions
- [ ] AC-0.2 System architecture + component diagram
- [ ] AC-0.3 Data-flow diagram with trust boundaries
- [ ] AC-0.4 Request lifecycle + Phase 2 extension
- [ ] AC-0.5 Threat model (STRIDE + LLM threats + exclusion bypass)
- [ ] AC-0.6 Source-provider strategy with hierarchy, freshness, adapter contract
- [ ] AC-0.7 Repository structure + planned commands
- [ ] AC-0.8 ADRs for each significant decision
- [ ] AC-0.9 **User review and approval** (ADRs move to Accepted)

## Milestone 1: Foundation
- AC-1.1 `docker compose up` starts postgres, api, ai-api, ai-worker, web from a clean clone with only `.env` copied from `.env.example`.
- AC-1.2 `GET /healthz` (liveness) and `/readyz` (DB reachable) return 200 on api and ai.
- AC-1.3 API → AI internal call succeeds with the service token and fails (401) without it.
- AC-1.4 `dbmate up` applies the initial migration. `dbmate down` then `up` succeeds again.
- AC-1.5 Typecheck, lint and unit tests pass in both languages (commands from the architecture doc), plus contract drift check.
- AC-1.6 gitleaks reports no secrets. `.env` is gitignored (verified with `git check-ignore .env`).

## Milestone 2: IPO ingestion
- AC-2.1 SearchPort with mock + manual-import + ≥1 permitted live adapter (behind a flag).
- AC-2.2 Every critical IPO field stored with source evidence ID and `checked_at`. A test fails if any field lacks provenance.
- AC-2.3 Status derivation tests: upcoming/open/closed/withdrawn/postponed, including the stale-"upcoming" case.
- AC-2.4 **Exclusion:** the shared vector file passes in TS and Python; an ingested Jio entity lands in `quarantined_entities` and never in `ipos`; DB trigger rejects jobs for non-allowed IPOs; API returns `ENTITY_EXCLUDED` for list, search, detail, research, calculate and evidence routes.
- AC-2.5 SSRF tests: private IP, redirect to private IP, and non-allowlisted domain are all blocked.

## Milestone 3: Evidence ledger
- AC-3.1 Evidence rows are append-only (UPDATE/DELETE denied for `app_ai` except by retention job role).
- AC-3.2 Same content fetched twice → one document version (hash dedup); stable `dN` IDs per report.
- AC-3.3 Page-level provenance for PDFs; OCR confidence stored for scanned pages.
- AC-3.4 Tenant-private evidence never returned to another tenant (test).

## Milestone 4: Orchestration
- AC-4.1 With `FakeModelPort` + mock providers, a full research run completes deterministically and produces identical output across runs.
- AC-4.2 SSE: events arrive in order; disconnect + reconnect with `Last-Event-ID` resumes with no gaps or duplicates; page reload after completion shows the final state.
- AC-4.3 Worker killed mid-job → job reclaimed → no duplicate sections/citations.
- AC-4.4 Each agent has documented contract, permitted tools, schemas, timeout and failure behaviour.
- AC-4.5 A live Gemini smoke test (opt-in) completes and records tokens and cost.

## Milestone 5: Validation and repair
- AC-5.1 T1: missing IDs, nonexistent IDs, and IDs from another report are all rejected.
- AC-5.2 T2 test table includes crore vs billion, lakh vs million, negative in parentheses, % vs pp, FY labels, consolidated vs standalone, and price-band ranges. Each mismatch is rejected.
- AC-5.3 Repair stops at 3 iterations, at the deadline, and on no-improvement. Unsupported claims are never published as verified (property test over random failure sequences).
- AC-5.4 Prompt-injection fixtures in evidence do not change validation outcomes or invoke tools.
- AC-5.5 Section states `ok/degraded/unavailable` derived by rules; tests per state.

## Milestone 6: Research UI
- AC-6.1 Discovery filters work; cards show provenance and timestamps.
- AC-6.2 Loading, empty, partial, error, retry and completed states each have an e2e test.
- AC-6.3 Each section shows Verified/Partial/Not found; source panel opens cited evidence and page.
- AC-6.4 XSS fixture in source text renders inert.
- AC-6.5 axe: no serious/critical violations on discovery, research and calculator pages.

## Milestone 7: Calculator
- AC-7.1 Unit and property tests for `Q`, `A`, `N_max`, budget boundaries (exactly affordable, ₹0.01 short, zero, huge), invalid prices, and non-integer lots.
- AC-7.2 Category rules (from cited rule data) enforced: RII cap, cut-off eligibility, min/max lots, with nearest valid alternatives shown.
- AC-7.3 No `number` arithmetic on money (lint rule + review).
- AC-7.4 Same package powers web preview and API authority; results identical for a shared test-vector file.

## Milestone 8: Security and reliability
- AC-8.1 Adversarial A/B tests: user B gets 404 for every user-A object on every route; RLS-level test with the wrong `app.tenant_id` returns zero rows.
- AC-8.2 Rate limits return 429 with `Retry-After`; idempotent research create returns the same `reportId`.
- AC-8.3 Circuit breaker transitions closed→open→half-open→closed tested with a fake clock.
- AC-8.4 Audit events written for login, report delete, and holding changes.
- AC-8.5 CSRF token required on state-changing routes.

## Milestones 9–12
Defined in detail at the start of each milestone. Baselines come from brief §§15, 18, 21, 22, 27 (Definition of Done).

## Release gate (brief §27)
All Definition-of-Done items verified against actual runs, **plus** legal review (requirements Q4) before any public use.
