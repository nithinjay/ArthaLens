# Agent Contracts

> Milestone 4 · Brief section 8 requires, for every agent: responsibility, permitted tools, input schema, output schema, failure behaviour and timeout. Code: `ai/arthalens_ai/research/`.

All agents share these rules:
- **Tools: none.** No agent can fetch, search, write evidence or approve claims.
- **Input:** a `ResearchDeps` bundle prepared by the worker (planned passages, snapshot fields, the model port, token budget, deadline).
- **Output:** a `SectionResult` saved atomically with its claims, citations, usage and a `section.completed` event.
- **Failure:** any error inside a section becomes `status = unavailable` with a reason. Only database failures fail the job attempt (then retried, up to 3 attempts).
- **Timeout:** `RESEARCH_SECTION_DEADLINE_SECONDS` (default 180 s) per section, inside `RESEARCH_JOB_DEADLINE_SECONDS` (default 900 s) per job. Token budget: `RESEARCH_TOKEN_BUDGET` (default 200,000) per job.
- **Exclusion:** each agent re-checks the policy before running (layer L4); a match stops the whole run (`job.rejected`).

| Agent | Responsibility | Input | Output | Model? | Specific failure behaviour |
|---|---|---|---|---|---|
| **Retrieval planner** (`planner.py`) | Choose up to 12 passages / 16,000 chars per section by keyword relevance; deterministic ordering | The report's labelled passages | `SectionPlan` (passages, covered, reason) | No | No relevant passage → `covered=false` → section "Not found: no passage addresses this section" |
| **A Company overview** | Business, products, customers, competitors, promoters, management | Planned passages, rendered as `<evidence>` data | `SectionDraft` → `SectionResult` | Yes (`common.v1 + A.v1`) | Model timeout / invalid JSON / provider error → unavailable with the code; budget → unavailable "Skipped" |
| **E Prospectus analysis** | Objects of the issue, litigation, related parties, contracts, shareholders | same | same | Yes (`E.v1`) | same |
| **F Risk assessment** | Disclosed risks, stated factually, no allegations | same | same | Yes (`F.v1`) | same |
| **D IPO structure** | Restate verified snapshot fields with their source, page and quote | Snapshot fields + report labels | `SectionResult`, `validation = deterministic` | **No** | Unverified/conflicting fields → listed as missing; all critical fields verified → **ok**, some → degraded, none → unavailable |
| **J Summary** | Up to 8 summary claims reusing other sections' citations | Non-quarantined claims of A, D, E, F | `SectionDraft` → `SectionResult` | Yes (`J.v1`) | No source claims → unavailable; a citation not taken from those claims → quarantined |
| **B, C, G, H, I** | Not implemented yet | — | `unavailable` with the stated reason | No | — |
| **Citation integrity (T1)** (`integrity.py`) | Drop citations to labels the agent wasn't shown; locate quotes to pages | Draft + shown passages | `FinalClaim`s: `unverified` or `quarantined` | No | Never marks anything verified |

## Model output schema (`SectionDraft`)

```json
{
  "claims": [
    {
      "text": "One factual statement",
      "claim_type": "risk",
      "citations": [{ "label": "d2", "quote": "verbatim text from passage d2" }]
    }
  ],
  "missing": ["information the evidence does not contain"]
}
```
Limits: 25 claims, 5 citations per claim, quotes ≤ 1,000 chars, `extra` keys forbidden. Output that doesn't parse against this schema is rejected (`invalid_output`); it is never repaired by guessing.

## Prompts
Versioned files in `research/prompts/`. The stored `prompt_version` is `common.v1+F.v1@<sha256 prefix>`, so an edit made without a version bump still shows up in results.
