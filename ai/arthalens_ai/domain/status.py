"""Derive an IPO's lifecycle status from *verified* fields only (brief section 5).

An old source calling an issue "upcoming" never makes it open: without verified bidding dates
the status is ``unverified``. Status is computed for one IST calendar date and stored with it;
it is never extrapolated forward (a new snapshot is taken instead).
"""

from datetime import UTC, date, datetime
from typing import cast
from zoneinfo import ZoneInfo

from arthalens_ai.contracts.ipo import IpoStatus
from arthalens_ai.domain.resolve import Resolution

IST = ZoneInfo("Asia/Kolkata")


def ist_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(IST).date()


def _as_date(value: object) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) else None


def derive_status(resolution: Resolution, today: date) -> IpoStatus:
    official = resolution.verified("official_status")
    if official in ("withdrawn", "postponed"):
        return cast(IpoStatus, official)

    open_d = _as_date(resolution.verified("open_date"))
    close_d = _as_date(resolution.verified("close_date"))
    listing_d = _as_date(resolution.verified("listing_date"))
    listing_confirmed = resolution.verified("listing_date_basis") == "confirmed"
    confirmed_listing = listing_d if listing_confirmed else None

    if confirmed_listing and today >= confirmed_listing:
        return "listed"
    if open_d is None or close_d is None or close_d < open_d:
        # Missing or inconsistent dates: refuse to guess, whatever any label says.
        return "unverified"
    if today < open_d:
        return "upcoming"
    if today <= close_d:
        return "open"
    if confirmed_listing and today < confirmed_listing:
        return "allotment"
    return "closed"
