"""Versioned contracts shared with the TypeScript side (ADR-0007).

Pydantic models here are the source of truth. ``export.py`` writes their JSON Schemas to
``packages/contracts/schemas``; TypeScript types are generated from those files.
"""

from pydantic import BaseModel

from arthalens_ai.contracts.health import DependencyCheck, ServiceHealth
from arthalens_ai.contracts.ipo import IpoDetail, IpoList
from arthalens_ai.contracts.research import (
    ResearchCreated,
    ResearchEvent,
    ResearchEvidence,
    ResearchList,
    ResearchReport,
)

# Every model listed here is exported. Schema file name = key.
EXPORTED_MODELS: dict[str, type[BaseModel]] = {
    "service-health.v1": ServiceHealth,
    "ipo-list.v1": IpoList,
    "ipo-detail.v1": IpoDetail,
    "research-report.v1": ResearchReport,
    "research-list.v1": ResearchList,
    "research-created.v1": ResearchCreated,
    "research-event.v1": ResearchEvent,
    "research-evidence.v1": ResearchEvidence,
}

__all__ = ["EXPORTED_MODELS", "DependencyCheck", "IpoDetail", "IpoList", "ServiceHealth"]
