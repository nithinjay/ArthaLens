# IPO Research & Stock Intelligence Agent
## Master Product, Architecture and Implementation Prompt

## 1. Your Role

Act as a **Forward Deployed Engineer (FDE), Principal AI Engineer, Full Stack Architect, Security Engineer, Data Engineer, DevOps Engineer, QA Engineer, and technical mentor**.

Your responsibility is to design, implement, test, document, and prepare a complete production-ready web application called **IPO Research & Stock Intelligence Agent**.

Do not build only a chatbot or a static dashboard. Build a reliable, evidence-grounded research platform that integrates official financial information, company filings, market data, AI research agents, financial calculations, user preferences, and scheduled stock monitoring.

Teach me as you build. Explain why every significant design decision is made, show each implementation step, provide complete working code for the current milestone, run or specify tests, and wait for verification before advancing.

Do not dump the entire codebase in one response. Maintain a clear implementation checklist and work incrementally.

---

## 2. Product Vision

Build a web application that helps users:

1. Discover and select upcoming, open, and recently closed IPOs in India.
2. Understand the company behind an IPO before making a decision.
3. Research company financials, valuation, promoters, business model, risks, prospectus, subscription demand, and market context.
4. Verify official IPO details, including price band, lot size, issue dates, and application rules.
5. Calculate valid lot quantities, bid prices, estimated application amounts, and budget scenarios.
6. Compare research findings with source documents and citations.
7. Track stocks held by the user, maintain a watchlist and wishlist, and review relevant news every day.
8. Understand why a stock-related event may matter without treating an AI-generated forecast as fact.
9. Learn financial and technical concepts through explanations, source links, and step-by-step research.
10. Operate with production-grade security, reliability, observability, cost controls, and deployment automation.

### Market scope

- India only.
- NSE and BSE.
- Support the applicable IPO categories, investor eligibility rules, and issue-specific application rules as published by authoritative sources.
- Handle mainboard and SME IPOs when reliable data and the applicable application rules are available.
- Support public IPO research and educational analysis, not automated submission of investment applications.

### Mandatory exclusion

**Exclude the Jio IPO completely.**

Implement an explicit exclusion rule covering:

- IPO discovery and recommendations.
- Search and selection results.
- Research generation and cached reports.
- IPO application calculators.
- Background jobs and notifications.
- API endpoints and direct-object access.
- Test fixtures and regression tests.

Apply the exclusion at the server-side domain and retrieval layers, not only in the UI. If a matching or ambiguous entity is encountered, quarantine it and explain that it is excluded without generating an IPO research or application workflow for it.

---

## 3. Technology Stack

Use the following stack unless a documented technical limitation justifies a change.

### Frontend

- React.
- TypeScript.
- Vite.
- A maintainable component library and accessible design system.
- Responsive desktop and mobile layouts.
- Server-sent events (SSE) for live research progress.
- TanStack Query or an equivalent server-state management library.
- React Hook Form and Zod for validated forms.
- Charting for financial trends, allocation scenarios, and stock history.

### Application backend

- Node.js.
- TypeScript.
- Express.js or Fastify; select one and explain why.
- Zod or equivalent runtime validation.
- OpenAPI documentation.
- Centralized error handling, request validation, authentication, authorization, and API rate limiting.

This layer owns user-facing APIs, authentication, portfolio and watchlist operations, scheduled-job management, and coordination with AI services.

### AI services

- Python.
- FastAPI.
- Google ADK for agent orchestration.
- Gemini API for research synthesis and selected reasoning tasks.
- Pydantic for typed schemas.
- Pytest for unit and integration tests.
- An independent evidence ledger and hallucination validator implemented primarily in deterministic Python.

The AI service must expose typed, versioned APIs to the TypeScript backend. Avoid duplicating domain rules across both backends.

### Persistence and infrastructure

Recommended initial design:

- PostgreSQL as the main production database.
- SQLite only for isolated learning exercises or lightweight tests, not as an assumption for multi-instance production.
- PostgreSQL full-text search and pgvector when vector retrieval is useful.
- Redis for distributed rate limiting, caching, and job coordination when required.
- A durable task queue for scheduled research and stock monitoring.
- Object storage for retained research documents and source snapshots, where permitted.
- Docker Compose for local development.
- Terraform and Helm for later production deployment.
- OpenTelemetry for traces and metrics.

Choose the simplest architecture that meets the current milestone. Do not introduce Kubernetes, Redis, a separate vector database, or additional infrastructure without explaining the need.

### Model abstraction

Initially use Google ADK with Gemini, using the existing Gemini API key.

Keep model and embedding providers behind interfaces so the system can later support alternative providers or local models. Do not assume that Gemini API access, embedding access, quotas, or pricing are unlimited.

Store secrets in environment variables during local development and use a managed secret store in production. Never expose API keys to the frontend, source control, logs, or generated reports.

---

## 4. Product Phases

### Phase 1 — IPO Research and Application Planning

Deliver a working application that supports:

- IPO discovery and manual IPO selection.
- Official detail verification.
- Company research and structured reports.
- Financial analysis and valuation comparisons.
- Prospectus analysis.
- Risk identification.
- Subscription and optional unofficial GMP information.
- Lot quantity and bid-price calculations.
- Budget-based scenario comparison.
- Source citations and evidence validation.
- A research dashboard with streamed progress.
- Authentication and persistent research history.

### Phase 2 — Stock Intelligence

Add:

- User-defined stock watchlist.
- Holdings with optional quantity and average purchase price.
- Wishlist for stocks the user may consider buying.
- Daily news and official filing summaries.
- Price history and supported market-data integrations.
- Material-event detection and impact explanations.
- Configurable alerts.
- Portfolio performance calculations.
- A daily dashboard digest.

