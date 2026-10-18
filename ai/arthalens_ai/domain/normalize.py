"""Parse raw values from Indian IPO source documents into exact, typed values.

Everything here is deterministic and raises ``ParseError`` rather than guessing. Money is
returned as integer paise (ADR-0006); never floats. Milestone 5's validator reuses these parsers.
"""

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

RUPEE = "\u20b9"
DASHES = "\u2010\u2011\u2012\u2013\u2014\u2212"  # hyphen variants, en/em dash, minus

ExchangeCode = Literal["NSE", "BSE"]
IssueType = Literal["mainboard", "sme"]
OfficialStatus = Literal[
    "upcoming", "open", "closed", "allotment", "listed", "withdrawn", "postponed"
]
ListingBasis = Literal["confirmed", "estimated"]


class ParseError(ValueError):
    """The raw text could not be parsed unambiguously."""


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for dash in DASHES:
        text = text.replace(dash, "-")
    return " ".join(text.split())


# --- Money ---------------------------------------------------------------------------------

# Scale words, longest first so "crores" wins over "cr".
_SCALES: tuple[tuple[str, int], ...] = (
    ("crores", 10**7),
    ("crore", 10**7),
    ("cr", 10**7),
    ("lakhs", 10**5),
    ("lakh", 10**5),
    ("lacs", 10**5),
    ("lac", 10**5),
    ("billion", 10**9),
    ("bn", 10**9),
    ("million", 10**6),
    ("mn", 10**6),
    ("thousand", 10**3),
)
_CURRENCY = rf"(?:{RUPEE}|rs\.?|inr)"
_NUMBER = r"\d{1,3}(?:,\d{2,3})*(?:\.\d+)?|\d+(?:\.\d+)?"
_MONEY_RE = re.compile(
    rf"^(?P<cur>{_CURRENCY})?\s*(?P<num>{_NUMBER})\s*"
    rf"(?P<scale>{'|'.join(s for s, _ in _SCALES)})?\.?$",
    re.IGNORECASE,
)


def _to_decimal(number: str) -> Decimal:
    digits = number.replace(",", "")
    try:
        return Decimal(digits)
    except InvalidOperation as exc:  # pragma: no cover - regex already guarantees digits
        raise ParseError(f"not a number: {number!r}") from exc


def parse_money_paise(text: str) -> int:
    """'Rs. 1,234.56 crore' -> 1234560000000 paise. Rejects negatives and sub-paisa precision."""
    cleaned = _clean(text).removesuffix(" only")
    match = _MONEY_RE.match(cleaned)
    if not match:
        raise ParseError(f"not an INR amount: {text!r}")
    amount = _to_decimal(match.group("num"))
    scale_word = (match.group("scale") or "").lower()
    scale = dict(_SCALES).get(scale_word, 1)
    paise = amount * scale * 100
    if paise != paise.to_integral_value():
        raise ParseError(f"amount has sub-paisa precision: {text!r}")
    if paise <= 0:
        raise ParseError(f"amount must be positive: {text!r}")
    return int(paise)


# --- Price band ----------------------------------------------------------------------------

_BAND_RE = re.compile(
    rf"{_CURRENCY}?\s*(?P<low>{_NUMBER})\s*(?:-|to)\s*{_CURRENCY}?\s*(?P<high>{_NUMBER})",
    re.IGNORECASE,
)
_FIXED_RE = re.compile(rf"^{_CURRENCY}\s*(?P<price>{_NUMBER})(?:\s+per\b.*)?$", re.IGNORECASE)


