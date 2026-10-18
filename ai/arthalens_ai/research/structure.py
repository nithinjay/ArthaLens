"""Section D (IPO structure and official details), built by code from the pinned snapshot.

No model is involved. Each claim restates a field that ingestion already verified (its quote
was found verbatim in the stored source), with that field's document, page and quote. Fields
that are not verified are listed as missing, never filled in.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from arthalens_ai.research.contracts import FinalCitation, FinalClaim, SectionResult, SectionStatus

RUPEE = "\u20b9"
CRITICAL = ("open_date", "close_date", "price_band_low", "price_band_high", "lot_size")
FIELD_LABELS = {
    "open_date": "Bidding opens",
    "close_date": "Bidding closes",
    "listing_date": "Listing date",
    "listing_date_basis": "Listing date basis",
    "price_band_low": "Price band (lower)",
    "price_band_high": "Price band (upper)",
    "lot_size": "Lot size",
    "issue_size": "Issue size",
    "fresh_issue_size": "Fresh issue",
    "ofs_size": "Offer for sale",
    "exchanges": "Exchanges",
    "issue_type": "Issue type",
    "official_status": "Official status",
}
STATUS_WORDS = {
    "unverified": "Not verified (source quote not found)",
    "conflict": "Not verified (sources disagree)",
    "unavailable": "Unavailable",
}
VERIFIED_AT_INGESTION = "Verified at ingestion: the quote was found verbatim in the stored source"


@dataclass(frozen=True)
class SnapshotField:
    field: str
    status: str
    value: object
    document_id: str | None
    label: str | None
    page: int | None
    quote: str | None


def group_indian(n: int) -> str:
    """12345678 -> "1,23,45,678" (last three digits, then pairs)."""
    digits = str(n)
    head, tail = digits[:-3], digits[-3:]
    pairs: list[str] = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + pairs + [tail])


def format_inr(paise: int) -> str:
    """Exact INR from paise: crore for amounts of a crore or more, else Indian grouping."""
    rupees = Decimal(paise) / 100
    if rupees >= Decimal(10_000_000):
        crore = (rupees / Decimal(10_000_000)).normalize()
        return f"{RUPEE}{crore:,f} crore"
    whole = int(rupees)
    fraction = paise % 100
    return f"{RUPEE}{group_indian(whole)}" + (f".{fraction:02d}" if fraction else "")


def _date(value: object) -> str:
    return date.fromisoformat(str(value)).strftime("%-d %B %Y")


def _cite(*fields: SnapshotField) -> tuple[FinalCitation, ...]:
    seen: dict[str, FinalCitation] = {}
    for f in fields:
        if f.label and f.document_id and f.label not in seen:
            seen[f.label] = FinalCitation(f.label, f.document_id, f.page, f.quote)
    return tuple(seen.values())


def _claim(text: str, *fields: SnapshotField) -> FinalClaim:
    return FinalClaim(text, "issue_detail", "verified", VERIFIED_AT_INGESTION, _cite(*fields))


def build_structure_section(fields: dict[str, SnapshotField]) -> SectionResult:
    def ok(name: str) -> SnapshotField | None:
        f = fields.get(name)
        return f if f and f.status == "verified" and f.label else None

    claims: list[FinalClaim] = []
    if (o := ok("open_date")) and (c := ok("close_date")):
        claims.append(
            _claim(f"Bidding opens on {_date(o.value)} and closes on {_date(c.value)}.", o, c)
        )
    if (lo := ok("price_band_low")) and (hi := ok("price_band_high")):
        low, high = format_inr(int(str(lo.value))), format_inr(int(str(hi.value)))
        band = low if low == high else f"{low} to {high}"
        claims.append(_claim(f"The price band is {band} per share.", lo, hi))
    if lot := ok("lot_size"):
        claims.append(_claim(f"One lot is {lot.value} shares.", lot))
    if (ld := ok("listing_date")) and (basis := ok("listing_date_basis")):
        claims.append(_claim(f"The listing date is {_date(ld.value)} ({basis.value}).", ld, basis))
    for name, wording in (
        ("issue_size", "The total issue size is"),
        ("fresh_issue_size", "The fresh issue is"),
        ("ofs_size", "The offer for sale is"),
    ):
        if f := ok(name):
            claims.append(_claim(f"{wording} {format_inr(int(str(f.value)))}.", f))
    if ex := ok("exchanges"):
        claims.append(_claim(f"The shares are to be listed on {' and '.join(ex.value)}.", ex))  # type: ignore[arg-type]
    if it := ok("issue_type"):
        claims.append(_claim(f"This is a {'SME' if it.value == 'sme' else 'mainboard'} issue.", it))

    def why(name: str) -> str:
        return (
            STATUS_WORDS.get(fields[name].status, "Unavailable")
            if name in fields
            else "Unavailable"
        )

    missing = tuple(
        f"{FIELD_LABELS[name]}: {why(name)}"
        for name in FIELD_LABELS
        if not ok(name) and name != "official_status"
    )
    verified_critical = sum(1 for n in CRITICAL if ok(n))
    if not claims:
        return SectionResult(
            "D",
            "unavailable",
            "deterministic",
            "No verified issue details in the snapshot.",
            (),
            missing,
        )
    status: SectionStatus = "ok" if verified_critical == len(CRITICAL) else "degraded"
    reason = None if status == "ok" else "Some critical issue details are not verified."
    return SectionResult("D", status, "deterministic", reason, tuple(claims), missing)