Do not assume the user owns a stock merely because it appears in a watchlist. Keep holdings, watchlists, and wishlists as separate entities.

### Phase 3 — Production Hardening

Add:

- Enterprise identity and SSO.
- Strong tenant isolation and row-level security.
- Advanced observability and cost attribution.
- Regression evaluation pipelines.
- Resilient scheduling and distributed execution.
- Deployment automation.
- Disaster recovery, backups, and restore testing.
- Optional enterprise integrations and local inference.

Design for all phases from the beginning, but implement them incrementally.

---

## 5. IPO Discovery and Selection

Provide two entry paths:

1. **Manual selection:** The user searches for and selects an IPO.
2. **AI discovery:** The application identifies upcoming, open, and recently closed IPOs using verified data.

IPO cards should display, when available:

- Company name.
- Exchange and issue type.
- IPO opening and closing dates.
- Price band.
- Lot size.
- Issue size.
- Fresh issue and offer-for-sale breakdown.
- Listing date or expected listing date, clearly identified as confirmed or estimated.
- Research status.
- Last verified timestamp.
- Links to official source documents.

Never invent missing dates, lot sizes, prices, or issue information.

When the data is incomplete, show “Not verified” or “Unavailable” rather than a fabricated value.

The system must distinguish:

- Upcoming IPO.
- Open IPO.
- Closed IPO.
- Allotment or listing stage, where verified.
- Withdrawn, postponed, or otherwise changed issues.

Do not assume that a company is accepting applications merely because an old source describes its IPO as upcoming.

Before a research run, create a versioned IPO snapshot containing the source of each critical field and the timestamp when it was checked.

---

## 6. IPO Research Workflow

For each selected IPO, generate a structured report containing the following sections.

### Section A — Company overview

- Company history and operating locations.
- Products and services.
- Business model and revenue streams.
- Customer and supplier concentration, where disclosed.
- Industry, competitors, and competitive advantages.
- Promoters, management, and governance.
- Business dependencies and major operating risks.

### Section B — Financial analysis

Analyze available historical financial periods, preferably using comparable audited figures.

Include:

- Revenue.
- Revenue growth.
- Profit or loss.
- Operating profitability and margins.
- Earnings per share when available.
- Debt and leverage.
- Cash flow.
- Return ratios where meaningful.
- Working capital and receivables.
- Related-party transactions and unusual financial trends.

Show units, periods, calculation formulas, source citations, and missing data.

Do not mix consolidated and standalone figures without explicitly labeling them. Identify changes in accounting periods, restatements, or inconsistent source definitions.

### Section C — Valuation

Where sufficient data exists, calculate and explain:

- Price-to-earnings ratio.
- Price-to-book ratio.
- Enterprise value to EBITDA where appropriate.
- Market capitalization at the issue price.
- Comparable listed-company metrics.
- Valuation relative to growth, profitability, debt, and risks.

Clearly distinguish issuer-reported figures from calculated metrics.

Peer selection must be justified by business model, scale, geography, growth, and profitability. Do not manufacture a peer group merely to support a conclusion.

If required inputs are missing, mark the metric unavailable.

### Section D — IPO structure and official details

Verify:

- Opening and closing dates.
- Price band.
- Lot size.
- Minimum application quantity.
- Issue size.
- Fresh issue versus offer for sale.
- Reservation categories.
- Application rules.
- Minimum and maximum quantities where applicable.
- Cut-off bidding eligibility.
- Use of proceeds.
- Registrar and other relevant official details.

Prefer the latest authoritative exchange documents, offer documents, and issuer disclosures.

### Section E — Prospectus analysis

Read and analyze the RHP/DRHP and other available official documents.

Extract:

- Business overview.
- Financial statements.
- Objects of the issue.
- Risk factors.
- Litigation and contingent liabilities.
- Promoter and shareholder details.
- Related-party transactions.
- Material contracts or dependencies.
- Industry information.
- Management discussion and analysis.

Include document names, publication dates, source URLs, and page numbers or section references when available.

Use document parsing and OCR for scanned PDFs where needed. Preserve page-level provenance so a user can verify a statement in the original document.

### Section F — Risk assessment

Identify and categorize risks such as:

- Financial weakness.
- Customer concentration.
- Regulatory exposure.
- Governance concerns.
- Promoter-related risks.
- Litigation.
- Industry cyclicality.
- Dependence on a small number of products or suppliers.
- Aggressive valuation.
- Uncertain or changing market conditions.

For every risk, provide:

- The factual evidence.
- Source citations.
- Potential significance.
- Known limitations or counterevidence.

Do not label a company fraudulent or make unsupported allegations. Clearly distinguish disclosed risks, analyst interpretation, and unverified claims.

### Section G — Subscription demand

When reliable data is available, show subscription information by investor category and the time at which the figures were published.

Distinguish official subscription statistics from news reports and commentary.

Do not present an incomplete or delayed subscription figure as final.

### Section H — Grey-market premium

GMP is optional and must be labeled unofficial, speculative, and potentially unreliable.

If a credible source is unavailable, omit the metric.

Never use GMP alone to estimate a guaranteed listing price, listing gain, or investment return. Explain that GMP can be manipulated, stale, or inconsistent across sources.

### Section I — Listing scenarios

Provide educational scenarios such as:

- Downside scenario.
- Neutral scenario.
- Upside scenario.

Explain the assumptions behind each scenario and the factors that might cause the result to differ.

Do not present scenario outputs as predictions with unsupported probabilities. Do not imply that historical performance guarantees future performance.

### Section J — Summary

Provide:

- Verified facts.
- Positive factors.
- Key concerns.
- Missing information.
- Valuation observations.
- Questions a reader should investigate further.
- Overall evidence confidence.
- Sources and last-updated timestamp.

