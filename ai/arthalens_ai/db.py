"""Database connectivity check.

Connection pooling and repositories arrive with the first tables this service owns (Milestone 2).
"""

import asyncio
import logging
import math
import time
from typing import Protocol

import psycopg

from arthalens_ai.contracts.health import DependencyCheck

logger = logging.getLogger(__name__)


class DbCheck(Protocol):
    async def __call__(self) -> DependencyCheck: ...


class PostgresCheck:
    def __init__(self, dsn: str, timeout_s: float) -> None:
        self._dsn = dsn
        self._timeout_s = timeout_s

    async def __call__(self) -> DependencyCheck:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self._timeout_s):
                conn = await psycopg.AsyncConnection.connect(
                    self._dsn, connect_timeout=max(1, math.ceil(self._timeout_s))
                )
                async with conn:
                    await conn.execute("SELECT 1")
        except (TimeoutError, psycopg.Error, OSError) as exc:
            # Log the error class only: driver messages can include host names.
            logger.warning("database check failed: %s", type(exc).__name__)
            return DependencyCheck(status="down", detail="database unreachable")
        return DependencyCheck(status="ok", latency_ms=_elapsed_ms(started))


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
