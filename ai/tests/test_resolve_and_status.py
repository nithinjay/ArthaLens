from datetime import date

import pytest

from arthalens_ai.contracts.ipo import Authority
from arthalens_ai.domain.resolve import (
    EvidenceDoc,
    RawObservation,
    expand,
    quote_supports,
    resolve_all,
    resolve_field,
)
from arthalens_ai.domain.status import derive_status, ist_today


def doc(
    key: str,
    text: str,
    authority: Authority = "official_exchange",
    published: date | None = date(2026, 10, 1),
) -> EvidenceDoc:
    return EvidenceDoc(key=key, authority=authority, published_at=published, text=text)


def obs(raw_field: str, raw_value: str, quote: str, d: EvidenceDoc) -> RawObservation:
    return RawObservation(raw_field=raw_field, raw_value=raw_value, quote=quote, doc=d)


# --- grounding ----------------------------------------------------------------------------


def test_quote_must_be_in_document_and_contain_value() -> None:
    text = "SYNTHETIC. Minimum Bid Lot:  50 Equity Shares and in multiples thereof."
    assert quote_supports("Minimum Bid Lot: 50 Equity Shares", "50 Equity Shares", text)
    assert not quote_supports("Minimum Bid Lot: 60 Equity Shares", "60 Equity Shares", text)
    assert not quote_supports("Minimum Bid Lot: 50 Equity Shares", "75", text)
    assert not quote_supports("", "50", text)


def test_price_band_expands_into_two_fields() -> None:
    d = doc("n", "Price Band: Rs 285 to Rs 300 per equity share")
    out = expand(obs("price_band", "Rs 285 to Rs 300", "Price Band: Rs 285 to Rs 300", d))
    assert [(o.field, o.value, o.counts) for o in out] == [
        ("price_band_low", "28500", True),
        ("price_band_high", "30000", True),
    ]


def test_unknown_raw_field_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="unknown raw field"):
        expand(obs("market_cap", "x", "x", doc("n", "x")))


# --- resolution ---------------------------------------------------------------------------

LOT_50 = "Lot size: 50 shares"
LOT_60 = "Lot size: 60 shares"


def lot(d: EvidenceDoc, value: str) -> list:  # type: ignore[type-arg]
    return expand(obs("lot_size", value, f"Lot size: {value} shares", d))


def test_single_grounded_source_is_verified() -> None:
    r = resolve_field("lot_size", lot(doc("a", LOT_50), "50"))
    assert (r.status, r.value, r.note) == ("verified", 50, None)
    assert r.winner is not None and r.winner.doc.key == "a"


def test_higher_authority_wins_and_discrepancy_is_noted() -> None:
    exchange = doc("ex", LOT_50, "official_exchange")
    news = doc("news", LOT_60, "credible_news", date(2026, 10, 5))
    r = resolve_field("lot_size", lot(exchange, "50") + lot(news, "60"))
    assert (r.status, r.value) == ("verified", 50)
    assert r.note and "differ" in r.note
    assert len(r.observations) == 2


def test_newer_document_at_same_authority_supersedes() -> None:
    old = doc("v1", LOT_50, published=date(2026, 10, 1))
    addendum = doc("v2", LOT_60, published=date(2026, 10, 9))
    r = resolve_field("lot_size", lot(old, "50") + lot(addendum, "60"))
    assert (r.status, r.value) == ("verified", 60)


def test_equal_authority_same_date_disagreement_is_conflict() -> None:
    a = doc("a", LOT_50)
    b = doc("b", LOT_60)
    r = resolve_field("lot_size", lot(a, "50") + lot(b, "60"))
    assert (r.status, r.value, r.winner) == ("conflict", None, None)
    assert r.note and "disagree" in r.note


def test_ungrounded_quote_is_unverified_not_verified() -> None:
    d = doc("a", "This document says nothing about lots.")
    r = resolve_field("lot_size", lot(d, "50"))
    assert (r.status, r.value) == ("unverified", 50)
    assert r.note == "Not verified: quote not found in source"