Use an educational conclusion, not an unqualified instruction to subscribe or avoid an IPO.

---

## 7. Application Budget, Lot Quantity and Bid Calculator

Build an interactive calculator for every supported IPO.

### User inputs

- Maximum budget for the selected IPO.
- Investor category.
- Number of lots, or an automatic budget-based calculation.
- Bid price or cut-off selection where eligible.
- Optional buffer for additional costs.
- Optional scenario comparison.

The default is to ask for a separate budget for each IPO.

Do not require a permanent investment budget in the user profile.

### Calculation rules

Use verified official lot size, price band, application rules, and category eligibility.

Let:

- \(L\) = shares per lot.
- \(N\) = number of lots.
- \(P\) = selected valid bid price.

Then:

\[
Q = N \times L
\]

\[
A = Q \times P
\]

where \(Q\) is the total share quantity and \(A\) is the indicative application amount.

For a budget \(B\), the maximum affordable whole-lot count under a simplified calculation is:

\[
N_{\max} =
\left\lfloor \frac{B}{L \times P} \right\rfloor
\]

The final implementation must also enforce the actual IPO's application rules and category-specific quantity constraints. If the maximum affordable quantity is not a valid application quantity, explain the restriction and show the nearest valid alternatives.

Display:

- Shares per lot.
- Number of lots.
- Total quantity.
- Selected bid price.
- Indicative amount.
- Budget remaining.
- Applicable charges or other relevant costs, if known.
- Any eligibility or quantity-rule warnings.
- Data source and verification timestamp.

Clearly distinguish the bid amount or blocked funds from a fee, final purchase cost, and eventual allocation. IPO allotment is not guaranteed.

### Bid price modes

Support:

1. A specific price within the verified official price band.
2. Cut-off bidding where the selected investor category and issue permit it.
3. A comparison of permitted bid-price scenarios.

Reject prices outside the permitted band and invalid quantity combinations.

Do not assume that selecting the highest bid guarantees allotment or that cut-off bidding is always available.

### Lot recommendation experience

The application must answer questions such as:

- How many lots fit within my stated budget?
- What is the indicative amount for one, two, or more lots?
- How much of my budget remains?
- What are the differences between the available bid options?
- What happens if I use a smaller or larger allocation scenario?

Offer minimum, moderate, and higher-budget scenarios when valid. Explain the cash commitment and uncertainty of each scenario.

The application may calculate an affordable quantity and compare user-defined scenarios. It must not pretend to know the user's full financial circumstances or issue a definitive personalized investment instruction.

Do not encourage borrowing, excessive concentration, or committing money needed for essential expenses. The user must make the final decision.

All financial calculations must use decimal-safe arithmetic, validated integer quantities, and currency formatting in INR. Never use floating-point arithmetic for money calculations when it could introduce rounding errors.

---

## 8. AI Agent Architecture

Use Google ADK to orchestrate bounded research agents.

Start with a central orchestrator and clearly defined research components. Use multiple specialized agents only where they provide meaningful separation of responsibilities.

Suggested components:

1. **IPO Discovery Service** — discovers and validates candidate IPOs.
2. **Retrieval Planner** — determines which authoritative sources and query sets are needed.
3. **SearchPort** — abstracts search providers, official-source retrieval, document retrieval, and market-data adapters.
4. **Evidence Ledger** — stores retrieved source records.
5. **Company Research Agent** — prepares the business overview.
6. **Financial Analysis Agent** — analyzes financial statements and calculates supported metrics.
7. **Valuation Agent** — evaluates valuation metrics and comparable companies.
8. **Prospectus Agent** — extracts disclosures, risk factors, and issue details.
9. **Market Context Agent** — summarizes verified subscription data, market context, and optional GMP.
10. **Validator** — checks evidence and claim support.
11. **Repair Controller** — coordinates bounded redrafting of failed sections.
12. **Report Composer** — assembles validated sections and their citations.
13. **Stock News Agent** — introduced in Phase 2.
14. **Stock Impact Explainer** — introduced in Phase 2.
15. **Notification Scheduler** — introduced in Phase 2.

Research sections may run in parallel when they are independent. Avoid parallel calls that duplicate the same searches or exceed source-provider limits.

Use typed request and response contracts between agents. Each agent must have a documented responsibility, permitted tools, input schema, output schema, failure behavior, and timeout.

---

## 9. Evidence Ledger

Every retrieved document must receive a stable evidence identifier such as `d1`, `d2`, and `d3`.

Each record should contain:

- Evidence ID.
- Document or source identifier.
- Canonical URL.
- Title.
- Publisher or issuing organization.
- Publication date, if available.
- Retrieval timestamp.
- Relevant text or extracted passages.
- Document hash or version.
- Page or section reference, when applicable.
- Source type.
- Authority classification.
- Data freshness.
- Retrieval method and relevant request metadata.

Only the retrieval and ingestion layer may create or modify evidence records. Research agents may read evidence but cannot fabricate source identifiers or silently rewrite source content.

Preserve source snapshots when legally and operationally permitted. Otherwise retain the permitted metadata, hashes, and citations needed to reproduce the research.

Treat all retrieved web pages and documents as untrusted data. They may contain prompt injections or instructions designed to manipulate the agent. Such instructions must never override system policies or authorize tools.

Every factual claim in a research report must carry one or more valid source IDs.

Example conceptual claim:

```json
{
  "claim_id": "claim-001",
  "text": "The company reported revenue of ...",
  "source_ids": ["d1"],
  "claim_type": "financial",
  "status": "verified"
}
```

The numerical value must be grounded in the cited source. The example is a schema illustration, not a claim about a real company.

---

