"""FastAPI application factory.

Run with: uvicorn --factory arthalens_ai.main:create_app
"""

import logging
import re
import uuid
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from arthalens_ai import __version__
from arthalens_ai.config import Settings
from arthalens_ai.contracts.health import ServiceHealth, overall_status
from arthalens_ai.db import DbCheck, PostgresCheck
from arthalens_ai.security import require_service_token

REQUEST_ID_HEADER = "x-request-id"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def create_app(settings: Settings | None = None, db_check: DbCheck | None = None) -> FastAPI:
    settings = settings or Settings()  # values come from the environment
    logging.basicConfig(level=settings.log_level.upper())
    if db_check is None:
        db_check = PostgresCheck(
            settings.database_url.get_secret_value(), settings.db_check_timeout_s
        )
    is_production = settings.environment == "production"

    app = FastAPI(
        title="ArthaLens AI service",
        version=__version__,
        # The AI service is internal-only; don't publish interactive docs in production.
        docs_url=None if is_production else "/docs",
        redoc_url=None,
        openapi_url=None if is_production else "/openapi.json",
    )

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Reuse the caller's ID so one request can be traced across services.
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        rid = incoming if _REQUEST_ID_PATTERN.match(incoming) else str(uuid.uuid4())
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = rid
        return response

    async def readiness() -> ServiceHealth:
        checks = {"database": await db_check()}
        return ServiceHealth(
            service="ai", status=overall_status(checks), version=__version__, checks=checks
        )

    def as_response(health: ServiceHealth) -> JSONResponse:
        code = 200 if health.status == "ok" else 503
        return JSONResponse(health.model_dump(mode="json"), status_code=code)

    @app.get("/healthz", response_model=ServiceHealth)
    async def healthz() -> ServiceHealth:
        """Liveness: the process is up. No dependency checks."""
        return ServiceHealth(service="ai", status="ok", version=__version__)

    @app.get("/readyz", response_model=ServiceHealth, responses={503: {"model": ServiceHealth}})
    async def readyz() -> JSONResponse:
        """Readiness: dependencies reachable. Used by container health checks."""
        return as_response(await readiness())

    internal = APIRouter(
        prefix="/internal/v1",
        dependencies=[Depends(require_service_token(settings.service_token))],
    )

    @internal.get(
        "/health", response_model=ServiceHealth, responses={503: {"model": ServiceHealth}}
    )
    async def internal_health() -> JSONResponse:
        """Authenticated readiness, called by backend/ to prove service-to-service auth works."""
        return as_response(await readiness())

    app.include_router(internal)
    return app
