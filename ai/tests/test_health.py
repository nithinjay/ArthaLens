from fastapi.testclient import TestClient

from arthalens_ai.contracts.health import ServiceHealth
from arthalens_ai.main import create_app
from tests.conftest import FakeDbCheck, make_settings


def test_healthz_is_unauthenticated_and_ok(client: TestClient) -> None:
    res = client.get("/healthz")
    assert res.status_code == 200
    body = ServiceHealth.model_validate(res.json())
    assert body.service == "ai"
    assert body.status == "ok"
    assert body.checks == {}


def test_readyz_ok_when_database_up(client: TestClient) -> None:
    res = client.get("/readyz")
    assert res.status_code == 200
    body = ServiceHealth.model_validate(res.json())
    assert body.checks["database"].status == "ok"


def test_readyz_503_when_database_down(client: TestClient, db: FakeDbCheck) -> None:
    db.up = False
    res = client.get("/readyz")
    assert res.status_code == 503
    body = ServiceHealth.model_validate(res.json())
    assert body.status == "down"
    assert body.checks["database"].detail == "database unreachable"


def test_request_id_is_propagated(client: TestClient) -> None:
    res = client.get("/healthz", headers={"x-request-id": "abc12345-req"})
    assert res.headers["x-request-id"] == "abc12345-req"


def test_invalid_request_id_is_replaced(client: TestClient) -> None:
    res = client.get("/healthz", headers={"x-request-id": "bad id\nwith newline"})
    assert res.headers["x-request-id"] != "bad id\nwith newline"
    assert len(res.headers["x-request-id"]) == 36


def test_docs_disabled_in_production() -> None:
    app = create_app(make_settings(APP_ENV="production"), db_check=FakeDbCheck())
    client = TestClient(app)
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
