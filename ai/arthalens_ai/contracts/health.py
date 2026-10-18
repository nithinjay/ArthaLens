"""Health/readiness contract used by every service and the frontend status panel."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DependencyCheck(BaseModel):
    """Result of checking one dependency (database, another service, ...)."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    status: Literal["ok", "down"]
    latency_ms: int | None = Field(default=None, ge=0)
    # Generic, non-sensitive description. Never include hosts, DSNs or exception text.
    detail: str | None = Field(default=None, max_length=200)


class ServiceHealth(BaseModel):
    """Liveness/readiness report for one service."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_serialization_defaults_required=True,
        title="ServiceHealth",
    )

    schema_version: Literal["service-health.v1"] = "service-health.v1"
    service: Literal["backend", "ai"]
    status: Literal["ok", "degraded", "down"]
    version: str
    checks: dict[str, DependencyCheck] = Field(default_factory=dict)


def overall_status(checks: dict[str, DependencyCheck]) -> Literal["ok", "down"]:
    """A service is ready only if every dependency it needs is up."""
    return "ok" if all(c.status == "ok" for c in checks.values()) else "down"