def parse_price_band_paise(text: str) -> tuple[int, int]:
    """'Rs 285 to Rs 300 per equity share' -> (28500, 30000). A fixed price returns (p, p)."""
    cleaned = _clean(text)
    # Ignore anything after "face value" so "of face value Rs 2 each" is never read as the band.
    head = re.split(r"\bface value\b", cleaned, flags=re.IGNORECASE)[0]
    match = _BAND_RE.search(head)
    if match:
        low = parse_money_paise(match.group("low"))
        high = parse_money_paise(match.group("high"))
    else:
        fixed = _FIXED_RE.match(head.strip(" ,;"))
        if not fixed:
            raise ParseError(f"not a price band: {text!r}")
        low = high = parse_money_paise(fixed.group("price"))
    if low > high:
        raise ParseError(f"price band low exceeds high: {text!r}")
    return low, high


# --- Integers (lot size, share counts) -----------------------------------------------------

_INT_RE = re.compile(
    r"^(?P<num>\d{1,3}(?:,\d{2,3})*|\d+)\s*(?:equity\s+)?(?:shares?)?\.?$", re.IGNORECASE
)


def parse_positive_int(text: str) -> int:
    """'1,200 Equity Shares' -> 1200. The whole value must be one count, nothing else."""
    match = _INT_RE.match(_clean(text))
    if not match:
        raise ParseError(f"not a share count: {text!r}")
    value = int(match.group("num").replace(",", ""))
    if value <= 0:
        raise ParseError(f"count must be positive: {text!r}")
    return value


# --- Dates ---------------------------------------------------------------------------------

_WEEKDAY = re.compile(r"^(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*,?\s+", re.IGNORECASE)
_DATE_FORMATS = (
    "%Y-%m-%d",  # ISO first: unambiguous
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%d-%m-%Y",  # numeric dates are day-first in Indian documents
    "%d/%m/%Y",
    "%d.%m.%Y",
)


def parse_date(text: str) -> date:
    """'Wednesday, October 22, 2026' / '22-10-2026' -> date(2026, 10, 22). Day-first numerics."""
    cleaned = _WEEKDAY.sub("", _clean(text)).rstrip(".")
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", cleaned, flags=re.IGNORECASE)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ParseError(f"not a date: {text!r}")


# --- Categorical fields --------------------------------------------------------------------


def parse_exchanges(text: str) -> list[ExchangeCode]:
    """'NSE and BSE' / 'BSE SME' / 'NSE Emerge' -> sorted unique exchange codes."""
    words = set(re.findall(r"[a-z]+", _clean(text).lower()))
    found: set[ExchangeCode] = set()
    if words & {"nse", "emerge"} or "national stock exchange" in _clean(text).lower():
        found.add("NSE")
    if "bse" in words or "bombay stock exchange" in _clean(text).lower():
        found.add("BSE")
    if not found:
        raise ParseError(f"no exchange named: {text!r}")
    return sorted(found)


def parse_issue_type(text: str) -> IssueType:
    lowered = _clean(text).lower()
    if re.search(r"\bsme\b|\bemerge\b", lowered):
        return "sme"
    if re.search(r"\bmain\s*-?\s*board\b", lowered):
        return "mainboard"
    raise ParseError(f"unknown issue type: {text!r}")


_STATUS_WORDS: tuple[tuple[str, OfficialStatus], ...] = (
    ("withdrawn", "withdrawn"),
    ("postponed", "postponed"),
    ("deferred", "postponed"),
    ("listed", "listed"),
    ("allotment", "allotment"),
    ("closed", "closed"),
    ("open", "open"),
    ("upcoming", "upcoming"),
    ("forthcoming", "upcoming"),
)


def parse_official_status(text: str) -> OfficialStatus:
    lowered = _clean(text).lower()
    for word, status in _STATUS_WORDS:
        if re.search(rf"\b{word}\b", lowered):
            return status
    raise ParseError(f"unknown issue status: {text!r}")


def parse_listing_basis(text: str) -> ListingBasis:
    lowered = _clean(text).lower()
    if re.search(r"\b(tentative|expected|estimated|proposed)\b", lowered):
        return "estimated"
    if re.search(r"\b(confirmed|final)\b", lowered):
        return "confirmed"
    raise ParseError(f"listing date basis must say confirmed or estimated: {text!r}")
