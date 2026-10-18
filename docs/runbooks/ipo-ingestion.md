# IPO Ingestion

> Milestone 2 · How IPO data gets into ArthaLens, what "verified" means, and how to import real data by hand.

## Commands

```sh
# Synthetic fixtures (8 imports: 6 IPOs + 2 entities that must be quarantined)
docker compose exec ai python -m arthalens_ai.ingestion.cli discover

# One manual import (file and its documents must be inside the container; see below)
docker compose exec ai python -m arthalens_ai.ingestion.cli import /path/in/container/import.json
```

Each run prints a JSON summary such as `{"status": "succeeded", "discovered": 8, "quarantined": 2, "created": 6, "unchanged": 0, "failed": 0, "withdrawn": 0}`. The exit code is non-zero unless the status is `succeeded`. Re-running with unchanged sources creates no new snapshots.

## Pipeline

```
provider.candidates()  ->  exclusion check (L5)  ->  blocked: quarantine (name + URL only), stop
                                                  ->  allowed: load documents (file or guarded fetch)
  -> extract text -> parse each raw value -> verify quote -> resolve per field -> derive status
  -> new snapshot only if the content fingerprint changed -> reconcile stored IPOs with policy (L6)
```

## Field states

| State | Meaning | Shown as (M6) |
|---|---|---|
| `verified` | Quote found verbatim in the stored document, value in the quote, value parsed. Top authority, latest document. | Verified + source + quote |
| `unverified` | A source claims a value, but its quote isn't in the document | "Not verified" |
| `conflict` | Equal-authority, same-date sources disagree. **No value is shown** | "Not verified: sources disagree" |
| `unavailable` | No source, or nothing parseable | "Unavailable" |

Resolution order: grounded observations only → highest authority (exchange > regulator = issuer filing > registrar > licensed data > news > unofficial) → latest publication date (addenda supersede) → disagreement at the top is a conflict, lower-ranked disagreement is noted. Every observation is kept and returned by `GET /api/v1/ipos/{id}`.

IPO status (`upcoming`, `open`, `closed`, `allotment`, `listed`, `withdrawn`, `postponed`, `unverified`) is derived from **verified** fields for one IST date (`status_as_of`). Without verified bid dates, the status is `unverified`, whatever any label says.

## Manual import (the route for NSE/BSE data)

NSE's terms forbid automated collection (ADR-0015), so exchange notices come in by hand:

1. Download the notice (and the RHP, if needed) in your browser.
2. Write an `arthalens.ipo-import.v1` JSON file next to the files. Copy the structure of `ai/fixtures/ipos/alpha-open.json`, but set `"synthetic": false` and give each document its real `url`, `title`, `publisher`, `published_at` and `authority`.
3. For every field, copy the value and a **verbatim quote** from the document. If the quote isn't in the document text, the field stays "Not verified".
4. Copy the folder into the container and import it:
   ```sh
   docker compose cp ./my-import ai:/tmp/my-import
   docker compose exec ai python -m arthalens_ai.ingestion.cli import /tmp/my-import/import.json
   ```

Rules the importer enforces:
- Raw field names: `open_date`, `close_date`, `listing_date`, `listing_date_basis` (must say confirmed or tentative/estimated), `price_band`, `lot_size`, `issue_size`, `fresh_issue_size`, `ofs_size`, `exchanges`, `issue_type`, `official_status`.
- Document `file` paths can't leave the import's folder. Types: `text/plain`, `text/html`, `application/pdf` (text-based; scanned PDFs need OCR, M3/M4).
- Unknown keys anywhere are rejected. You can't mark something verified yourself.

## Live SEBI fetch (off by default)

Set `PROVIDER_SEBI_FETCH_ENABLED=true` in `.env`, run `docker compose up -d ai`, and in the import use `"fetch": true` (instead of `"file"`) for a `https://www.sebi.gov.in/...` document. Only `sebi.gov.in` is allow-listed. **This has only been tested against a mock network** (`ai/tests/test_fetch.py`).

## Exclusion

Entities matching `packages/policy/exclusions.v1.json` are recorded in `quarantined_entities` (name, rule, decision, source URL, seen count) and **nothing else**: their documents are never loaded. See ADR-0008 for all seven layers. To inspect:

```sh
docker compose exec postgres psql -U postgres -d arthalens -c \
  "SELECT raw_name, decision, reason, seen_count FROM quarantined_entities"
```
