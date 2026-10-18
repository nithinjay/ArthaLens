"""IPO contracts shared with backend/ and frontend/ (exported to packages/contracts).

Value encoding inside ``IpoField.value`` (JSON has no exact money or date type):
- dates: ISO ``"YYYY-MM-DD"``
- money: integer paise as a decimal string, e.g. ``"30000"`` for Rs 300 (ADR-0006)
- lot_size: integer
- exchanges: list of ``"NSE"`` / ``"BSE"``
- everything else: a lowercase code string
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

FieldName = Literal[
    "open_date",
    "close_date",
    "listing_date",
    "listing_date_basis",
    "price_band_low",
    "price_band_high",
    "lot_size",
    "issue_size",
    "fresh_issue_size",
    "ofs_size",
    "exchanges",
    "issue_type",
    "official_status",
]
FIELD_NAMES: tuple[FieldName, ...] = FieldName.__args__  # type: ignore[attr-defined]

FieldStatus = Literal["verified", "unverified", "conflict", "unavailable"]
IpoStatus = Literal[
    "upcoming", "open", "closed", "allotment", "listed", "withdrawn", "postponed", "unverified"
]
Authority = Literal[
    "official_exchange",
    "official_regulator",
    "issuer_filing",
    "official_registrar",
    "licensed_market_data",
    "credible_news",
    "unofficial",
]
RetrievalMethod = Literal["mock_fixture", "manual_import", "live_fetch"]
FieldValue = str | int | list[str]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class SourceRef(_Contract):
    """Citation for a value. Links to the original; the API never returns stored text."""

    evidence_id: UUID
    url: str
    title: str
    publisher: str
    published_at: date | None
    authority: Authority
    retrieval_method: RetrievalMethod
    is_synthetic: bool


class IpoField(_Contract):
    status: FieldStatus
    value: FieldValue | None
    checked_at: datetime | None
    source: SourceRef | None
    # Verbatim text from the source that contains the value (shown as a short excerpt).
    quote: str | None
    note: str | None


class FieldObservation(_Contract):
    """One source's claim about one field, including ones that lost or disagreed."""

    field: FieldName
    value: FieldValue | None
    raw_value: str
    quote: str
    quote_verified: bool
    parse_error: str | None
    observed_at: datetime
    source: SourceRef


class IpoSummary(_Contract):
    model_config = ConfigDict(title="IpoSummary")

    id: UUID
    slug: str
    company_name: str
    status: IpoStatus
    status_as_of: date
    snapshot_version: int
    snapshot_created_at: datetime
    is_synthetic: bool
    fields: dict[FieldName, IpoField]


class IpoDetail(IpoSummary):
    model_config = ConfigDict(title="IpoDetail")

    observations: list[FieldObservation]


class ExclusionNotice(_Contract):
    code: Literal["ENTITY_EXCLUDED"]
    message: str


class IpoList(_Contract):
    model_config = ConfigDict(title="IpoList")

    schema_version: Literal["ipo-list.v1"] = "ipo-list.v1"
    items: list[IpoSummary]
    next_cursor: str | None = Field(max_length=500)
    # Set when the search itself names an excluded entity (brief section 2).
    notice: ExclusionNotice | None