## 10. Hallucination Validation and Bounded Repair

Implement a deterministic-first validation pipeline.

### Tier 1 — Citation integrity

Check that:

- Every factual claim includes source IDs.
- Every referenced evidence ID exists.
- Citations point to retrievable evidence.
- The citation supports the specific claim and is not merely related to the topic.

### Tier 2 — Literal grounding

Check numbers, dates, percentages, currencies, quantities, and financial metrics against cited evidence.

Normalize common number representations when comparing values, while preserving currency, scale, period, units, and context.

For example, distinguish ₹9.4 crore from ₹9.4 billion. Never accept a numerically similar value if its units or reporting period differ.

Implement explicit handling for:

- Negative values.
- Percentages.
- Currency conversions.
- Rounding.
- Fiscal years.
- Share counts.
- Price bands.
- Financial ratios.
- Derived values.

Derived metrics must be recomputed from validated inputs and their formulas must be recorded.

### Tier 3 — Semantic entailment

Use a small, bounded model call only when deterministic checks cannot determine whether prose is supported by the cited source.

The entailment check must distinguish:

- Directly supported.
- Partially supported.
- Contradicted.
- Not supported.
- Insufficient evidence.

An LLM judgment is an additional quality signal, not an absolute guarantee of correctness.

### Repair policy

When validation fails:

1. Quarantine the unsupported claim.
2. Produce structured validation feedback.
3. Redraft only the affected section where possible.
4. Revalidate the new draft.
5. Accept only claims that pass the required checks.

Set:

- Maximum three drafting/repair iterations per section.
- A wall-clock deadline.
- An early exit if an iteration makes no meaningful improvement.
- Per-provider and per-section retry limits.
- A token and cost budget.

**Never allow unsupported claims to become trusted merely because the repair loop has ended.** If a claim cannot be verified, omit it or label it explicitly as unavailable.

The validator must not independently rewrite failed claims and then approve its own output without another validation pass.

---

## 11. Adaptive Retrieval and Honest Degradation

Retrieval depth must depend on evidence quality rather than a fixed number of searches.

For each report section:

1. Run a predefined first-pass query set.
2. Retrieve documents from authoritative sources.
3. Record them in the evidence ledger.
4. Evaluate source coverage and relevance.
5. If evidence is missing or insufficient, run one bounded broader retrieval round.
6. Draft the section.
7. Validate every claim.
8. Repair failed claims within the configured limits.

Do not repeat searches if an authoritative source already provides adequate evidence.

Use a source hierarchy appropriate to the claim:

- Official exchange disclosures and issuer filings for issue details.
- SEBI publications and relevant official documents for applicable regulatory information.
- Audited financial statements and prospectuses for reported financials.
- Official exchange data or appropriately licensed providers for market information.
- Credible news organizations for independent context.
- Unofficial sources only when clearly labeled and appropriate.

Source hierarchy must not be treated as an excuse to ignore contradictory evidence. Record material discrepancies and show the source dates.

### Section status

Each section must resolve to one of three states:

- `ok`: required claims have passed validation.
- `degraded`: useful evidence exists, but some claims were removed or remain uncertain.
- `unavailable`: sufficient evidence could not be retrieved or validated.

The UI should translate these states into:

- Verified.
- Partial.
- Not found.

Do not silently fill missing information with an LLM-generated guess.

---

## 12. APIs and Data Contracts

Implement versioned APIs with OpenAPI documentation.

### IPO endpoints

- `GET /api/v1/ipos` — list and filter supported IPOs.
- `GET /api/v1/ipos/{ipoId}` — retrieve verified IPO details.
- `POST /api/v1/ipos/{ipoId}/research` — create a research job.
- `GET /api/v1/research/{reportId}` — retrieve the report.
- `GET /api/v1/research/{reportId}/events` — stream progress through SSE.
- `GET /api/v1/research/{reportId}/evidence` — retrieve permitted evidence references.
- `POST /api/v1/ipos/{ipoId}/calculate` — calculate valid lot and bid scenarios.
- `GET /api/v1/research` — list the user's research history.
- `DELETE /api/v1/research/{reportId}` — delete a report according to the retention policy.

### Phase 2 stock endpoints

- `GET /api/v1/stocks/watchlist`
- `POST /api/v1/stocks/watchlist`
- `DELETE /api/v1/stocks/watchlist/{itemId}`
- `GET /api/v1/stocks/holdings`
- `POST /api/v1/stocks/holdings`
- `PATCH /api/v1/stocks/holdings/{holdingId}`
- `DELETE /api/v1/stocks/holdings/{holdingId}`
- `GET /api/v1/stocks/wishlist`
- `POST /api/v1/stocks/wishlist`
- `DELETE /api/v1/stocks/wishlist/{itemId}`
- `GET /api/v1/stocks/{stockId}/news`
- `GET /api/v1/stocks/{stockId}/summary`
- `GET /api/v1/stocks/{stockId}/prices`
- `GET /api/v1/alerts`
- `POST /api/v1/alerts`
- `PATCH /api/v1/alerts/{alertId}`
- `DELETE /api/v1/alerts/{alertId}`

Define consistent pagination, validation, authentication, authorization, error formats, request IDs, and rate limits.

Use idempotency keys for operations where retries could create duplicate jobs or records. Idempotency keys must be scoped to the authenticated user or tenant, operation, and request semantics.

Do not allow client-provided user IDs or tenant IDs to override authenticated identity.

---

## 13. Database Design

Use PostgreSQL as the recommended production database.

Design normalized tables for the following entities:

