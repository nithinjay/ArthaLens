"""Report sections A-J (brief section 6): what each one needs and how it is produced.

Kinds:
- ``llm``:          drafted by a model from planned evidence passages (claims stay unverified
                    until the Milestone 5 validator checks them)
- ``deterministic``: built by code from verified data (no model)
- ``summary``:      drafted from the other sections' claims, not from raw evidence
- ``planned``:      not implemented yet; always "Not found" with the reason, never a guess
"""

from dataclasses import dataclass
from typing import Literal

from arthalens_ai.research.contracts import ClaimType, SectionId

Kind = Literal["llm", "deterministic", "summary", "planned"]


@dataclass(frozen=True)
class SectionSpec:
    id: SectionId
    title: str
    kind: Kind
    claim_type: ClaimType = "other"
    keywords: tuple[str, ...] = ()
    max_passages: int = 12
    max_chars: int = 16_000
    planned_reason: str | None = None


CATALOG: dict[SectionId, SectionSpec] = {
    s.id: s
    for s in (
        SectionSpec(
            "A",
            "Company overview",
            "llm",
            "business",
            keywords=(
                "business",
                "products",
                "services",
                "customers",
                "operations",
                "revenue",
                "segment",
                "history",
                "incorporated",
                "competitors",
                "competition",
                "promoter",
                "promoters",
                "management",
                "suppliers",
                "manufacturing",
            ),
        ),
        SectionSpec(
            "B",
            "Financial analysis",
            "planned",
            planned_reason="Financial analysis needs the deterministic metrics engine and numeric "
            "grounding (planned for Milestone 5).",
        ),
        SectionSpec(
            "C",
            "Valuation",
            "planned",
            planned_reason="Valuation needs computed metrics and a justified peer set "
            "(planned for Milestone 5).",
        ),
        SectionSpec("D", "IPO structure and official details", "deterministic", "issue_detail"),
        SectionSpec(
            "E",
            "Prospectus analysis",
            "llm",
            "legal",
            keywords=(
                "objects",
                "proceeds",
                "utilisation",
                "utilization",
                "litigation",
                "proceedings",
                "related party",
                "contingent",
                "material contracts",
                "shareholding",
                "selling shareholder",
                "offer for sale",
                "promoter group",
                "dividend",
            ),
        ),
        SectionSpec(
            "F",
            "Risk assessment",
            "llm",
            "risk",
            keywords=(
                "risk",
                "risks",
                "depend",
                "dependence",
                "concentration",
                "litigation",
                "regulatory",
                "regulation",
                "competition",
                "debt",
                "borrowings",
                "cyclical",
                "adverse",
                "uncertain",
                "default",
                "penalty",
            ),
        ),
        SectionSpec(
            "G",
            "Subscription demand",
            "planned",
            planned_reason="No source of official subscription data is connected yet.",
        ),
        SectionSpec(
            "H",
            "Grey-market premium",
            "planned",
            planned_reason="GMP is unofficial and disabled by default (source-provider strategy).",
        ),
        SectionSpec(
            "I",
            "Listing scenarios",
            "planned",
            planned_reason="Listing scenarios are built with the calculator "
            "(planned for Milestone 7).",
        ),
        SectionSpec("J", "Summary", "summary", "summary"),
    )
}

PARALLEL_SECTIONS: tuple[SectionId, ...] = ("A", "B", "C", "D", "E", "F", "G", "H", "I")
"""Independent sections run concurrently; J runs after them (it summarises their claims)."""
