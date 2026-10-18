"""Research API contracts (brief section 12), exported to packages/contracts.

The backend assembles these from the database; the worker writes the rows. Status words
shown to people follow brief section 11: ok -> Verified, degraded -> Partial,
unavailable -> Not found.
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from arthalens_ai.contracts.ipo import Authority

ReportStatus = Literal[
    "pending", "running", "completed", "completed_degraded", "failed", "rejected_excluded"
]
SectionStatus = Literal["ok", "degraded", "unavailable"]
DisplayStatus = Literal["Verified", "Partial", "Not found"]
ClaimStatus = Literal["verified", "unverified", "quarantined"]
ClaimType = Literal[
    "business",
    "financial",
    "issue_detail",
    "risk",
    "governance",
    "legal",
    "market",
    "summary",
    "other",
]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class ReportCitation(_Contract):
    label: str
    document_id: UUID
    title: str
    publisher: str
    url: str
    page: int | None
    # Short verbatim excerpt; omitted when the source's display rights are metadata-only.
    quote: str | None
    authority: Authority
    is_synthetic: bool


class ReportClaim(_Contract):
    text: str
    claim_type: ClaimType
    status: ClaimStatus
    status_reason: str | None
    citations: list[ReportCitation]


class ReportSection(_Contract):
    section: Literal["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
    title: str
    status: SectionStatus
    display_status: DisplayStatus
    validation: Literal["pending", "deterministic", "passed"]
    reason: str | None
    missing: list[str]
    model: str | None
    prompt_version: str | None
    claims: list[ReportClaim]


class ResearchReport(_Contract):
    model_config = ConfigDict(title="ResearchReport")

    schema_version: Literal["research-report.v1"] = "research-report.v1"
    id: UUID
    ipo_id: UUID
    company_name: str
    snapshot_version: int
    status: ReportStatus
    is_synthetic: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    sections: list[ReportSection]
    disclaimers: list[str]


class ResearchSummary(_Contract):
    id: UUID
    ipo_id: UUID
    company_name: str
    status: ReportStatus
    created_at: datetime
    completed_at: datetime | None


class ResearchList(_Contract):
    model_config = ConfigDict(title="ResearchList")

    schema_version: Literal["research-list.v1"] = "research-list.v1"
    items: list[ResearchSummary]
    next_cursor: str | None = Field(max_length=500)


class ResearchCreated(_Contract):
    model_config = ConfigDict(title="ResearchCreated")

    report_id: UUID
    status: ReportStatus
    events_url: str
    # False when an Idempotency-Key replay returned an existing report.
    created: bool


class ResearchEvent(_Contract):
    model_config = ConfigDict(title="ResearchEvent")

    seq: int = Field(ge=1)
    type: str
    payload: dict[str, Any]
    created_at: datetime


class EvidenceItem(_Contract):
    label: str
    document_id: UUID
    title: str
    publisher: str
    url: str
    published_at: date | None
    retrieved_at: datetime
    authority: Authority
    source_type: str
    version: int
    is_synthetic: bool
    cited_by_claims: int = Field(ge=0)


class ResearchEvidence(_Contract):
    model_config = ConfigDict(title="ResearchEvidence")

    schema_version: Literal["research-evidence.v1"] = "research-evidence.v1"
    report_id: UUID
    items: list[EvidenceItem]
