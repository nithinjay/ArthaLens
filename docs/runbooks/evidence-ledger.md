# Evidence Ledger

> Milestone 3 · Design: [ADR-0016](../decisions/0016-evidence-ledger.md)

## Tests

```sh
# Everything (unit + OCR + database integration) in a Linux container, against a throwaway
# database that is created, migrated and dropped. Your local data is not touched.
sh scripts/test-integration.sh
sh scripts/test-integration.sh -m integration     # only the database tests
sh scripts/test-integration.sh -m ocr             # only OCR

# Migration 4 against Milestone 2-shaped data (versions, canonical keys, lossless split, safe rollback)
sh scripts/check-evidence-backfill.sh

# On macOS without tesseract/Postgres URLs, OCR and integration tests are skipped:
cd ai && uv run pytest
```

## Inspecting evidence

```sh
docker compose exec postgres psql -U postgres -d arthalens
```
```sql
-- Documents with their versions and how often they were retrieved
SELECT d.version, d.title, d.source_key, count(r.*) AS retrievals
  FROM evidence_documents d JOIN evidence_retrievals r ON r.document_id = d.id
 GROUP BY d.id ORDER BY d.source_key, d.version;

-- Page-anchored passages of one document
SELECT p.page_number, p.passage_index, p.extraction, p.ocr_confidence, left(p.text, 80)
  FROM evidence_documents d JOIN evidence_passages p ON p.content_sha256 = d.content_sha256
 WHERE d.canonical_url LIKE '%beta-rhp.pdf' ORDER BY 1, 2;

-- Labels of the current snapshot of each IPO
SELECT i.company_name, it.label, d.title
  FROM ipos i JOIN ipo_snapshots s ON s.id = i.current_snapshot_id
  JOIN evidence_set_items it ON it.set_id = s.evidence_set_id
  JOIN evidence_documents d ON d.id = it.document_id ORDER BY 1, it.position;
```

Raw bytes: `docker compose exec ai ls -R /data/evidence` (files named by SHA-256, read-only).

## Expected errors (these are protections, not bugs)

| Error | Meaning |
|---|---|
| `EVIDENCE_IMMUTABLE: UPDATE on evidence_documents is not allowed` | Evidence is append-only, even for the table owner |
| `EVIDENCE_NOT_VISIBLE: document … belongs to another tenant` | A set tried to cite another tenant's private evidence |
| `new row violates row-level security policy` | A write tried to use another tenant's identity |
| `PDF could not be parsed (timeout / worker_failed / output_too_large)` | The sandbox stopped a malformed or hostile PDF |

## Retention purge (not automated yet)

The only way to delete evidence. It must run in one transaction:
```sql
BEGIN;
SET LOCAL arthalens.evidence_retention = 'on';
DELETE FROM evidence_retrievals WHERE document_id = '…';
DELETE FROM evidence_documents WHERE id = '…';
COMMIT;
```
Snapshots that cite the document block the delete (foreign keys). A retention job with its own role and rules arrives with the retention policy work.

## Scanned PDFs

Pages with fewer than 20 characters of text layer are rendered at 200 dpi and OCR'd with Tesseract. Each passage stores `extraction = 'ocr'` and the mean word confidence (0–100). If Tesseract is missing, the page keeps its empty text, a warning is logged, and any quote on it stays "Not verified".