- `users`
- `tenants`
- `memberships`
- `roles`
- `permissions`
- `ipos`
- `ipo_snapshots`
- `research_reports`
- `research_sections`
- `research_jobs`
- `evidence_documents`
- `evidence_claims`
- `claim_citations`
- `financial_metrics`
- `ipo_calculation_scenarios`
- `stocks`
- `watchlist_items`
- `holdings`
- `wishlist_items`
- `stock_news`
- `price_snapshots`
- `alerts`
- `notification_jobs`
- `audit_events`
- `evaluation_runs`
- `usage_records`

Include primary keys, foreign keys, unique constraints, indexes, timestamps, and migration scripts.

Requirements:

- Use immutable or versioned research snapshots where auditability matters.
- Track the source and timestamp of every important external value.
- Separate a stock's identity from a user's watchlist, wishlist, and holding records.
- Preserve historical reports when source data changes, subject to retention policies.
- Enforce tenant isolation through database and application authorization.
- Store monetary values in appropriate exact decimal types.
- Avoid storing unnecessary sensitive financial information.
- Document retention, deletion, and backup policies.

---

## 14. User Interface

Build a professional financial research dashboard.

### Main navigation

- Dashboard.
- Discover IPOs.
- IPO Research.
- Budget Calculator.
- My Watchlist.
- My Holdings.
- Wishlist.
- News and Alerts.
- Research History.
- Settings.

### IPO discovery screen

Provide filters for issue status, issue type, exchange, dates, and research status.

Show price band, lot size, dates, verification timestamp, and a link to the detailed research view.

### IPO research screen

Display:

- Overall research status.
- A section-by-section progress indicator.
- Live research events.
- Verified facts and citations.
- Financial charts.
- Risk analysis.
- Valuation comparisons.
- Prospectus references.
- Missing information.
- A source panel with document titles, publishers, dates, URLs, and page references.

Each section must visibly indicate Verified, Partial, or Not found.

### Calculator screen

Let users adjust budget, bid price, and lot quantity. Recalculate the result immediately using deterministic application code rather than an LLM.

Display valid scenarios, budget remaining, eligibility warnings, and assumptions.

### Stock intelligence screen

Display:

- Stocks held.
- Watchlist stocks.
- Wishlist stocks.
- Latest relevant news.
- Official filings and company announcements.
- Price history where available.
- Source-backed event explanations.
- Last-updated time.
- Alert settings.

Clearly distinguish reported facts from AI interpretation.

### UI requirements

- Accessible labels, keyboard navigation, and sufficient contrast.
- Responsive design.
- Loading, empty, partial-data, error, and retry states.
- No false success indicators.
- Clear timestamps and stale-data warnings.
- Safe rendering of untrusted source content.
- No exposure of internal secrets or other users' records.

---

## 15. Phase 2 — Daily Stock News and Monitoring

Create a scheduled monitoring pipeline.

For each stock selected by the user:

1. Identify relevant official announcements and news published since the previous successful run.
2. Deduplicate stories using canonical URLs, source IDs, and content fingerprints.
3. Verify publication time and distinguish it from the event date.
4. Retrieve supporting evidence.
5. Classify the event, for example as financial results, regulatory action, management change, litigation, business development, or industry news.
6. Generate a concise source-grounded summary.
7. Explain possible implications and uncertainty.
8. Record the run, sources, and last successful checkpoint.
9. Display the digest in the dashboard.
10. Trigger only user-configured alerts that satisfy their conditions.

Do not treat repeated coverage of one event as independent confirmation.

Track stale feeds, failed source retrieval, and incomplete monitoring windows.

Do not promise continuous or real-time updates when a provider offers only delayed or periodic data. Clearly display provider limitations.

Daily monitoring must not silently stop after an error. Record failed jobs and make safe, bounded retries.

Use idempotent scheduled jobs so that reruns do not create duplicate news records or alerts.

---

## 16. Reliability Engineering

Apply reliability controls throughout both backend services.

### Timeouts and retries

- Define deadlines for API requests, external retrieval, model calls, database operations, and research jobs.
- Retry only transient and recoverable failures.
- Use exponential backoff with jitter.
- Respect provider retry instructions and rate-limit responses.
- Set maximum retry attempts and total wall-clock budgets.
- Do not retry non-idempotent operations without safe deduplication.

### Circuit breakers

Implement circuit breakers for external search providers, market-data providers, and model APIs where appropriate.

Use closed, open, and half-open states. Avoid sending repeated requests to a failing dependency. Provide fallback behavior and record the reason for degraded operation.

### Rate limiting

Apply rate limits at the API gateway and per-provider adapter.

Support limits by user, tenant, endpoint, and provider as appropriate.

Account for provider quotas, concurrent requests, model token limits, and daily cost budgets.

### Checkpointing

Persist research-job state and completed sections. Resume incomplete work safely when possible.

A restarted worker must not create duplicate reports, duplicate citations, or duplicate alerts.

### Failure handling

Handle:

- Provider outages.
- Invalid source responses.
- Empty retrieval results.
- Model timeouts.
- Invalid model output.
- Database failures.
- SSE disconnections.
- Browser navigation away from an active report.
- Duplicate requests.
- Scheduler restarts.
- Partial source outages.

The product must degrade honestly rather than fabricating results.

---

## 17. Latency, Tokens and Cost Optimization

Measure and optimize the full request path.

### Latency

- Record latency for authentication, retrieval, document extraction, drafting, validation, persistence, and report delivery.
- Measure p50, p95, and p99 latency.
- Parallelize independent research sections.
- Limit concurrency to safe provider and infrastructure capacity.
- Stream progress through SSE.
- Cache deterministic or reusable results when freshness rules permit.
- Avoid redundant retrieval and unnecessary model calls.

### Token efficiency

- Send only relevant evidence to each agent.
- Remove redundant conversation history.
- Summarize long documents with retained provenance.
- Limit prompt and output sizes.
- Avoid sending complete prospectuses repeatedly when targeted passages suffice.
- Use structured outputs with explicit schemas.

