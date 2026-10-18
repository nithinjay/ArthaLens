import asyncio
import logging

import pytest

from arthalens_ai.db import PostgresCheck


def test_unreachable_database_reports_down_without_leaking_dsn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Port 1 on loopback is closed, so the connection fails fast.
    dsn = "postgresql://app_ai:supersecret@127.0.0.1:1/arthalens"
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(PostgresCheck(dsn, timeout_s=2)())
    assert result.status == "down"
    assert result.detail == "database unreachable"
    assert "supersecret" not in caplog.text
    assert "127.0.0.1" not in caplog.text
