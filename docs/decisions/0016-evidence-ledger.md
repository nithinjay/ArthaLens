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

- **De-duplication:** same `source_key` (canonical URL) + same bytes → same document; only a retrieval is logged. Identical bytes from two sources share one content and one set of passages.
- **Versions:** same source, new bytes → `version + 1` with `supersedes_id`. Reverting to old bytes reuses the old version.
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
- Plain text and HTML in-process. **PDFs in a sandboxed subprocess**: `python -I`, minimal environment (no secrets), CPU, memory, file-size and open-file limits, a wall-clock kill and an output cap.
- Pages keep their numbers. Pages with almost no text layer are OCR'd (Tesseract 5.3, 200 dpi) and store a mean word confidence.

### Raw bytes (source snapshots)
Kept write-once by hash in a `LocalBlobStore` on the `evidence` Docker volume, re-verified on every read and never served by the API. Object storage replaces it in Milestone 11.

## Consequences
- Evidence can't be corrected in place. A wrong document stays and is superseded or purged by retention, which keeps old reports reproducible.
- The content-hash function reveals whether given bytes were seen before (`false` on re-insert). Only the service calls it, never tenants directly. Recorded as threat T-24.
- OCR quality varies. Confidence is stored per passage so later milestones can degrade claims built on weak OCR.
