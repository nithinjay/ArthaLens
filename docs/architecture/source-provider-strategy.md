# Source-Provider Strategy

> Milestone 0 · Status: **design; no provider has been integrated or verified yet**

## 1. Principles

1. **Official first.** Issue details come from exchange and issuer/offer documents. Everything else is context.
2. **Permitted access only.** Each provider is used only under its terms of use, robots policy and any licence. If programmatic access isn't clearly permitted, we don't scrape. We use manual import or a licensed vendor instead. *This needs a terms-of-use review per provider before Milestone 2 goes live, and it is tracked as an open item.*
3. **Everything behind `SearchPort`.** No other component makes outbound calls.
4. **Mock first, live opt-in.** Every adapter ships with a mock that replays **synthetic** fixtures. Live adapters run only when `PROVIDER_<NAME>_ENABLED=true`. CI never calls live providers except in an explicitly configured integration job.
5. **Record provenance, never invent.** Missing data stays `unverified`/`unavailable`.
6. **Freshness is explicit.** Each source type has a freshness SLA. Stale data is shown with a warning, never silently.

## 2. Provider tiers

| Tier | Authority class | Candidate sources | Used for | Access approach (to verify) |
|---|---|---|---|---|
| **T1** | `official_exchange` | NSE and BSE IPO/issue pages, public issue notices, corporate announcements, subscription (bid details) data | Dates, price band, lot size, status, subscription | NSE/BSE websites have no documented free public API; their sites restrict automated access. **Preferred:** licensed exchange data products or an authorised vendor. **Fallback:** manual admin import with the source URL recorded. |
| **T1** | `official_regulator` | SEBI: filed offer documents (DRHP/RHP), circulars, ICDR regulations | Offer documents, regulatory rules | Publicly published documents; fetch individual documents by URL with conservative rate limits after ToS review |
| **T1** | `issuer_filing` | RHP/prospectus hosted by issuer, BRLMs, exchange | Financials, risks, objects, promoters | Document fetch by URL; PDF parsing/OCR |
| **T2** | `official_registrar` | Registrar notices (allotment status pages) | Allotment stage | Read-only status where permitted; no user PAN is ever sent from our side |
| **T3** | `licensed_market_data` | Market-data vendors (to be selected) | Prices, peer metrics (Phase 2, Section C peers) | Paid API with licence that permits our display use |
| **T4** | `credible_news` | Established business news outlets | Context, Phase 2 news | Publisher RSS feeds or a licensed news API; store metadata + short excerpts + link, not full articles, unless licensed |
| **T5** | `unofficial` | GMP-tracking websites, forums | Section H (GMP), optional | **Disabled by default**, behind a feature flag; always labelled unofficial/speculative; shown only with ≥2 agreeing sources and timestamps |
| — | `manual_import` | Admin uploads a PDF or enters a field with source URL | Any gap above | Always available; audit-logged; marked with uploader and timestamp |

> **Gemini Google Search grounding** is *not* treated as a source. If used for discovery hints, the returned URLs must be fetched by a SearchPort adapter and ingested like any other document before anything is cited. Grounding has its own display/terms requirements, to be reviewed before use.

## 3. Source hierarchy per claim type

| Claim type | Accept from (highest first) | Conflict rule |
|---|---|---|
| Issue dates, price band, lot size, issue size | Exchange notice → RHP/Prospectus → issuer site | Latest-dated official source wins; discrepancy recorded and shown |
| Application rules, categories, cut-off eligibility | RHP "Issue Procedure" + SEBI ICDR/circulars | Issue-specific RHP terms override generic rules |
| Financial statements | RHP restated financials (label consolidated/standalone + period) | Never mix bases; restatements flagged |
| Subscription | Exchange bid details with timestamp | News figures shown only as "reported by X at T" |
| Peer metrics | Licensed market data; peers' own filings | Peer choice justified; missing → metric unavailable |
| Market/industry context | RHP industry section (cite as issuer-commissioned) → news | Labelled as context |
| GMP | Unofficial only | Never used in calculations |

## 4. Freshness policy (initial values; calibrate later)

| Data | Freshness target | Stale behaviour |
|---|---|---|
| IPO status/dates during the open window | ≤ 1 h | Show "last verified HH:MM", warning after 2 h |
| IPO status/dates outside the window | ≤ 24 h | Warning after 48 h |
| Subscription during bidding | Every exchange update, ≤ 30 min | Show "as of" time; never "final" until the exchange marks it final |
| Offer document | On new version (DRHP → RHP → addendum) | Report pinned to its snapshot version |
| Prices (P2) | Per provider (EOD/delayed) | Display provider delay class |
| News (P2) | Daily monitoring window | Incomplete window flagged |

## 5. Adapter contract

```python
class ProviderDescriptor(BaseModel):
    name: str                       # "sebi_offer_documents"
    authority: AuthorityClass
    allowed_domains: list[str]      # SSRF allowlist
    rate_limit: RateLimit           # rps, burst, daily cap
    timeout_s: float
    retry: RetryPolicy              # max_attempts, backoff, retry_on
    circuit: CircuitPolicy
    licence_ref: str                # link to ToS/licence review record
    display_rights: DisplayRights   # full_text | excerpt | metadata_only
    enabled: bool
```

Every adapter must:

- Emit `SourceHit`/`FetchedDocument` with full provenance fields (see brief §9).
- Normalise to UTF-8 text plus page anchors. Store raw bytes in object storage only if `display_rights` permits.
- Pass the exclusion filter before returning.
- Record `usage_records` (requests, bytes, cost) and OpenTelemetry spans.
- Have a mock twin plus contract tests that run the same assertions against mock and (opt-in) live.

## 6. Rollout plan

| Milestone | Providers |
|---|---|
| M2 | `MockExchangeProvider`, `MockOfferDocumentProvider` (synthetic), `ManualImportProvider`; first live candidate: SEBI offer-document fetch (after ToS review) |
| M2–M4 | Exchange data through licensed vendor **or** manual import (decision needed: budget for a vendor) |
| M4 | Document parsing + OCR for RHP PDFs |
| M9 | Market data + news provider(s) (decision needed) |
| Later | GMP adapter (flagged), local-inference alternatives for air-gapped mode with import-only sources |

## 7. Air-gapped mode (Stage 2)

Live sources and Gemini are unavailable without egress. Air-gapped deployments use `ManualImportProvider` and bundle imports, plus a local model behind `ModelPort` (Stage 8). The UI must say "offline mode: data as of the last import". We never claim live data offline.
