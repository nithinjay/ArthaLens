# ADR-0015: Source access per provider, and JSON Schema request validation

**Status:** Accepted · **Date:** 2026-10-18 · **Refines:** ADR-0002, ADR-0014, source-provider strategy

## Context
Milestone 2 needs official IPO data. The source-provider strategy requires a terms-of-use review before any live adapter is enabled. Separately, the first user-input routes (`/api/v1/ipos` filters) needed a request-validation approach.

## Decision 1: access per provider (reviewed 2026-10-18)

| Source | What its terms say | Decision |
|---|---|---|
| **NSE** (nseindia.com) | [Terms of Use](https://www.nseindia.com/static/nse-terms-of-use) bar "systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting)". | **No automated adapter.** NSE material enters only via **manual import** (a person downloads the notice in a browser and imports the file) or a licensed vendor later. |
| **BSE** (bseindia.com) | Terms not confirmed; `/robots.txt` returns an HTML page rather than a robots file. | Treated like NSE: **manual import only** until reviewed. |
| **SEBI** (sebi.gov.in) | [Website Policy](https://www.sebi.gov.in/website-policy.html): linking needs no permission; *reproducing* material needs permission by email; pages must not be framed. Nothing on automated access. `robots.txt` allows crawling except asset folders. | **Live fetch allowed for single public documents you name**, for private analysis. Off by default (`PROVIDER_SEBI_FETCH_ENABLED=false`). We store the hash, metadata and short cited quotes, link to the original, never frame it, and never republish the full text (`display_rights`). |
| Issuer / registrar sites | Vary per site. | Manual import until each is reviewed. |

This is an engineering reading of public terms, not legal advice. The release gate in requirements Q4 (legal review before any public launch) still applies.

### Fetcher guarantees (threat model T-20)
https only on port 443, no credentials, allow-listed domains only, every DNS answer must be a public address, a post-connect peer-address check against DNS rebinding, every redirect hop re-validated (max 3), robots.txt honoured (401/403 counts as disallow-all), MIME allow-list, 50 MB cap, no environment proxies, and an identifying user agent.

## Decision 2: "verified" means grounded
A field is `verified` only if its quote appears verbatim in the stored document, the raw value appears in the quote, and the value parses. The database enforces the provenance half (`verified_requires_provenance` CHECK). An authoritative source can't rescue a value its own document doesn't contain.

## Decision 3: request validation (refines ADR-0002 and ADR-0014)
Request schemas are plain **JSON Schema** validated by Fastify's built-in Ajv, with TypeScript types derived by `json-schema-to-ts` (type-only, no runtime cost). Response schemas are the generated contracts. The Zod type provider is **not** adopted, because one schema language across Python contracts, Fastify and OpenAPI beats two. Zod stays for environment config and, from Milestone 6, frontend forms.

## Consequences
- Live coverage of exchange data is manual until a licensed vendor is chosen (requirements Q2). The import format and runbook make that workflow practical.
- Turning on SEBI fetching is your call. It has been tested against a mock network only, never against the live site.
