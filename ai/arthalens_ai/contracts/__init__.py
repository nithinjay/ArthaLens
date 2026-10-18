"""Versioned contracts shared with the TypeScript side (ADR-0007).

Pydantic models here are the source of truth. ``export.py`` writes their JSON Schemas to
``packages/contracts/schemas``; TypeScript types are generated from those files.
"""

from arthalens_ai.contracts.health import DependencyCheck, ServiceHealth

# Every model listed here is exported. Schema file name = key.
EXPORTED_MODELS = {
    "service-health.v1": ServiceHealth,
}

__all__ = ["EXPORTED_MODELS", "DependencyCheck", "ServiceHealth"]
