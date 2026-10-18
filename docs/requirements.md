# Requirements

> Milestone 0 · Derived from [PROJECT_BRIEF.md](PROJECT_BRIEF.md). The brief is the full spec. This document turns it into numbered, testable requirements and records the assumptions and open questions.
> IDs are referenced by [acceptance-criteria.md](acceptance-criteria.md) and [CHECKLIST.md](CHECKLIST.md).

## 1. Scope

**In scope:** Indian IPOs (NSE, BSE; mainboard, and SME where reliable rules/data exist); educational research reports; deterministic application calculator; Phase 2 stock intelligence; production hardening.
**Out of scope (permanent):** automated IPO bid submission, trading, personalised investment advice, the Jio IPO.

## 2. Functional requirements

### Discovery & selection (FR-D)
- **FR-D1** List upcoming, open, closed, allotment/listing-stage, and withdrawn/postponed IPOs from verified sources, filterable by status, issue type, exchange, date, and research status.
- **FR-D2** Manual search and selection.
- **FR-D3** IPO cards show the fields in brief §5. Each critical field shows source and last-verified time; missing fields show "Not verified"/"Unavailable".
- **FR-D4** Status is derived from verified dates **and** official status. A stale "upcoming" label never implies an open issue.
- **FR-D5** A versioned IPO snapshot with per-field provenance is created before each research run.

### Research (FR-R)
- **FR-R1** Report sections A–J per brief §6, each resolving to `ok | degraded | unavailable`.
- **FR-R2** Every factual claim carries ≥1 valid evidence ID. Unsupported claims are quarantined or omitted.
- **FR-R3** Financials labelled with period, unit, and consolidated/standalone basis. Restatements flagged.
- **FR-R4** Derived metrics computed deterministically with the recorded formula. Issuer-reported vs calculated values are distinguished.
- **FR-R5** Peer selection justified. Missing inputs → metric unavailable.
- **FR-R6** Prospectus citations include document name, date, URL, and page/section.
- **FR-R7** Risks include evidence, citation, significance, and limitations. No unsupported allegations.
- **FR-R8** Subscription data shows category and publication time and is never presented as final unless the exchange marks it final.
- **FR-R9** GMP is optional, off by default, labelled unofficial, and never used in calculations.
- **FR-R10** Listing scenarios are illustrative with stated assumptions and no probabilities.
- **FR-R11** Summary is educational, with no subscribe/avoid instruction.
- **FR-R12** Progress is streamed via SSE. Reports are persisted and immutable; refresh creates a new version.

### Calculator (FR-C)
- **FR-C1** Inputs: budget (per IPO, not stored as a profile default), investor category, lots or auto, bid price or cut-off, optional buffer.
- **FR-C2** `Q = N × L`, `A = Q × P`, `N_max = floor(B / (L × P))`, plus issue- and category-specific min/max constraints. Nearest valid alternatives shown when `N_max` is invalid.
- **FR-C3** Reject bid prices outside the verified band and cut-off where not permitted for the category.
- **FR-C4** Exact arithmetic, INR formatting ([ADR-0006](decisions/0006-money-and-quantities.md)). Deterministic, with no LLM.
- **FR-C5** Shows remaining budget, warnings, data source and timestamp. States that blocked amount ≠ cost and allotment is not guaranteed.
- **FR-C6** Minimum / moderate / higher scenarios when valid. No borrowing encouragement.

### Stock intelligence, Phase 2 (FR-S)
- **FR-S1** Separate holdings (optional qty, avg price), watchlist, and wishlist entities.
- **FR-S2** Daily monitoring per brief §15, idempotent, with checkpoints and failed-run records.
- **FR-S3** Event dedup and clustering. Repeated coverage is not counted as confirmation.
- **FR-S4** Facts and AI interpretation visibly separated.
- **FR-S5** Deterministic, user-configured alerts with idempotent notifications.
- **FR-S6** Provider delay/limitations displayed.

### Exclusion (FR-X)
- **FR-X1** The Jio IPO is excluded across all surfaces listed in brief §2, enforced server-side in the layers of [ADR-0008](decisions/0008-jio-exclusion-policy.md).
- **FR-X2** Ambiguous matches are quarantined, with an explanation shown and no workflow generated.
- **FR-X3** Regression tests per surface, with the same test vectors in TS and Python.

## 3. Non-functional requirements

