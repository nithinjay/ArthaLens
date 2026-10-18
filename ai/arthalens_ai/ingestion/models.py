"""Import format shared by synthetic fixtures and manual imports (``arthalens.ipo-import.v1``).

An import names the company, lists source documents, and for each raw field gives the value,
which document it came from and a *verbatim quote* from that document. The pipeline verifies
the quote against the document text before anything is marked verified.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arthalens_ai.contracts.ipo import Authority, RetrievalMethod
from arthalens_ai.domain.resolve import RAW_FIELDS
from arthalens_ai.policy.exclusion import Identifiers

SourceType = Literal[
    "exchange_notice",
    "offer_document",
    "regulator_publication",
    "registrar_notice",
    "issuer_website",
    "news",
    "other",
]
MimeType = Literal["text/plain", "text/html", "application/pdf"]
DisplayRights = Literal["full_text", "excerpt", "metadata_only"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ImportDocument(_Strict):
    ref: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    url: str = Field(pattern=r"^https?://", max_length=2000)
    title: str = Field(min_length=1, max_length=500)
    publisher: str = Field(min_length=1, max_length=300)
    published_at: date | None = None
    authority: Authority
    source_type: SourceType
    mime_type: MimeType
    # Exactly one of: a local file next to the import, or a live fetch of ``url``.
    file: str | None = None
    fetch: bool = False
    display_rights: DisplayRights = "excerpt"

    @model_validator(mode="after")
    def _one_origin(self) -> Self:
        if (self.file is None) == (not self.fetch):
            raise ValueError(f"document {self.ref!r}: give exactly one of 'file' or 'fetch: true'")
        return self


class ImportObservation(_Strict):
    value: str = Field(min_length=1, max_length=1000)
    source: str
    quote: str = Field(min_length=1, max_length=1000)


class IpoImport(_Strict):
    schema_: Literal["arthalens.ipo-import.v1"] = Field(alias="schema")
    synthetic: bool
    company_name: str = Field(min_length=1, max_length=300)
    identifiers: Identifiers = Identifiers()
    documents: tuple[ImportDocument, ...] = Field(min_length=1)
    fields: dict[str, tuple[ImportObservation, ...]]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        refs = [d.ref for d in self.documents]
        if len(refs) != len(set(refs)):
            raise ValueError("document refs must be unique")
        unknown = set(self.fields) - set(RAW_FIELDS)
        if unknown:
            raise ValueError(f"unknown fields: {sorted(unknown)}")
        for name, observations in self.fields.items():
            for o in observations:
                if o.source not in refs:
                    raise ValueError(f"field {name!r} cites unknown document {o.source!r}")
        return self


class Candidate(_Strict):
    """An IPO a provider found, before any document is loaded."""

    provider: str
    origin: Path  # the import file; documents with ``file`` resolve relative to it
    data: IpoImport

    @property
    def name(self) -> str:
        return self.data.company_name

    @property
    def source_url(self) -> str:
        return self.data.documents[0].url


class LoadedDocument(_Strict):
    """A source document with its bytes hashed and text extracted."""

    ref: str
    spec: ImportDocument
    sha256: str
    byte_size: int
    text: str
    retrieved_at: datetime
    retrieval_method: RetrievalMethod
    provider: str
    is_synthetic: bool