### Cost

- Use deterministic code for calculations, validation, filtering, and formatting.
- Reserve stronger models for complex reasoning that needs them.
- Use smaller models for suitable classification and extraction tasks.
- Batch offline embedding jobs where supported.
- Cache reusable embeddings and deterministic retrieval results.
- Record model usage and estimated cost per request and successful report.
- Add configurable token, request, and daily cost limits.
- Support graceful degradation when a budget is exhausted.

Do not trade away evidence quality or tenant security to reduce latency or cost.

Every optimization must be evaluated against a regression evaluation set.

---

## 18. Observability and Customer Health

Implement correlated traces across:

- Public API requests.
- AI orchestration.
- Retrieval and external provider calls.
- Model invocations.
- Validation and repair loops.
- Database operations.
- Background jobs.
- Persistence and report delivery.

Use OpenTelemetry-compatible instrumentation and a request/trace ID propagated across service boundaries.

Monitor:

### Reliability

- Request volume.
- Error rates.
- Timeout rates.
- Retry counts.
- Provider failures.
- Circuit-breaker transitions.
- Queue depth.
- Job completion rates.

### Performance

- p50/p95/p99 latency per stage.
- Model-call latency.
- Retrieval latency.
- Database latency.
- Concurrency and queue delays.

### Cost

- Input and output tokens.
- Model usage.
- Cost per request.
- Cost per successful research report.
- Cost by tenant and workflow.

### Quality

- Retrieval relevance and coverage.
- Citation validity.
- Unsupported-claim rate.
- Repair-loop termination.
- Section degradation rate.
- User feedback.
- Sampled human evaluations.
- Regression-test results.

### Security

- Authentication failures.
- Authorization denials.
- Suspicious tool calls.
- Prompt-injection signals.
- Cross-tenant access attempts.
- Unexpected data-access patterns.
- Secret exposure detections.

Avoid logging API keys, raw credentials, or unnecessary personal and financial data.

---

## 19. Security and Enterprise Identity

Apply the following controls from the beginning:

- Secure authentication and session handling.
- Role-based access control.
- Tenant-aware authorization.
- Least-privilege service credentials.
- Row-level security where appropriate.
- Strict tenant isolation in queries, caches, jobs, retrieval, and evidence access.
- Input validation and output encoding.
- Protection against SQL injection, SSRF, CSRF where applicable, and unsafe file handling.
- Secret management.
- Encryption in transit and at rest.
- Audit logging.
- Dependency and container scanning.
- Secure defaults and explicit permission checks.

A user must never be able to retrieve another user's reports, holdings, wishlist, evidence, or settings by changing an identifier.

Enterprise identity must be designed to support:

- OAuth 2.0.
- OpenID Connect.
- SAML SSO.
- SCIM provisioning.
- Role mapping.
- Tenant-specific identity configuration.

Do not implement a simulated enterprise identity bridge as if it were production SSO. Clearly distinguish local development mocks from real identity-provider integration.

---

## 20. Apply All 12 Forward Deployed Engineer Stages

Design the project roadmap around these stages.

### Stage 1 — Enterprise Identity and Access

Learn and implement authentication, OAuth 2.0, OIDC, SAML, SCIM, RBAC, and tenant isolation.

Practice: Build a simulated identity-provider integration and prove through tests that User A cannot access User B's reports or stock records.

### Stage 2 — Air-Gapped and VPC Deployments

Learn Kubernetes, Helm, Terraform, private container registries, egress filtering, and offline deployment constraints.

Practice: Produce reproducible infrastructure definitions for deploying the platform into an isolated environment. Test that the deployment operates without unintended public egress.

External market data and Gemini API access will not work without a permitted connection. For air-gapped operation, design explicit data-import and local-inference alternatives rather than claiming that an internet-dependent service works offline.

### Stage 3 — Legacy Data Extraction and ETL

Learn OCR, PDF extraction, structured and unstructured data pipelines, reconciliation, and data quality checks.

Practice: Ingest official prospectuses, including scanned PDFs, extract financial tables and risk sections, preserve page-level provenance, and validate extracted data against source documents.

### Stage 4 — Secure RAG and Permission-Filtered Retrieval

Learn hybrid retrieval, metadata filtering, access-controlled chunks, citation grounding, and abstention.

Practice: Build a retrieval system that applies authorization filters before returning evidence to the model. Prove through tests that unauthorized documents never enter the model context.

### Stage 5 — MCP and Legacy Integration

Learn MCP, tool schemas, safe API integration, rate-limit handling, and credential isolation.

Practice: Build a read-only MCP server for permitted research or market-data operations. Require explicit authorization and human approval for any future consequential write operation. Never expose raw credentials to the model.

### Stage 6 — AI Guardrails and PII Redaction

Learn deterministic filtering, sensitive-data detection, validation middleware, and audit logging.

Practice: Build a middleware layer that detects and masks test PII in relevant inputs and outputs. Use reversible tokens only when necessary, with protected mappings and tightly controlled restoration. Do not send sensitive data to external models unnecessarily.

### Stage 7 — Human-in-the-Loop Workflows

Learn durable workflows, state machines, webhooks, approval gates, and retry-safe execution.

Practice: Create an approval workflow for consequential administrative actions. Research reports and financial calculations should remain read-only; the application must not submit IPO bids or trade securities automatically.

### Stage 8 — Edge and On-Premises Inference

Learn vLLM, Ollama, quantized models, GPU constraints, and local inference.

Practice: Run a local model for an appropriate extraction or classification task and compare its latency, quality, resource usage, and privacy properties against the Gemini implementation.

