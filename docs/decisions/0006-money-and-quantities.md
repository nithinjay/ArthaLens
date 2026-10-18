# ADR-0006: Exact money arithmetic

**Status:** Accepted · **Date:** 2026-10-17

## Context
The calculator and financial metrics must never suffer floating-point errors. In JS, `0.1 + 0.2 !== 0.3`, and `Number` loses integer precision above 2^53.

## Decision
- **TypeScript (calculator, `packages/ipo-rules`):** represent INR as **integer paise in `bigint`** (₹1 = 100 paise). Share quantities and lot counts are `bigint` or validated safe integers. Division is explicit floor division with a documented rounding rule. No `number` arithmetic on money.
- **Python (metrics engine):** `decimal.Decimal` with an explicit context (precision, `ROUND_HALF_EVEN` for display ratios). Values carry `{amount, unit, scale, currency, period, basis}`.
- **PostgreSQL:** `NUMERIC(20,2)` for rupee amounts, or `BIGINT` paise where the TS side owns the value (calculator scenarios). `NUMERIC` for ratios. Never `REAL`/`DOUBLE`.
- **Wire format:** money as **strings** in JSON (`"amount_paise": "1499700"`) so no JS client parses it into a float.
- **Display:** `Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' })` with Indian digit grouping (₹14,99,700), plus lakh/crore labels where helpful.

## Consequences
- + Deterministic, testable to the paisa. Property-based tests (fast-check / Hypothesis) on budget boundaries.
- − Slightly more verbose code, and conversions at the edges must be tested.

## Alternatives
- **decimal.js in TS:** fine, but integer paise is simpler for add/multiply/floor-divide, which is all the calculator needs.
- **Floats with rounding:** rejected.
