# syntax=docker/dockerfile:1
# ArthaLens AI service. Build context: repository root (needs packages/policy).

FROM python:3.13.16-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first so code changes don't invalidate the dependency layer.
COPY ai/pyproject.toml ai/uv.lock ai/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY ai/arthalens_ai arthalens_ai
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13.16-slim-bookworm AS runtime
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
# Exclusion policy (shared with backend/) and SYNTHETIC fixtures for the dev "discover" command.
COPY packages/policy/exclusions.v1.json packages/policy/exclusion-vectors.v1.json /app/policy/
COPY ai/fixtures /app/fixtures
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    POLICY_DIR=/app/policy \
    FIXTURES_DIR=/app/fixtures/ipos
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "--factory", "arthalens_ai.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
