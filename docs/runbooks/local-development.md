# Local Development

> Milestone 1 · Verified on macOS (Apple silicon), Docker Desktop 28.1.1, Node 22.23.2, uv 0.12.3.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Node.js | 22.x (`.nvmrc`) | `nvm use` in the repo root. Node 20 is end-of-life and too old for Vitest 5. |
| pnpm | 12.14.0 (via Corepack) | `corepack enable pnpm` once; the version comes from `package.json`. |
| uv | 0.12+ | Manages Python 3.13 and the `ai/` virtualenv. |
| Docker Desktop | with Compose v2 | No file-sharing setup needed: nothing is bind-mounted. |

## First run

```sh
nvm use                      # Node 22
corepack enable pnpm
pnpm install                 # frontend, backend, packages/*
uv sync --project ai         # Python deps for ai/
pnpm env:init                # creates .env with random local secrets (gitignored, chmod 600)
docker compose up --build -d
pnpm smoke                   # 54 checks: services, DB roles, RLS, ingestion, exclusion, IPO API, evidence
```

Then open http://localhost:8080. You should see **System status: All systems operational**.
`pnpm smoke` also ingests the synthetic IPO fixtures; see [ipo-ingestion.md](ipo-ingestion.md).

| Service | URL (127.0.0.1 only) | What it is |
|---|---|---|
| frontend | http://localhost:8080 | nginx serving the React build; proxies `/api/*` to backend |
| backend | http://localhost:3000 | Fastify API. `/healthz`, `/readyz`, `/api/v1/health`, `/api/v1/openapi.json` |
| ai | http://localhost:8000 | FastAPI. `/healthz`, `/readyz`, `/docs`; `/internal/v1/*` needs the service token |
| postgres | localhost:5433 | 5433 avoids a local Postgres on 5432. Change `POSTGRES_HOST_PORT` in `.env` if needed |

Startup order is enforced by health checks: postgres (healthy) → migrate (exits 0) → ai (healthy) → backend (healthy) → frontend.

## Day-to-day commands

| Purpose | Command |
|---|---|
| Hot-reload backend (stack's postgres + ai still in Docker) | `docker compose stop backend frontend`, then `pnpm dev:backend` with env vars from `.env` (see below) |
| Hot-reload frontend | `pnpm dev:frontend` → http://localhost:5173 (proxies `/api` to :3000) |
| All TS checks | `pnpm typecheck && pnpm lint && pnpm test` |
| All Python checks | `cd ai && uv run ruff check . && uv run ruff format --check . && uv run mypy arthalens_ai tests && uv run pytest` (OCR + DB tests skip on macOS) |
| Full Python suite incl. OCR + DB integration (Linux container, throwaway DB) | `sh scripts/test-integration.sh` |
| Regenerate contracts after changing a Pydantic model | `pnpm contracts:gen` (then `pnpm build`) |
| Contract drift check (CI) | `pnpm contracts:check` |
| New migration | add `database/migrations/<yyyymmddhhmmss>_<name>.sql` with `-- migrate:up` / `-- migrate:down`, then `docker compose up --build migrate` |
| Prove migrations reverse cleanly | `sh scripts/check-migrations.sh` (uses a throwaway DB) |
| Secret scan | `pnpm secrets:scan` (scans exactly the files git would commit) |
| Ingest synthetic IPOs | `docker compose exec ai python -m arthalens_ai.ingestion.cli discover` |
| List IPOs | `curl 'localhost:3000/api/v1/ipos?status=open'` |
| psql as the API role | `docker compose exec postgres psql -h 127.0.0.1 -U app_api -d arthalens` (password in `.env`) |
| Stop | `docker compose down` · wipe data too: `docker compose down -v` |

Running the backend outside Docker needs these variables (values from `.env`):
`DATABASE_URL=postgresql://app_api:<APP_API_DB_PASSWORD>@127.0.0.1:5433/arthalens`,
`AI_SERVICE_URL=http://127.0.0.1:8000`, `AI_SERVICE_TOKEN=<AI_SERVICE_TOKEN>`.
Put them in a gitignored `.env.local` at the repo root; `pnpm dev:backend` loads it.

## Expected results

- `pnpm smoke` → `Smoke test: 54 passed, 0 failed`
- `GET /readyz` on backend → `{"status":"ok", ...}`. Stop the AI service (`docker compose stop ai`) and it becomes `"degraded"` with HTTP 200; stop postgres and it becomes `"down"` with HTTP 503.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `required variable POSTGRES_PASSWORD is missing` | No `.env`. Run `pnpm env:init`. |
| `Ports are not available ... 5432` (or 3000/8000/8080) | Something else listens there. `lsof -nP -iTCP:<port> -sTCP:LISTEN`; change the port in `.env`/compose. |
| `Mounts denied ... not shared from the host` | Something tried to bind-mount a path under `/Library`. Nothing in this repo should; bake files into the image instead. |
| Image pulls fail with `httpReadSeeker ... EOF` | Docker Desktop's proxy dropping Docker Hub CDN downloads. Rerun `docker pull <image>`; finished layers are kept. Persistent: check Docker Desktop → Settings → Resources → Proxies, or restart Docker Desktop. |
| Postgres roles missing / wrong passwords after editing `.env` | The init script only runs on an **empty** volume. `docker compose down -v` (deletes local data) and start again. |
| `pnpm: command not found` | `corepack enable pnpm` (with Node 22 active). |
| `ai` unhealthy, logs show `AI_SERVICE_TOKEN ... placeholder` | `.env` still has the example value; run `pnpm env:init` on a fresh checkout or set a 32+ char random token. |
