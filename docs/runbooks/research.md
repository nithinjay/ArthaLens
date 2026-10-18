# Research Reports

> Milestone 4 · Design: [ADR-0017](../decisions/0017-research-orchestration.md) · Agents: [agent-contracts.md](../architecture/agent-contracts.md)

## Run a report (local stack, fake model)

```sh
docker compose up --build -d
sh scripts/seed-dev.sh                                   # dev tenant + user (AUTH_MODE=dev)
docker compose exec ai python -m arthalens_ai.ingestion.cli discover

API=http://localhost:3000/api/v1
IPO=$(curl -s "$API/ipos?q=alpha" | python3 -c "import json,sys;print(json.load(sys.stdin)['items'][0]['id'])")
curl -s -X POST -H 'Idempotency-Key: my-first-report-1' "$API/ipos/$IPO/research"
#  -> 202 {"report_id": "...", "events_url": "/api/v1/research/.../events", ...}

curl -N "$API/research/<report_id>/events"                # live progress (SSE)
curl -N -H 'Last-Event-ID: 5' "$API/research/<report_id>/events"   # resume after event 5
curl -s "$API/research/<report_id>" | python3 -m json.tool          # the report
curl -s "$API/research/<report_id>/evidence"                        # labelled sources
curl -s "$API/research"                                             # history
curl -X DELETE "$API/research/<report_id>"                          # hide (soft delete)
```

Expected with the fake model: `completed_degraded`; D **Verified**; A, E, F, J **Partial** (claims `unverified`); B, C, G, H, I **Not found** with reasons.

## Use Gemini (opt-in)

1. Put your key in `.env` yourself (never in chat or code): `GEMINI_API_KEY=...`
2. `docker compose up -d ai-worker` then list the models your key can use:
   `docker compose exec ai-worker python -m arthalens_ai.research.models`
3. In `.env`: `MODEL_PROVIDER=gemini`, `GEMINI_MODEL=<an id from step 2>`. Optionally add prices for cost estimates: `GEMINI_INPUT_USD_PER_MTOK=…`, `GEMINI_OUTPUT_USD_PER_MTOK=…`
4. `docker compose up -d ai-worker` and create a report as above. `docker compose logs -f ai-worker` shows progress.
5. Live check (one billed call, synthetic text incl. a prompt-injection line):
   ```sh
   set -a; . ./.env; set +a     # load the key into this shell only
   docker compose --profile test run --rm -e GEMINI_API_KEY -e GEMINI_MODEL ai-test /venv/bin/pytest -m live_gemini -s
   ```

## Tests

| What | Command |
|---|---|
| Unit (planner, T1, section D, agents, budget, deadlines, checkpoints) | `cd ai && uv run pytest tests/test_research_unit.py` |
| Worker against Postgres (full run, determinism, crash/resume, leases, exclusion, RLS) | `sh scripts/test-integration.sh -m integration` |
| API + SSE | `cd backend && pnpm test` |
| End to end through nginx | `pnpm smoke` (70 checks) |

## Inspecting a run

```sql
SELECT seq, type, payload FROM research_events WHERE report_id = '…' ORDER BY seq;
SELECT section, status, validation, reason, attempt, model FROM research_sections WHERE report_id = '…';
SELECT status, attempt, lease_owner, lease_expires_at, last_error FROM research_jobs WHERE report_id = '…';
SELECT section, model, input_tokens, output_tokens, estimated_cost_usd, outcome FROM usage_records WHERE report_id = '…';
```
(As `postgres` or `app_migrate`. The runtime roles only see rows of the tenant they are scoped to.)

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| POST returns 401 | `AUTH_MODE` isn't `dev`, or the backend runs with `NODE_ENV=production` |
| Report stays `pending` | `ai-worker` isn't running: `docker compose ps ai-worker`, `docker compose logs ai-worker` |
| Worker exits with `MODEL_PROVIDER=gemini needs GEMINI_API_KEY and GEMINI_MODEL` | Set both in `.env` |
| A section says "The model call failed (timeout)" | Raise `RESEARCH_SECTION_DEADLINE_SECONDS`, or check provider status |
| Every model section says "Skipped: token budget" | Raise `RESEARCH_TOKEN_BUDGET` |
| SSE stalls behind a proxy | The proxy is buffering; nginx here sets `proxy_buffering off` for `/api/` |
