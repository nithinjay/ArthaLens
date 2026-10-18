import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_TOKEN

URL = "/internal/v1/health"


def test_internal_health_accepts_valid_token(client: TestClient) -> None:
    res = client.get(URL, headers={"Authorization": f"Bearer {TEST_TOKEN}"})
    assert res.status_code == 200
    assert res.json()["service"] == "ai"


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        f"Basic {TEST_TOKEN}",
        "Bearer wrong-token",
        f"Bearer {TEST_TOKEN}x",
        f"Bearer {TEST_TOKEN[:-1]}",
    ],
)
def test_internal_health_rejects_bad_tokens(client: TestClient, header: str | None) -> None:
    headers = {} if header is None else {"Authorization": header}
    res = client.get(URL, headers=headers)
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == "Bearer"
    # The response must never echo the expected token.
    assert TEST_TOKEN not in res.text
