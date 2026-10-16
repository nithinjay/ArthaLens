# ADR-0009: Deterministic-first validation and bounded repair

**Status:** Proposed · **Date:** 2026-10-17

## Context
The product's value depends on reports containing no unsupported facts. LLM self-checking is unreliable on its own.

## Decision
- Drafters must output **structured claims** with `source_ids` and machine-readable values, not free prose.
- Validation tiers: **T1** citation integrity → **T2** literal grounding (number/date/unit/scale/period/basis normaliser, derived metrics recomputed by the metrics engine) → **T3** model entailment, used *only* when T1/T2 can't decide, with a 5-way label.
- Normaliser handles: Indian scales (lakh = 10^5, crore = 10^7) vs million/billion; ₹/Rs./INR; negatives in parentheses `(12.3)`; percentages vs percentage points; fiscal-year labels (FY25 = 1 Apr 2024–31 Mar 2025; "Fiscal 2025"; "nine months ended Dec 31, 2024"); rounding tolerance only at the source's stated precision.
- Repair: failed claims only, max **3** iterations per section, section deadline, no-improvement early exit, retry and token/cost budgets. The validator never edits claims.
- Final state per section is `ok | degraded | unavailable`, decided by rules (required claims per section are defined in config).

## Initial budgets (to calibrate in M10 against the eval set)

| Budget | Initial value |
|---|---|
| Repair iterations / section | 3 |
| Section deadline | 180 s |
| Job deadline | 15 min |
| Broader retrieval rounds / section | 1 |
| Model retries / call (transient) | 2 |
| Token budget / job | configurable; default set after first measurement |

## Consequences
- + Most checks are fast, free and explainable ("scale mismatch" beats "the model said no").
- − The normaliser is a substantial piece of code needing extensive unit tests, which is the point of Milestone 5.
- − T3 remains probabilistic (see threat model, residual risks).
