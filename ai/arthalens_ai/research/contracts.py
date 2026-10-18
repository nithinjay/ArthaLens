"""Typed contracts between the research components (brief section 8).

``SectionDraft`` is what a drafting model must return. It is deliberately strict: every claim
cites evidence labels it was shown, with a verbatim quote, so it can be checked
deterministically. Anything that doesn't fit the schema is rejected, never repaired by guessing.
"""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SectionId = Literal["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
SECTION_IDS: tuple[SectionId, ...] = SectionId.__args__  # type: ignore[attr-defined]

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
SectionStatus = Literal["ok", "degraded", "unavailable"]
Validation = Literal["pending", "deterministic", "passed"]
ClaimStatus = Literal["verified", "unverified", "quarantined"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftCitation(_Model):
    label: str = Field(description="Evidence label exactly as shown, e.g. d2", max_length=12)
    quote: str = Field(
        description="Verbatim text copied from that passage that supports the claim",
        min_length=1,
        max_length=1000,
    )


class DraftClaim(_Model):
    text: str = Field(
        description="One factual statement, in plain English", min_length=1, max_length=2000
    )
    claim_type: ClaimType
    citations: list[DraftCitation] = Field(min_length=1, max_length=5)


class SectionDraft(_Model):
    """Output schema for every drafting call."""

    claims: list[DraftClaim] = Field(max_length=25)
    missing: list[str] = Field(
        default_factory=list,
        description="Information the section needs that the evidence does not contain",
        max_length=10,
    )


@dataclass(frozen=True)
class PlannedPassage:
    """A passage shown to a drafting agent, with its evidence label."""

    label: str
    document_id: str
    page: int | None
    text: str
    score: float


@dataclass(frozen=True)
class FinalCitation:
    label: str
    document_id: str
    page: int | None
    quote: str | None


@dataclass(frozen=True)
class FinalClaim:
    text: str
    claim_type: ClaimType
    status: ClaimStatus
    status_reason: str | None
    citations: tuple[FinalCitation, ...]


@dataclass(frozen=True)
class SectionResult:
    section: SectionId
    status: SectionStatus
    validation: Validation
    reason: str | None
    claims: tuple[FinalClaim, ...] = ()
    missing: tuple[str, ...] = ()
    prompt_version: str | None = None
    model: str | None = None
    usage: tuple["UsageRecord", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class UsageRecord:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    outcome: Literal["ok", "invalid_output", "timeout", "error", "budget"]
    estimated_cost_usd: float | None = None
