import pytest
from pydantic import ValidationError

from tests.conftest import TEST_TOKEN, make_settings


def test_rejects_short_service_token() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        make_settings(AI_SERVICE_TOKEN="short")


def test_rejects_placeholder_service_token() -> None:
    with pytest.raises(ValidationError, match="placeholder"):
        make_settings(AI_SERVICE_TOKEN="change-me-to-a-random-value-of-at-least-32-chars")


def test_secrets_hidden_from_repr() -> None:
    settings = make_settings(DATABASE_URL="postgresql://app_ai:supersecret@db/arthalens")
    text = repr(settings) + str(settings)
    assert "supersecret" not in text
    assert TEST_TOKEN not in text
