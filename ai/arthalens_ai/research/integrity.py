"""Citation integrity for drafted claims (validation tier T1, brief section 10).

Milestone 4 applies only the checks that need no judgement:
- a citation must use a label the agent was actually shown (no fabricated source ids)
- it must carry a non-empty quote
A claim with no valid citation is quarantined. Every other drafted claim stays ``unverified``:
literal grounding (T2) and entailment (T3) arrive with the Milestone 5 validator, and nothing
is marked verified before then.
"""

from collections.abc import Sequence

from arthalens_ai.domain.resolve import squash
from arthalens_ai.research.contracts import (
    FinalCitation,
    FinalClaim,
    PlannedPassage,
    SectionDraft,
)

AWAITING_VALIDATION = "Not yet validated (claim validation arrives in Milestone 5)"
QUOTE_NOT_FOUND = "Quote not found in the cited passage; not yet validated"
NO_VALID_CITATION = "Quarantined: cites no evidence the agent was shown"


def check_citations(draft: SectionDraft, shown: Sequence[PlannedPassage]) -> tuple[FinalClaim, ...]:
    by_label: dict[str, list[PlannedPassage]] = {}
    for p in shown:
        by_label.setdefault(p.label, []).append(p)

    claims: list[FinalClaim] = []
    for claim in draft.claims:
        citations: list[FinalCitation] = []
        all_quotes_found = True
        for c in claim.citations:
            passages = by_label.get(c.label.strip())
            if not passages or not c.quote.strip():
                continue
            needle = squash(c.quote)
            match = next((p for p in passages if needle in squash(p.text)), None)
            all_quotes_found &= match is not None
            source = match or passages[0]
            citations.append(
                FinalCitation(
                    label=source.label,
                    document_id=source.document_id,
                    page=match.page if match else None,
                    quote=c.quote.strip()[:1000],
                )
            )
        if not citations:
            claims.append(
                FinalClaim(claim.text, claim.claim_type, "quarantined", NO_VALID_CITATION, ())
            )
            continue
        reason = AWAITING_VALIDATION if all_quotes_found else QUOTE_NOT_FOUND
        claims.append(
            FinalClaim(claim.text, claim.claim_type, "unverified", reason, tuple(citations))
        )
    return tuple(claims)
