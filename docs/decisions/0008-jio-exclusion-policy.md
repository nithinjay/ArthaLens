# ADR-0008: Jio exclusion: policy-as-data, layered, fail-closed

**Status:** Accepted · **Date:** 2026-10-17

## Context
The brief mandates excluding "the Jio IPO" from discovery, search, research, cached reports, calculators, jobs, notifications, API/direct access, and fixtures. Enforcement must happen server-side at the domain and retrieval layers. Ambiguous matches must be quarantined with an explanation.

The rule has to be enforced in both services (the API serves routes, the AI service ingests), but the brief also says not to duplicate domain rules.

## Decision

### 1. Policy as data, single source
`packages/policy/exclusions.v1.json` (versioned, reviewed via PR):

```json
{
  "version": 1,
  "rules": [{
    "rule_id": "EXCL-JIO-001",
    "scope": ["ipo"],
    "reason": "Product policy: Jio IPO excluded",
    "match": {
      "name_tokens": ["jio"],
      "aliases": ["reliance jio", "jio platforms", "reliance jio infocomm"],
      "identifiers": { "isin": [], "cin": [], "nse_symbol": [], "bse_code": [] }
    },
    "ambiguous_action": "quarantine"
  }]
}
```

Identifier lists start **empty**. They are filled only from verified official sources, never guessed. Name matching does the work until then.

### 2. Shared test vectors
`packages/policy/exclusion-vectors.v1.json` lists inputs → expected `{excluded | quarantined | allowed}`. The TS and Python matchers are each small (~50 lines) and **both must pass the identical vector file in CI**. The logic exists twice, but the rule and its truth table exist once.

### 3. Matching algorithm (both languages)
NFKC normalise → case-fold → map common confusables (`0→o`, `1→i`, `l→i` only in the confusable pass) → strip punctuation → tokenise. Then:
- Identifier match or exact token `jio` in an **IPO entity name** → `excluded`
- Alias match → `excluded`
- Fuzzy/confusable-only match (e.g. `J1O Platforms`), or an issuer whose parent/promoter disclosure names a Jio entity → `quarantined`
- Otherwise → `allowed`

### 4. Enforcement layers (fail closed)

| # | Layer | Action |
|---|---|---|
| L1 | Ingestion (AI) | Matching entities go to `quarantined_entities`, **never** into `ipos` |
| L2 | Database | `ipos.exclusion_status` check constraint plus trigger: inserts into `research_jobs`, `ipo_calculation_scenarios` and `notification_jobs` referencing a non-`allowed` IPO are rejected |
| L3 | API | Fastify `preHandler` on every IPO-addressed route (`/ipos/:id/*`, `/research/*` via report→ipo) and list/search filters return `ENTITY_EXCLUDED` problem JSON |
| L4 | Worker | Re-check before snapshot, before each section, and before composing |
| L5 | SearchPort | Evidence hits primarily about an excluded entity are dropped (logged with rule ID) |
| L6 | Cache/history | A policy version bump triggers a job that marks any pre-existing matching reports `withdrawn_by_policy` (hidden, retained for audit) |
| L7 | Jobs & notifications | Scheduler and notifier re-check |

Every hit writes an `audit_events` row with `rule_id`, layer and normalised input.

### 5. User-facing behaviour
"This IPO is excluded from ArthaLens by product policy. No research, calculations or alerts are available for it." No partial content is generated.

### 6. Fixtures
Test fixtures use **synthetic** entities only. Exclusion tests use names like "Jio Platforms Limited (SYNTHETIC TEST ENTITY)" purely as matcher inputs. They never get a research workflow.

## Open question (needs your decision)
Does the exclusion extend to **already-listed Jio-named stocks** in Phase 2 watchlists/holdings (for example Jio Financial Services, which is listed and not an IPO), or to the Jio Platforms stock after it lists?
**Proposed default:** rule scope is `ipo` only. Listed stocks are allowed in Phase 2, but any monitoring item that concerns the Jio IPO itself is quarantined. Changing this means adding `"stock"` to `scope`, which is a data change, not code.

**Resolution (2026-10-17):** default accepted with Milestone 0 approval: scope is `ipo` only.

## Consequences
- + Easy to audit; multiple independent layers; a missed layer is caught by another.
- − Name-token matching may over-exclude unrelated names containing the token `jio`. That is acceptable as fail-closed, and overrides require an explicit `allow` entry with justification.