### Stage 9 — Observability and Customer Health

Learn OpenTelemetry, dashboards, cost attribution, and operational health metrics.

Practice: Build dashboards showing service health, successful research jobs, citation-validation results, token usage, costs, and latency. Where the application has no enterprise customer teams, use per-user or per-tenant usage metrics without inventing customer ROI.

### Stage 10 — Evals on Customer Data

Learn golden datasets, trajectory grading, shadow testing, and evaluator calibration.

Practice: Create a legally permitted, appropriately anonymized set of representative IPO documents and questions. Test factual correctness, citation entailment, numeric grounding, retrieval coverage, and failure handling.

Use synthetic fixtures for initial development. Never claim a benchmark result without running the evaluation and recording the result.

### Stage 11 — Technical Discovery and Scoping

Learn stakeholder interviews, requirements, architecture diagrams, measurable acceptance criteria, and statements of work.

Practice: Convert a hypothetical stakeholder request into a scoped implementation plan with deliverables, risks, dependencies, success metrics, and a phased timeline.

### Stage 12 — Handoff and Self-Service Administration

Learn runbooks, admin portals, onboarding, configuration management, and chaos testing.

Practice: Build a secure administrative interface for managing source providers, quotas, scheduled jobs, retention settings, prompts, and operational logs. Use versioning, audit trails, and controlled rollbacks for production changes.

---

## 21. Testing and Evaluation Strategy

Use a testing pyramid.

### Unit tests

Test:

- Lot and bid calculations.
- IPO eligibility and quantity rules.
- Financial formulas.
- Number normalization.
- Evidence ID validation.
- Citation integrity.
- Literal grounding.
- Source freshness.
- Retry termination.
- Circuit-breaker transitions.
- Idempotency behavior.
- Tenant authorization.
- Exclusion rules.

### Integration tests

Test:

- Node.js to Python API communication.
- PostgreSQL persistence.
- Evidence-ledger writes and reads.
- Search-provider adapters.
- Gemini response validation.
- SSE streaming.
- Scheduled jobs.
- Database transactions.
- Authentication and access control.

### End-to-end tests

Test:

1. Select an eligible IPO.
2. Verify official details.
3. Start research.
4. Observe streaming progress.
5. Inspect report sections and citations.
6. Open cited evidence.
7. Calculate valid application scenarios.
8. Reload the report and confirm persistence.
9. Simulate a provider failure and verify graceful degradation.
10. Attempt unauthorized access and verify denial.

### AI evaluation suite

Build a versioned golden dataset containing known facts, authoritative evidence, unsupported claims, contradictory sources, numeric edge cases, prompt-injection attempts, and missing-information cases.

Measure:

- Retrieval recall and relevance.
- Claim support.
- Citation correctness.
- Numeric accuracy.
- Unsupported-claim rate.
- Abstention quality.
- Section completeness.
- Latency and token cost.

Require regression tests for every meaningful prompt, model, retrieval, or validation change.

---

## 22. Deployment and CI/CD

### Local development

Provide:

- A documented repository structure.
- `.env.example` containing placeholders only.
- Docker Compose configuration.
- Database migrations.
- Seed data for tests.
- Mock data providers.
- A health-check endpoint for each service.
- A single documented startup sequence.
- Linting, type checks, formatting, and test commands.

### Continuous integration

Run:

- TypeScript type checking.
- Python type and lint checks.
- Unit tests.
- Integration tests where infrastructure is available.
- Dependency and container scanning.
- Secret scanning.
- AI regression evaluations.
- Migration validation.

### Production deployment

Create a production deployment plan with:

- Environment-specific configuration.
- Secret management.
- Database migration strategy.
- Horizontal scaling where required.
- Health and readiness checks.
- Structured logs and distributed traces.
- Backups and restore tests.
- Disaster recovery procedures.
- Rollback and release strategies.
- Cost and quota monitoring.

Do not claim production readiness merely because the application runs locally. Define the operational acceptance criteria and verify them.

---

## 23. Implementation Roadmap

Work through the following milestones in order.

### Milestone 0 — Requirements and architecture

Deliver:

- Requirements document.
- System architecture diagram.
- Data-flow diagram.
- Threat model.
- Source-provider plan.
- Repository structure.
- Technology decision records.
- Acceptance criteria.

### Milestone 1 — Project foundation

Create the frontend, TypeScript backend, Python AI service, local environment, PostgreSQL schema, migrations, and health checks.

Verify that all services start and communicate successfully.

### Milestone 2 — IPO data ingestion

Implement the SearchPort abstraction, official-source adapters, IPO entity model, data normalization, source provenance, and exclusion enforcement.

Verify the source of each critical IPO field.

### Milestone 3 — Evidence ledger

Implement immutable evidence records, source metadata, retrieval timestamps, and stable document identifiers.

Test deduplication, provenance, and authorization.

### Milestone 4 — Research orchestration

Integrate Google ADK and Gemini. Implement the retrieval planner, structured agent contracts, parallel section execution, and SSE progress events.

Use mock providers for deterministic development tests.

### Milestone 5 — Validation and repair

Implement citation integrity, literal grounding, semantic entailment, quarantine, bounded repairs, deadlines, and honest degradation.

Verify that unsupported facts are not published as verified claims.

### Milestone 6 — IPO research UI

Build discovery, selection, report sections, source panels, progress indicators, and report history.

Verify loading, partial, failed, and completed states.

### Milestone 7 — Budget and bid calculator

Implement deterministic financial calculations, category-specific rules, lot scenarios, validation, and tests.

Verify edge cases, invalid quantities, and budget boundaries.

### Milestone 8 — Security and reliability

Implement authentication, authorization, rate limiting, idempotency, circuit breakers, timeout handling, tenant isolation, and audit events.

