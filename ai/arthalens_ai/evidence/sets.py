"""Evidence sets: stable, report-scoped labels d1, d2, ... (brief section 9).

A label, once assigned, never changes or moves to another document. Adding a document that
is already in the set returns its existing label. Labels are gap-free: assignment is
serialised by locking the set row.
"""

from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

Purpose = Literal["ipo_snapshot", "research_report", "test"]


class EvidenceSets:
    def __init__(self, conn: psycopg.AsyncConnection[Any], tenant_id: UUID | None = None) -> None:
        self._conn = conn
        self._tenant_id = tenant_id

    async def _scope(self, cur: psycopg.AsyncCursor[Any]) -> None:
        if self._tenant_id is not None:
            await cur.execute(
                "SELECT set_config('app.tenant_id', %s, true)", (str(self._tenant_id),)
            )

    async def create(self, purpose: Purpose) -> UUID:
        async with self._conn.transaction(), self._conn.cursor(row_factory=dict_row) as cur:
            await self._scope(cur)
            await cur.execute(
                "INSERT INTO evidence_sets (tenant_id, purpose) VALUES (%s, %s) RETURNING id",
                (self._tenant_id, purpose),
            )
            row = await cur.fetchone()
            if row is None:
                raise RuntimeError("evidence set was not created")
            return UUID(str(row["id"]))

    async def add(self, set_id: UUID, document_id: UUID) -> str:
        async with self._conn.transaction(), self._conn.cursor(row_factory=dict_row) as cur:
            await self._scope(cur)
            await cur.execute(
                "SELECT next_position FROM evidence_sets WHERE id = %s FOR UPDATE", (set_id,)
            )
            locked = await cur.fetchone()
            if locked is None:
                raise LookupError("evidence set not found or not visible")
            await cur.execute(
                "SELECT label FROM evidence_set_items WHERE set_id = %s AND document_id = %s",
                (set_id, document_id),
            )
            existing = await cur.fetchone()
            if existing:
                return str(existing["label"])
            position = int(locked["next_position"])
            await cur.execute(
                "INSERT INTO evidence_set_items (set_id, position, document_id)"
                " VALUES (%s, %s, %s) RETURNING label",
                (set_id, position, document_id),
            )
            await cur.execute(
                "UPDATE evidence_sets SET next_position = next_position + 1 WHERE id = %s",
                (set_id,),
            )
            return f"d{position}"
