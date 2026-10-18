# ADR-0016: Evidence ledger design

**Status:** Accepted · **Date:** 2026-10-18 · **Implements:** brief section 9, threat model T-12, T-21, T-31

## Context
Every factual claim must cite evidence that can't be fabricated or silently changed. Evidence comes from public sources (shared by all tenants) and, later, from tenant uploads (private). Prospectuses run to hundreds of pages and may be scans.

## Decision

### Data model (migration `20261018000002`)

| Table | Holds | Identity |
|---|---|---|
| `evidence_contents` | Bytes metadata: type, size, page count, extraction method, storage key | SHA-256 of the bytes |
| `evidence_passages` | Text, ≤ 4,000 chars, anchored to page + index, with OCR confidence | (content, page, index) |
| `evidence_documents` | Source record: URL, title, publisher, dates, authority, display rights, visibility | `source_key` + `version` |
| `evidence_retrievals` | Every retrieval, including unchanged re-fetches, with non-sensitive request metadata | append-only log |
| `evidence_sets` / `_items` | Stable per-report labels `d1`, `d2`, … | (set, position) |

- **De-duplication:** fetching a source again with the same bytes as its *latest* version returns that document; only a retrieval is logged. Identical bytes from two sources share one content and one set of passages.
- **Versions are a timeline:** new bytes → `version + 1` with `supersedes_id`, even when they match an older version (A → B → A is v1, v2, v3). The newest version is always the current content. *(Changed after PR #3 review: originally a revert reused v1, which left an outdated v2 looking current.)*
- **Key namespaces:** public documents use the canonical URL. Tenant documents use `tenant:<id>:<url>` or `upload:<id>:<sha>`, enforced by a CHECK, so a tenant's copy of a URL never collides with, or reveals itself through, the public version chain.
- **Canonical keys** are defined twice, in Python (`canonical.py`) and SQL (`canonical_source_key`, used by the backfill), with shared test vectors proving they agree.
- **Labels:** assigned under a row lock on the set, so they are gap-free and idempotent, and never move to another document.

### Immutability
Triggers refuse UPDATE, DELETE and TRUNCATE on all evidence tables **for every role, including the table owner**. Two narrow exceptions:
1. A DELETE in a transaction that sets `arthalens.evidence_retention = 'on'` (the future retention job).
2. `evidence_contents.storage_key` may go from NULL to a value once, with every other column unchanged (attaching retained bytes).

`app_ai` has only SELECT/INSERT. `evidence_sets` may only advance its counter by one.

### Writes through one function
`evidence_put_content()` (SECURITY DEFINER, owner = `app_migrate`) is the only way to write contents and passages. A plain insert can't work under RLS: `INSERT … ON CONFLICT` applies the SELECT policy to the new row, and a pre-check would be RLS-filtered. The function does one idempotent insert and is executable only by `app_ai`.

### Authorization (row-level security)
- Documents: `visibility = 'public' OR tenant_id = current_tenant_id()` for SELECT and INSERT.
- Contents, passages and retrievals are visible only through a visible document. Sets are visible only to their tenant (or to everyone if public).
- A trigger stops a set from citing another tenant's document, even when RLS is bypassed: foreign-key checks ignore RLS.
- `EvidenceReader` always sets the tenant context, even to empty, so a stale value can't leak between reads.
- `app_api` can read citation columns of documents but not passages or contents.

### Read/write separation in code
`EvidenceLedger` and `EvidenceSets` (write) are constructed only by ingestion. Research agents (M4) get `EvidenceReader`, which has no write methods. Agents can't create source ids or rewrite source content.

### Extraction
- Plain text and HTML in-process. **PDFs in a sandboxed subprocess**: `python -I`, minimal environment (no secrets), CPU, memory, file-size and open-file limits, a wall-clock kill, and an output cap enforced *while reading* (the worker is killed the moment it is exceeded, and only the last 64 KB of stderr is kept).
- Pages keep their numbers. Pages with almost no text layer are OCR'd (Tesseract 5.3, 200 dpi) and store a mean word confidence.

### Raw bytes (source snapshots)
Kept write-once by hash in a `LocalBlobStore` on the `evidence` Docker volume, re-verified on every read and never served by the API. Object storage replaces it in Milestone 11.

### Backfill and rollback
- Milestone 2 documents become versions in retrieval order, keyed canonically, with their text split into ≤ 4,000-character passages and nothing dropped.
- Rolling back **refuses** when the data can't be represented in the Milestone 2 shape (tenant-private evidence would become public; repeated content per URL), instead of deleting rows. `scripts/check-evidence-backfill.sh` tests both.

## Consequences
- Evidence can't be corrected in place. A wrong document stays and is superseded or purged by retention, which keeps old reports reproducible.
- The content-hash function reveals whether given bytes were seen before (`false` on re-insert). Only the service calls it, never tenants directly. Recorded as threat T-24.
- OCR quality varies. Confidence is stored per passage so later milestones can degrade claims built on weak OCR.
