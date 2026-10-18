import pytest
from fastapi.testclient import TestClient

from arthalens_ai.config import Settings
from arthalens_ai.contracts.health import DependencyCheck
from arthalens_ai.main import create_app

TEST_TOKEN = "t" * 40  # synthetic test value, not a real secret


class FakeDbCheck:
    def __init__(self, up: bool = True) -> None:
        self.up = up

    async def __call__(self) -> DependencyCheck:
        if self.up:
            return DependencyCheck(status="ok", latency_ms=1)
        return DependencyCheck(status="down", detail="database unreachable")


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql://unused@localhost/unused",
        "AI_SERVICE_TOKEN": TEST_TOKEN,
    }
    values.update(overrides)
    return Settings.model_validate(values)


@pytest.fixture
def db() -> FakeDbCheck:
    return FakeDbCheck(up=True)


@pytest.fixture
def client(db: FakeDbCheck) -> TestClient:
    return TestClient(create_app(make_settings(), db_check=db))
