"""Turn raw source observations into one resolved value per field.

Implements the source hierarchy in docs/architecture/source-provider-strategy.md, section 3.

Rules, in order:
1. An observation counts only if its quote appears verbatim in the source document, the raw
   value appears in the quote, and the raw value parses. Otherwise it is kept for display only.
2. Among counting observations, the highest authority wins.
3. Within that authority, the most recently published document wins (addenda supersede).
4. If the latest documents at the top authority disagree, the field is a ``conflict`` with no
   value. If lower-authority sources disagree with the winner, the winner stands and the
   discrepancy is noted.
5. No counting observation: ``unverified`` (value shown as unconfirmed) if anything was
   claimed, else ``unavailable``.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date
from typing import Any

from arthalens_ai.contracts.ipo import FIELD_NAMES, Authority, FieldName, FieldStatus
from arthalens_ai.domain import normalize as n

AUTHORITY_RANK: dict[Authority, int] = {
    "official_exchange": 6,
    "official_regulator": 5,
    "issuer_filing": 5,
    "official_registrar": 4,
    "licensed_market_data": 3,
    "credible_news": 2,
    "unofficial": 1,
}

# Raw field name in a source -> (resolved fields it produces, parser returning one value each).
Parser = Callable[[str], tuple[Any, ...]]


def _one(fn: Callable[[str], Any]) -> Parser:
    return lambda raw: (fn(raw),)


def _iso(raw: str) -> str:
    return n.parse_date(raw).isoformat()


def _paise(raw: str) -> str:
    return str(n.parse_money_paise(raw))


def _band(raw: str) -> tuple[str, str]:
    low, high = n.parse_price_band_paise(raw)
    return str(low), str(high)


RAW_FIELDS: dict[str, tuple[tuple[FieldName, ...], Parser]] = {
    "open_date": (("open_date",), _one(_iso)),
    "close_date": (("close_date",), _one(_iso)),
    "listing_date": (("listing_date",), _one(_iso)),
    "listing_date_basis": (("listing_date_basis",), _one(n.parse_listing_basis)),
    "price_band": (("price_band_low", "price_band_high"), _band),
    "lot_size": (("lot_size",), _one(n.parse_positive_int)),
    "issue_size": (("issue_size",), _one(_paise)),
    "fresh_issue_size": (("fresh_issue_size",), _one(_paise)),
    "ofs_size": (("ofs_size",), _one(_paise)),
    "exchanges": (("exchanges",), _one(n.parse_exchanges)),
    "issue_type": (("issue_type",), _one(n.parse_issue_type)),
    "official_status": (("official_status",), _one(n.parse_official_status)),
}


@dataclass(frozen=True)
class EvidenceDoc:
    """The parts of a source document resolution needs."""

    key: str  # stable id within one ingestion (content hash, or evidence uuid once stored)
    authority: Authority
    published_at: date | None
    text: str
    # (page_number, text) per page; page_number is None for formats without pages.
    pages: tuple[tuple[int | None, str], ...] = ()


@dataclass(frozen=True)
class RawObservation:
    raw_field: str
    raw_value: str
    quote: str
    doc: EvidenceDoc


@dataclass(frozen=True)
class Observation:
    """A raw observation mapped onto one resolved field."""

    field: FieldName
    value: Any
    raw_value: str
    quote: str
    quote_verified: bool
    parse_error: str | None
    doc: EvidenceDoc
    page: int | None = None  # page of the document where the quote was found

    @property
    def counts(self) -> bool:
        return self.quote_verified and self.parse_error is None


@dataclass(frozen=True)
class ResolvedField:
    field: FieldName
    status: FieldStatus
    value: Any
    winner: Observation | None
    note: str | None
    observations: tuple[Observation, ...] = ()


def squash(text: str) -> str:
    return " ".join(n._clean(text).split()).casefold()


def quote_supports(quote: str, raw_value: str, doc_text: str) -> bool:
    """Deterministic grounding: the quote is in the document and the value is in the quote.

    Comparison ignores case, Unicode width and whitespace runs, nothing else.
    """
    q = squash(quote)
    return bool(q) and q in squash(doc_text) and squash(raw_value) in q


def expand(raw: RawObservation) -> list[Observation]:
    """Parse one raw observation into one observation per resolved field."""
    if raw.raw_field not in RAW_FIELDS:
        raise ValueError(f"unknown raw field {raw.raw_field!r}")
    targets, parser = RAW_FIELDS[raw.raw_field]
    verified = quote_supports(raw.quote, raw.raw_value, raw.doc.text)
    page = _page_of(raw.quote, raw.doc.pages) if verified else None
    error: str | None = None
    try:
        values: tuple[Any, ...] = parser(raw.raw_value)
    except n.ParseError as exc:
        values, error = (None,) * len(targets), str(exc)[:500]
    return [
        Observation(
            field=f,
            value=v,
            raw_value=raw.raw_value,
            quote=raw.quote,
            quote_verified=verified,
            parse_error=error,
            doc=raw.doc,
            page=page,
        )
        for f, v in zip(targets, values, strict=True)
    ]


def _page_of(quote: str, pages: tuple[tuple[int | None, str], ...]) -> int | None:
    needle = squash(quote)
    for number, text in pages:
        if number is not None and needle in squash(text):
            return number
    return None


def _recency(o: Observation) -> date:
    return o.doc.published_at or date.min


def resolve_field(name: FieldName, observations: Sequence[Observation]) -> ResolvedField:
    obs = tuple(o for o in observations if o.field == name)
    counting = [o for o in obs if o.counts]

    if not counting:
        if not obs:
            return ResolvedField(name, "unavailable", None, None, None, obs)
        best = max(obs, key=lambda o: (AUTHORITY_RANK[o.doc.authority], _recency(o)))
        reason = "value could not be parsed" if best.parse_error else "quote not found in source"
        value = best.value if best.parse_error is None else None
        status: FieldStatus = "unverified" if value is not None else "unavailable"
        return ResolvedField(name, status, value, best, f"Not verified: {reason}", obs)

    top_rank = max(AUTHORITY_RANK[o.doc.authority] for o in counting)
    top = [o for o in counting if AUTHORITY_RANK[o.doc.authority] == top_rank]
    latest = max(_recency(o) for o in top)
    newest = [o for o in top if _recency(o) == latest]
    distinct = {_key(o.value) for o in newest}

    if len(distinct) > 1:
        conflict = "Sources of equal authority and date disagree: " + ", ".join(
            sorted(repr(o.value) for o in newest)
        )
        return ResolvedField(name, "conflict", None, None, conflict, obs)

    winner = newest[0]
    disagreeing = {_key(o.value) for o in counting} - distinct
    note: str | None = None
    if disagreeing:
        note = f"{len(disagreeing)} other source value(s) differ; see observations"
    return ResolvedField(name, "verified", winner.value, winner, note, obs)


def _key(value: Any) -> str:
    return repr(value)


@dataclass
class Resolution:
    fields: dict[FieldName, ResolvedField] = dc_field(default_factory=dict)

    def verified(self, name: FieldName) -> Any | None:
        f = self.fields.get(name)
        return f.value if f and f.status == "verified" else None


def resolve_all(raw: Sequence[RawObservation]) -> Resolution:
    observations = [o for r in raw for o in expand(r)]
    return Resolution({name: resolve_field(name, observations) for name in FIELD_NAMES})