| ID | Area | Requirement |
|---|---|---|
| NFR-SEC1 | Isolation | No cross-user/tenant access by ID manipulation (API + RLS) |
| NFR-SEC2 | Secrets | No secrets in repo, logs, browser, model prompts, or reports |
| NFR-SEC3 | Untrusted content | Source content and model output are never executed or rendered as HTML; prompt injection cannot alter validation or tools |
| NFR-SEC4 | SSRF | Outbound fetches only via allowlisted SearchPort |
| NFR-REL1 | Timeouts | Deadlines on every external call and job |
| NFR-REL2 | Retries | Transient-only, backoff + jitter, bounded |
| NFR-REL3 | Breakers | Circuit breakers on providers and model API |
| NFR-REL4 | Idempotency | Research create, scheduled jobs, notifications |
| NFR-REL5 | Resume | Worker restart causes no duplicate reports/citations/alerts |
| NFR-OBS1 | Tracing | Trace ID propagated browser→API→DB→AI→providers |
| NFR-OBS2 | Metrics | Latency p50/95/99 per stage, tokens, cost per report, validation rates |
| NFR-COST1 | Budgets | Per-job token/cost budget; daily per-tenant and global caps; graceful degradation |
| NFR-A11Y1 | Accessibility | WCAG 2.2 AA target; keyboard navigable; axe clean on key pages |
| NFR-UX1 | Honesty | No false success indicators; stale-data warnings; loading/empty/partial/error/retry states |
| NFR-PERF1 | Latency (initial targets, to calibrate) | API p95 < 300 ms for reads; calculator < 50 ms server-side; first SSE event < 2 s after job creation; full report p95 < 10 min |

## 4. Domain rules catalogue: **to verify, not hard-code**

The calculator must enforce issue-specific rules. These are the *generally understood* rules that the M7 rule engine must model. **Each must be confirmed against the current SEBI ICDR Regulations/circulars and the specific RHP before use**, and stored as versioned, cited rule data:

| Rule | Current understanding (unverified) |
|---|---|
| Investor categories (mainboard) | QIB, NII (split into small NII and big NII by application size), Retail Individual Investor (RII), plus issue-specific employee and shareholder reservations; anchor investors are outside the public application flow |
| RII max application value | Up to ₹2 lakh |
| sNII / bNII thresholds | ~₹2–10 lakh / above ₹10 lakh |
| Cut-off bidding | Generally only RII (and eligible employee/shareholder reservation bidders); not QIB/NII |
| Minimum application | One lot (mainboard); SME minimum application size rules differ and were revised by SEBI, so they must be verified |
| UPI application limit | ASBA via UPI has a per-application cap (currently understood as ₹5 lakh), so higher amounts use other ASBA modes |
| Listing timeline | T+3 listing regime |

## 5. Assumptions

1. Single region (India), INR only, IST for display, UTC storage.
2. Early users are individuals (personal tenants). Enterprise tenancy is designed in from the start but exercised in Phase 3.
3. The Gemini key exists and has finite quota; model IDs are config.
4. No live data provider has been contracted. M2 begins with mocks + manual import + SEBI document fetch (after ToS review).
5. All seed/test data is synthetic and labelled as such.

## 6. Open questions (your input needed)

| # | Question | Proposed default if no answer |
|---|---|---|
| Q1 | Exclusion scope for already-listed Jio-named stocks in Phase 2 (see ADR-0008) | **Resolved 2026-10-17:** IPO scope only (default accepted) |
| Q2 | Budget for a licensed exchange/market-data vendor? | **Resolved 2026-10-17:** no vendor for Phase 1; manual import + permitted official documents (default accepted) |
| Q3 | Is GMP wanted at all? | Feature exists, disabled by default |
| Q4 | Will this ever be offered publicly (needs SEBI/DPDP legal review)? | Personal/learning use; legal review is a release gate |
| Q5 | Hosting target for M11 (GCP is natural with Gemini, but AWS/Azure are fine) | GCP |
| Q7 | Enable live fetching of individual public SEBI documents (`PROVIDER_SEBI_FETCH_ENABLED`)? See ADR-0015 | Off; manual import only |
| Q6 | Repo ownership: `/Library/WebServer/Documents/ArthaLens` is root-owned, so git reports "dubious ownership" | **Resolved:** ownership fixed; repo pushed to GitHub |