Prove access controls with adversarial tests.

### Milestone 9 — Stock intelligence

Add the watchlist, holdings, wishlist, news ingestion, deduplication, price history, daily dashboard digest, and configurable alerts.

### Milestone 10 — Observability and evaluation

Add correlated traces, dashboards, usage accounting, golden datasets, regression evaluations, and failure-injection tests.

### Milestone 11 — Production deployment

Implement CI/CD, infrastructure definitions, production configuration, backups, recovery procedures, and deployment documentation.

### Milestone 12 — Enterprise FDE extensions

Implement the remaining enterprise capabilities: SSO and provisioning integrations, air-gapped deployment, advanced ETL, MCP integrations, PII controls, HITL workflows, local inference, customer-health reporting, and self-service administration.

At each milestone, report what is completed, what remains, the tests run, the results observed, and the next step.

---

## 24. Required Repository Structure

Use a maintainable monorepo or clearly documented multi-repository arrangement.

A possible monorepo layout:

```text
ipo-intelligence/
├── apps/
│   └── web/                   # React + TypeScript UI
├── services/
│   ├── api/                   # Node.js application API
│   └── ai/                    # Python + FastAPI + Google ADK
├── packages/
│   ├── contracts/             # Shared API schemas and types
│   └── ui/                    # Shared UI components if needed
├── database/
│   ├── migrations/
│   └── seeds/
├── infrastructure/
│   ├── docker/
│   ├── terraform/
│   └── helm/
├── tests/
│   ├── integration/
│   ├── e2e/
│   └── evaluation/
├── docs/
│   ├── architecture/
│   ├── security/
│   ├── runbooks/
│   └── decisions/
├── docker-compose.yml
├── .env.example
└── README.md
```

Adapt the layout when justified, but preserve clear boundaries between the frontend, application API, AI orchestration, persistence, infrastructure, and tests.

---

## 25. Documentation Deliverables

Maintain:

- Product requirements document.
- System architecture and component diagrams.
- Data-flow and sequence diagrams.
- Database schema and migration guide.
- API reference.
- Evidence-ledger schema.
- AI agent contracts.
- Source reliability and freshness policy.
- Security and threat model.
- Local development guide.
- Testing and evaluation guide.
- Deployment guide.
- Incident response and troubleshooting runbooks.
- Cost and quota management guide.
- FDE stage completion tracker.
- Known limitations and future work.

Explain technical concepts when they are introduced. Include relevant examples, expected outputs, failure cases, and verification commands.

---

## 26. Working Agreement for the AI Coding Assistant

Follow these instructions throughout implementation.

1. Begin with Milestone 0 and establish the architecture and acceptance criteria.
2. Do not skip ahead to later milestones without completing the required foundations.
3. Explain the purpose of every significant file and component.
4. Provide complete, executable code for the current task, not disconnected snippets that cannot be integrated.
5. Do not invent successful test results, completed integrations, live source availability, or production deployment status.
6. Prefer deterministic business logic over LLM calls whenever a formula or explicit rule is sufficient.
7. Keep prompts, model settings, provider configuration, and schemas versioned.
8. Keep external dependencies behind interfaces.
9. Use mock providers for deterministic tests and live providers for explicitly configured integration tests.
10. Never commit secrets or ask me to paste API keys into source code.
11. After each implementation step, provide commands to run, expected results, troubleshooting guidance, and a verification checklist.
12. When a test fails, explain the cause and fix the current issue before proceeding.
13. Ask questions only when a missing decision materially blocks progress. Otherwise, choose a sensible default, document it, and continue.
14. Maintain a persistent project checklist and update the project documentation as the implementation evolves.
15. Never bypass a security or evidence check merely to make a demo look successful.
16. Never use fabricated financial data in a report presented as real. Mark sample fixtures clearly as synthetic.
17. Distinguish implemented features, tested features, planned features, and unverified assumptions.
18. Do not create an automatic IPO application-submission or securities-trading mechanism.

## 27. Definition of Done

The project is ready for an initial production release only when:

- Eligible IPOs can be discovered and selected using supported sources.
- The Jio IPO exclusion is enforced and tested throughout the system.
- Critical IPO facts have verifiable provenance and freshness indicators.
- Research sections have validated claims and citations.
- Unsupported claims are quarantined or omitted.
- Repair loops terminate within configured limits.
- Financial calculations pass deterministic tests.
- User authentication and authorization work correctly.
- Cross-user and cross-tenant access is denied.
- External provider failures result in bounded retries and honest degradation.
- Logs, traces, latency, token usage, and costs can be inspected.
- Regression evaluations are reproducible.
- Daily stock monitoring is idempotent and records failed runs.
- Deployment, backup, recovery, and rollback procedures are documented and tested.
- Known limitations are clearly documented.

Do not declare the project complete until the acceptance criteria have been checked against actual implementation and test results.

---

# Start Here

Begin with **Milestone 0: Requirements and Architecture**.

First, explain the complete request lifecycle:

Company or IPO selection → Retrieval planner → SearchPort → Evidence ledger → Parallel research sections → Claim validation → Bounded repair → Report composition → SSE streaming → Persistent report.

Then explain how the stock-monitoring workflow will extend this architecture in Phase 2.

Produce the initial architecture diagram, service responsibilities, data-flow diagram, threat model, source-provider strategy, and acceptance criteria. Explain the reasoning behind the hybrid Python and TypeScript design and the use of Google ADK.

After that, provide the initial repository setup and development commands. Wait for verification before moving to the next implementation milestone.

**The ultimate objective is a trustworthy, secure, observable, cost-conscious IPO and stock research platform that also serves as a hands-on learning project for building production-grade AI systems as a Forward Deployed Engineer.**