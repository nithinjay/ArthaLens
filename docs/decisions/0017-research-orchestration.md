# ADR-0017: Research orchestration (Milestone 4) and its scope

**Status:** Accepted · **Date:** 2026-10-18 · **Implements:** ADR-0003, ADR-0004, ADR-0005 · **Refines:** ADR-0010

## Context
Milestone 4 connects the request lifecycle end to end: create a report, run sections in parallel, stream progress, persist the result. Claim validation (T2/T3, bounded repair) is Milestone 5, so this milestone must not present drafted claims as checked facts.

## Decisions

### Scope of sections
| Section | Milestone 4 | Why |
|---|---|---|
| A Company overview, E Prospectus, F Risks | Drafted by the model from planned passages | Text sections; the evidence is in offer documents |
| D IPO structure | **Deterministic**, from the snapshot's verified fields (no model) | Every value was already grounded at ingestion; no reason to let a model restate it |
| J Summary | Drafted from the other sections' claims, reusing their citations only | Can't introduce new facts or sources |
| B Financials, C Valuation | "Not found: planned for Milestone 5" | Need the deterministic metrics engine and numeric grounding, which belong with the validator |
| G Subscription, H GMP, I Listing scenarios | "Not found", with the reason | No official subscription source yet; GMP off by default; scenarios come with the calculator (M7) |

### Honest states before validation
- Drafted claims are stored as `unverified` (or `quarantined` when they cite a label the agent wasn't shown). Nothing drafted is `verified` until the Milestone 5 validator passes it.
- Drafted sections can be at most `degraded` (shown as **Partial**). A database CHECK forbids `ok` while `validation = 'pending'`.
- So every Milestone 4 report ends `completed_degraded`. Section D can be **Verified** because it is deterministic.

### ADK usage
- `SequentialAgent[ ParallelAgent[A..I], J ]`. Each section is a custom `BaseAgent` that calls our `ModelPort`. Agents have **no tools**. Evidence is sent as delimited data in the user message, never in instructions, and any delimiter inside source text is neutralised.
- A section's failure (model error, timeout, budget, bug) becomes an honest "Not found" for that section and never aborts the others. Only infrastructure failures (database) fail the attempt, which is then retried.
- Pinned `google-adk==2.12.0`. It caps `opentelemetry-api` at 1.42.1, so FastAPI is held at `>=0.141.1,<0.143` until ADK relaxes that cap.

### Models
- `FakeModelPort` (deterministic, offline) is the default for development and every test; its reports carry the model name `fake-deterministic`. The worker refuses it when `APP_ENV=production`.
- `GeminiModelPort`: temperature 0, JSON response schema, timeout, retries for 408/429/5xx only (exponential backoff with jitter, max 2). **No default model id**: `GEMINI_MODEL` must be set, chosen from `python -m arthalens_ai.research.models`. Cost is recorded only if `GEMINI_INPUT_USD_PER_MTOK` and `GEMINI_OUTPUT_USD_PER_MTOK` are configured; otherwise `estimated_cost_usd` is NULL, never guessed.

### Jobs, checkpoints, events
- `claim_research_job()` (SECURITY DEFINER) is the only cross-tenant step. The worker then works under the job's tenant with RLS.
- Lease 60 s, renewed every 20 s. An expired lease is reclaimable; jobs out of attempts are failed, not left running.
- Each section commits together with its claims, citations, usage and `section.completed` event, so a crash leaves a section either fully saved (skipped on retry) or absent.
- Event `seq` is gap-free per report (advisory lock), and `pg_notify` carries only the report id. SSE: subscribe, then replay, then follow; heartbeats double as polling; the stream closes after `job.completed`, `job.failed` or `job.rejected`.

### Identity until Milestone 8 (refines ADR-0010)
`AUTH_MODE=dev` signs every request in as one seeded dev tenant and user (`scripts/seed-dev.sh`). The backend refuses it when `NODE_ENV=production`. Without it, research endpoints answer 401. Reports are owned by user and tenant; another user's report is a 404, the same as a missing one.

## Consequences
- The pipeline, streaming and persistence are proven end to end with a fake model, but no Gemini call has been made yet (requirements Q8).
- Milestone 5 adds the validator, which upgrades `pending` sections and `unverified` claims, plus sections B and C.
