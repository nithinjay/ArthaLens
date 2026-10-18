"""Data freshness per source type (source-provider strategy, section 4).

Initial values; calibrated later. Offer documents and regulator publications don't age out:
they are superseded by a newer version of the same source instead.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

MAX_AGE: dict[str, timedelta | None] = {
    "exchange_notice": timedelta(hours=24),
    "registrar_notice": timedelta(hours=24),
    "issuer_website": timedelta(days=7),
    "news": timedelta(days=7),
    "other": timedelta(days=7),
    "offer_document": None,
    "regulator_publication": None,
}

FreshnessStatus = Literal["fresh", "stale", "no_expiry"]


@dataclass(frozen=True)
class Freshness:
    status: FreshnessStatus
    age: timedelta
    stale_after: datetime | None


def freshness(source_type: str, retrieved_at: datetime, now: datetime) -> Freshness:
    if source_type not in MAX_AGE:
        raise ValueError(f"unknown source type {source_type!r}")
    age = max(now - retrieved_at, timedelta(0))
    limit = MAX_AGE[source_type]
    if limit is None:
        return Freshness("no_expiry", age, None)
    stale_after = retrieved_at + limit
    return Freshness("fresh" if now <= stale_after else "stale", age, stale_after)
