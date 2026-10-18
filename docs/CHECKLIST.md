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

## Milestone 2: IPO data ingestion (merged 2026-10-18, PR #2)

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

## Milestone 3: Evidence ledger (awaiting your verification)

| AC | Item | State | Evidence (run 2026-10-18) |
|---|---|---|---|
| 3.1 | Evidence is append-only for every role incl. the table owner (UPDATE/DELETE/TRUNCATE refused) | tested | Integration tests (as `app_ai` and as owner); smoke (2 owner probes) |
| 3.1 | Only exceptions: retention DELETE in an opted-in transaction; storage key NULL → value once | tested | `test_retention_purge_is_the_only_way_to_delete`, `test_retained_bytes_can_be_attached_once…` |
| 3.1 | Label assignments and set counters can't be rewritten | tested | `test_label_assignments_cannot_be_rewritten` |
| 3.2 | Same source + same bytes → one document, each retrieval logged | tested | Integration test; smoke (re-ingest → +12 retrievals, 0 duplicates) |
| 3.2 | Changed bytes → new version with `supersedes_id`; A → B → A is v1, v2, v3 | tested | `test_changed_bytes_make_a_new_version_that_supersedes` |
| 3.2 | Identical bytes from two sources share one content and one set of passages | tested | `test_identical_bytes_from_two_sources_share_one_content` |
| 3.2 | Stable labels d1, d2, …: idempotent, gap-free under 6 concurrent writers | tested | `test_labels_are_stable_idempotent_and_gap_free_under_concurrency`; every snapshot has a labelled set (smoke) |
| 3.3 | Page-level passages for PDFs; quotes located to a page; API cites the page | tested | Unit + integration; live API: Beta fresh issue → page 2 (smoke) |
| 3.3 | OCR for scanned pages with stored confidence | tested (container) | `test_ocr.py` (4) against rendered scans, Tesseract 5.3.0 |
| 3.4 | Tenant-private evidence invisible to other tenants (reader, passages, quote search, backend role) | tested | `test_private_evidence_is_invisible_to_other_tenants` |
| 3.4 | A set can't cite another tenant's document, even with RLS bypassed | tested | `test_a_set_cannot_cite_another_tenants_document` |
| 3.4 | A tenant can't write evidence as another tenant | tested | `test_a_tenant_cannot_write_evidence_as_another_tenant` |
| T-21 | PDFs parsed in a sandboxed subprocess (timeouts, crashes, output cap, no inherited secrets, memory limit) | tested | 7 sandbox tests incl. memory limit (Linux container) |
| — | Raw source bytes kept write-once by hash, integrity-checked on read, never served | tested | Blob store unit tests; smoke (every content retained; file count matches) |
| — | Migration 4 backfills Milestone 2 data and reverses cleanly, with and without data | tested | Dev DB backfill (12 docs → 12 contents/passages/retrievals); roundtrip script; rollback with data |
| — | PR #3 review: 10 findings, all real, all fixed with regression tests | tested | Backfill versions, canonical keys (Python = SQL, 13 vectors), lossless passage split, tenant key namespace, version timeline, safe rollback, streaming output cap (2 GB flood stopped at 8 MB), cross-page/passage quote location, `pages=[]`, cached normalisation. `scripts/check-evidence-backfill.sh` + 8 new tests |
| — | Dev database recreated after amending migration 4 | done | Held only synthetic fixtures (6 IPOs, 0 non-synthetic); re-ingested |

Totals: pytest 307 in the container (0 skipped; macOS skips 21 OCR/DB/Linux-only tests) · Vitest 99 · smoke 54 · migration roundtrip pass · backfill check pass · secret scan clean.

### Known limitations (Milestone 3)
- Retention purging is manual SQL; the scheduled job and its policy come later.
- OCR tests use clean rendered scans; real scanned prospectuses will have lower confidence. Confidence is stored so later milestones can down-weight it.
- The PDF worker isn't network-isolated (container egress policy, M11).
- No API endpoint serves evidence yet (`GET /research/{id}/evidence` arrives with reports in M4).

## Unverified assumptions to resolve
- Indian IPO application rules in requirements §4 (verify against SEBI/RHP at M7).
- BSE terms of use (treated as manual-only until reviewed).
- Exact Google ADK APIs and current Gemini model IDs (at M4, against pinned versions).

## Later milestones
| Milestone | State |
|---|---|
| M4 Research orchestration | planned |
| M5 Validation & repair | planned |
| M6 Research UI | planned |
| M7 Calculator | planned |
| M8 Security & reliability | planned |
| M9 Stock intelligence | planned |
| M10 Observability & evals | planned |
| M11 Production deployment | planned |
| M12 Enterprise FDE extensions | planned |
