"""Configuration for ingestion jobs (CLI and, from Milestone 4, the worker)."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# SEBI allows linking without permission and requires permission to *reproduce* material
# (website policy, checked 2026-10-18). We fetch single public documents for private analysis,
# store hashes and short cited excerpts, and link to the original. See ADR-0015.
SEBI_DOMAINS = ("sebi.gov.in",)


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    database_url: SecretStr = Field(alias="DATABASE_URL")
    fixtures_dir: Path = Field(
        default=Path(__file__).resolve().parents[2] / "fixtures" / "ipos", alias="FIXTURES_DIR"
    )
    # Live fetching is off unless explicitly enabled (source-provider strategy, principle 4).
    sebi_fetch_enabled: bool = Field(default=False, alias="PROVIDER_SEBI_FETCH_ENABLED")
    log_level: str = Field(default="info", alias="LOG_LEVEL")
