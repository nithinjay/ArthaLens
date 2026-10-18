from datetime import date

import pytest

from arthalens_ai.domain.normalize import (
    ParseError,
    parse_date,
    parse_exchanges,
    parse_issue_type,
    parse_listing_basis,
    parse_money_paise,
    parse_official_status,
    parse_positive_int,
    parse_price_band_paise,
)

R = "\u20b9"  # rupee sign; kept as an escape so the source stays ASCII


@pytest.mark.parametrize(
    ("text", "paise"),
    [
        (f"{R}1,234.56 crore", 1_234_56 * 10**7),
        ("Rs. 1,234.56 Cr", 1_234_56 * 10**7),
        ("INR 500 crores", 500 * 10**7 * 100),
        (f"{R} 12,00,000", 12_00_000 * 100),
        ("Rs 75 lakh", 75 * 10**5 * 100),
        ("Rs. 2.5 lakhs", 250_000 * 100),
        ("Rs 9.4 crore", 94_000_000 * 100),
        ("Rs 9.4 billion", 9_400_000_000 * 100),
        ("Rs 300", 30000),
        ("Rs 300.50", 30050),
        ("1,000 million", 1_000_000_000 * 100),
        (f"{R}450 crore only", 450 * 10**7 * 100),
    ],
)
def test_parse_money_paise(text: str, paise: int) -> None:
    assert parse_money_paise(text) == paise


def test_crore_and_billion_are_never_confused() -> None:
    """Brief section 10: Rs 9.4 crore and Rs 9.4 billion differ by 100x."""
    assert parse_money_paise("Rs 9.4 billion") == 100 * parse_money_paise("Rs 9.4 crore")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "crore",
        "Rs",
        "-5 crore",
        "Rs 0",
        "Rs 12.345",
        "USD 100",
        "about 500 crore",
        "500 crore+",
    ],
)
def test_parse_money_rejects(text: str) -> None:
    with pytest.raises(ParseError):
        parse_money_paise(text)


@pytest.mark.parametrize(
    ("text", "band"),
    [
        (f"{R}285 to {R}300", (28500, 30000)),
        ("Rs. 285 - 300 per equity share", (28500, 30000)),
        (f"{R} 285\u2013{R} 300", (28500, 30000)),
        (f"{R}1,045 to {R}1,100 per share of face value {R}10 each", (104500, 110000)),
        (f"{R}120 per equity share", (12000, 12000)),
        ("Rs 285 to Rs 300 per Equity Share of face value of Rs 2 each", (28500, 30000)),
    ],
)
def test_parse_price_band(text: str, band: tuple[int, int]) -> None:
    assert parse_price_band_paise(text) == band


@pytest.mark.parametrize("text", ["Rs 300 to Rs 285", "price band to be announced", "300"])
def test_parse_price_band_rejects(text: str) -> None:
    with pytest.raises(ParseError):
        parse_price_band_paise(text)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("50", 50),
        ("50 Equity Shares", 50),
        ("1,200 shares", 1200),
        ("12,000 Equity Shares.", 12000),
    ],
)
def test_parse_positive_int(text: str, value: int) -> None:
    assert parse_positive_int(text) == value


@pytest.mark.parametrize(
    "text", ["0", "50 shares and in multiples of 50", "fifty", "-5", "50.5", ""]
)
def test_parse_positive_int_rejects(text: str) -> None:
    with pytest.raises(ParseError):
        parse_positive_int(text)


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-22",
        "22 October 2026",
        "22 Oct 2026",
        "October 22, 2026",
        "Wednesday, October 22, 2026",
        "22nd October 2026",
        "22-10-2026",
        "22/10/2026",
        "22.10.2026",
    ],
)
def test_parse_date(text: str) -> None:
    assert parse_date(text) == date(2026, 10, 22)


def test_numeric_dates_are_day_first() -> None:
    assert parse_date("03/11/2026") == date(2026, 11, 3)


@pytest.mark.parametrize("text", ["31/02/2026", "next week", "2026-13-01", "October 2026"])
def test_parse_date_rejects(text: str) -> None:
    with pytest.raises(ParseError):
        parse_date(text)


@pytest.mark.parametrize(
    ("text", "codes"),
    [
        ("NSE and BSE", ["BSE", "NSE"]),
        ("BSE SME", ["BSE"]),
        ("NSE Emerge", ["NSE"]),
        ("National Stock Exchange of India and BSE Limited", ["BSE", "NSE"]),
    ],
)
def test_parse_exchanges(text: str, codes: list[str]) -> None:
    assert parse_exchanges(text) == codes


def test_parse_exchanges_rejects_unknown() -> None:
    with pytest.raises(ParseError):
        parse_exchanges("NASDAQ")


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Mainboard", "mainboard"),
        ("Main Board IPO", "mainboard"),
        ("SME IPO", "sme"),
        ("NSE Emerge", "sme"),
    ],
)
def test_parse_issue_type(text: str, kind: str) -> None:
    assert parse_issue_type(text) == kind


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("Issue withdrawn by the company", "withdrawn"),
        ("Postponed", "postponed"),
        ("Bidding open", "open"),
        ("Upcoming issue", "upcoming"),
        ("Listed on 13 October", "listed"),
    ],
)
def test_parse_official_status(text: str, status: str) -> None:
    assert parse_official_status(text) == status


@pytest.mark.parametrize(
    ("text", "basis"),
    [
        ("Tentative listing date", "estimated"),
        ("Expected", "estimated"),
        ("Confirmed", "confirmed"),
    ],
)
def test_parse_listing_basis(text: str, basis: str) -> None:
    assert parse_listing_basis(text) == basis


def test_parse_listing_basis_rejects_unlabelled() -> None:
    """Brief section 5: listing dates must be marked confirmed or estimated, never assumed."""
    with pytest.raises(ParseError):
        parse_listing_basis("27 October 2026")
