"""Runtime configuration, read from environment variables.

Secrets are held as ``SecretStr`` so they never appear in ``repr()``, logs or tracebacks.
"""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SERVICE_TOKEN_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    environment: Literal["development", "test", "production"] = Field(
        default="development", alias="APP_ENV"
    )
    database_url: SecretStr = Field(alias="DATABASE_URL")
    service_token: SecretStr = Field(alias="AI_SERVICE_TOKEN")
    log_level: str = Field(default="info", alias="LOG_LEVEL")
    db_check_timeout_s: float = Field(default=2.0, gt=0, le=30)

    @field_validator("service_token")
    @classmethod
    def _service_token_strength(cls, value: SecretStr) -> SecretStr:
        token = value.get_secret_value()
        if len(token) < MIN_SERVICE_TOKEN_LENGTH:
            raise ValueError(f"AI_SERVICE_TOKEN must be at least {MIN_SERVICE_TOKEN_LENGTH} chars")
        if token.startswith("change-me"):
            raise ValueError("AI_SERVICE_TOKEN is still the .env.example placeholder")
        return value
