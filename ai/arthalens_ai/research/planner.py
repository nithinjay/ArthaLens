"""Retrieval planner (brief sections 8 and 11): which evidence each section gets.

Deterministic: passages are ranked by section keywords, ties broken by label, page and
position, so the same evidence always gives the same plan. A section only ever sees the
passages planned for it, never whole documents (token budget and injection surface).

Milestone 4 plans over the report's evidence set (the snapshot's documents). Broader
retrieval through SearchPort, when coverage is insufficient, comes with live providers.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from arthalens_ai.research.catalog import SectionSpec
from arthalens_ai.research.contracts import PlannedPassage


@dataclass(frozen=True)
class LabelledPassage:
    label: str
    document_id: str
    source_type: str
    page: int | None
    passage_index: int
    text: str


@dataclass(frozen=True)
class SectionPlan:
    section: str
    passages: tuple[PlannedPassage, ...]
    covered: bool
    reason: str | None

    @property
    def labels(self) -> frozenset[str]:
        return frozenset(p.label for p in self.passages)


def _label_number(label: str) -> int:
    return int(label[1:]) if label[1:].isdigit() else 10**9


def _patterns(keywords: Sequence[str]) -> list[re.Pattern[str]]:
    return [re.compile(rf"\b{re.escape(k.casefold())}", re.IGNORECASE) for k in keywords]


def score(text: str, patterns: Sequence[re.Pattern[str]]) -> float:
    lowered = text.casefold()
    # Each keyword counts at most three times, so one repetitive passage can't dominate.
    hits = sum(min(len(p.findall(lowered)), 3) for p in patterns)
    if not hits:
        return 0.0
    return hits / (1 + len(lowered) / 2000)  # mild preference for focused passages


def plan_section(spec: SectionSpec, passages: Sequence[LabelledPassage]) -> SectionPlan:
    patterns = _patterns(spec.keywords)
    ranked = sorted(
        ((score(p.text, patterns), p) for p in passages),
        key=lambda sp: (
            -sp[0],
            0 if sp[1].source_type == "offer_document" else 1,
            _label_number(sp[1].label),
            sp[1].page or 0,
            sp[1].passage_index,
        ),
    )
    chosen: list[PlannedPassage] = []
    used = 0
    for s, p in ranked:
        if s <= 0 or len(chosen) >= spec.max_passages:
            break
        if used + len(p.text) > spec.max_chars and chosen:
            continue
        chosen.append(PlannedPassage(p.label, p.document_id, p.page, p.text, round(s, 4)))
        used += len(p.text)
    # Present passages in document order: easier to read, and stable.
    chosen.sort(key=lambda c: (_label_number(c.label), c.page or 0))
    if not chosen:
        return SectionPlan(
            spec.id,
            (),
            covered=False,
            reason="No passage in the evidence addresses this section (an offer document is "
            "usually needed).",
        )
    return SectionPlan(spec.id, tuple(chosen), covered=True, reason=None)


_DELIMITERS = re.compile(r"<(/?)(evidence|passage)", re.IGNORECASE)


def _neutralise(text: str) -> str:
    """Stop source text from closing or opening our delimiters (prompt injection, T-30).

    The angle bracket becomes its full-width form. Quote verification applies NFKC, which
    folds it back, so a quote copied from the rendered text still matches the original.
    """
    return _DELIMITERS.sub(lambda m: "\uff1c" + m.group(1) + m.group(2), text)


def render_evidence(passages: Sequence[PlannedPassage]) -> str:
    """The evidence block sent as *data* in the user message, never in instructions."""
    parts = ["<evidence>"]
    for p in passages:
        page = f' page="{p.page}"' if p.page is not None else ""
        parts.append(f'<passage label="{p.label}"{page}>\n{_neutralise(p.text)}\n</passage>')
    parts.append("</evidence>")
    return "\n".join(parts)