def test_unparseable_value_is_unavailable() -> None:
    d = doc("a", "Lot size: TBA shares")
    r = resolve_field("lot_size", expand(obs("lot_size", "TBA", "Lot size: TBA shares", d)))
    assert (r.status, r.value) == ("unavailable", None)
    assert r.note == "Not verified: value could not be parsed"


def test_no_observation_is_unavailable() -> None:
    r = resolve_field("issue_size", [])
    assert (r.status, r.value, r.note) == ("unavailable", None, None)


def test_grounded_low_authority_beats_ungrounded_high_authority() -> None:
    """Authority never rescues a claim its own document doesn't support."""
    exchange = doc("ex", "Nothing relevant here.", "official_exchange")
    issuer = doc("rhp", LOT_60, "issuer_filing")
    r = resolve_field("lot_size", lot(exchange, "50") + lot(issuer, "60"))
    assert (r.status, r.value) == ("verified", 60)


# --- status -------------------------------------------------------------------------------

NOTICE = (
    "SYNTHETIC NOTICE. Bid opens on 20 October 2026. Bid closes on 22 October 2026. "
    "Listing date: 27 October 2026 (Confirmed). Status: Upcoming. Issue withdrawn."
)


def resolution(**raw: str):  # type: ignore[no-untyped-def]
    d = doc("n", NOTICE)
    quotes = {
        "open_date": "Bid opens on {v}",
        "close_date": "Bid closes on {v}",
        "listing_date": "Listing date: {v}",
        "listing_date_basis": "(Confirmed)",
        "official_status": "Status: {v}",
    }
    observations = []
    for field_name, value in raw.items():
        quote = quotes[field_name].format(v=value)
        if field_name == "official_status" and value == "withdrawn":
            quote = "Issue withdrawn"
        if field_name == "listing_date_basis":
            value = "Confirmed"
        observations.append(obs(field_name, value, quote, d))
    return resolve_all(observations)


DATES = {"open_date": "20 October 2026", "close_date": "22 October 2026"}
LISTING = {"listing_date": "27 October 2026", "listing_date_basis": "confirmed"}


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 19), "upcoming"),
        (date(2026, 10, 20), "open"),
        (date(2026, 10, 22), "open"),
        (date(2026, 10, 23), "allotment"),
        (date(2026, 10, 27), "listed"),
        (date(2026, 11, 30), "listed"),
    ],
)
def test_status_follows_verified_dates(today: date, expected: str) -> None:
    assert derive_status(resolution(**DATES, **LISTING), today) == expected


def test_closed_when_no_confirmed_listing_date() -> None:
    assert derive_status(resolution(**DATES), date(2026, 10, 25)) == "closed"


def test_stale_upcoming_label_without_dates_is_unverified() -> None:
    """Brief section 5: an old 'upcoming' label never implies the issue is accepting bids."""
    assert derive_status(resolution(official_status="Upcoming"), date(2026, 10, 21)) == "unverified"


def test_withdrawn_overrides_dates() -> None:
    r = resolution(**DATES, official_status="withdrawn")
    assert derive_status(r, date(2026, 10, 21)) == "withdrawn"


def test_inconsistent_dates_are_unverified() -> None:
    d = doc("n", "Bid opens on 22 October 2026. Bid closes on 20 October 2026.")
    r = resolve_all(
        [
            obs("open_date", "22 October 2026", "Bid opens on 22 October 2026", d),
            obs("close_date", "20 October 2026", "Bid closes on 20 October 2026", d),
        ]
    )
    assert derive_status(r, date(2026, 10, 21)) == "unverified"


def test_ist_today_crosses_midnight_before_utc() -> None:
    from datetime import UTC, datetime

    # 19:00 UTC on 17 Oct is 00:30 IST on 18 Oct.
    assert ist_today(datetime(2026, 10, 17, 19, 0, tzinfo=UTC)) == date(2026, 10, 18)
