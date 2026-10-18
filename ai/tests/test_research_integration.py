"""Research worker against a real, migrated PostgreSQL (AC-4.1 to AC-4.3).

Run with scripts/test-integration.sh (throwaway database). Skipped when the URLs aren't set.
"""

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from arthalens_ai.ingestion.pipeline import IngestionPipeline
from arthalens_ai.ingestion.providers.files import FileImportProvider
from arthalens_ai.ingestion.repository import PostgresIngestionRepository
from arthalens_ai.ingestion.searchport import SearchPort
from arthalens_ai.policy.exclusion import load_policy
from arthalens_ai.research.contracts import SectionResult
from arthalens_ai.research.model import FakeModelPort
from arthalens_ai.research.store import ClaimedJob, LeaseLost, ReportContext, ResearchStore
from arthalens_ai.research.worker import Worker, WorkerSettings

AI_URL = os.environ.get("TEST_DB_AI_URL")
API_URL = os.environ.get("TEST_DB_API_URL")
ADMIN_URL = os.environ.get("TEST_DB_ADMIN_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (AI_URL and API_URL and ADMIN_URL), reason="no test database"),
]

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ipos"
Conn = psycopg.AsyncConnection[Any]


def settings() -> WorkerSettings:
    return WorkerSettings.model_validate(
        {"DATABASE_URL": str(AI_URL), "RESEARCH_LEASE_SECONDS": 30, "APP_ENV": "test"}
    )


def run(test: Callable[[AsyncConnectionPool[Any], Conn, Conn], Awaitable[None]]) -> None:
    async def main() -> None:
        pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
            str(AI_URL), min_size=1, max_size=12, kwargs={"autocommit": True}, open=False
        )
        await pool.open()
        api = await psycopg.AsyncConnection.connect(str(API_URL), autocommit=True)
        admin = await psycopg.AsyncConnection.connect(str(ADMIN_URL), autocommit=True)
        try:
            await test(pool, api, admin)
        finally:
            await pool.close()
            await api.close()
            await admin.close()

    asyncio.run(main())


@pytest.fixture(scope="module", autouse=True)
def ingested() -> None:
    async def main() -> None:
        repo = await PostgresIngestionRepository.connect(str(AI_URL))
        try:
            provider = FileImportProvider.fixtures(FIXTURES)
            policy = load_policy()
            await IngestionPipeline(SearchPort({"fixtures": provider}, policy), repo, policy).run(
                "fixtures"
            )
        finally:
            await repo.close()

    asyncio.run(main())


async def one(conn: Conn, sql: str, *params: Any) -> Any:
    cur = await conn.execute(sql, params)
    row = await cur.fetchone()
    return row[0] if row else None


async def rows(conn: Conn, sql: str, *params: Any) -> list[dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return await cur.fetchall()


async def tenant_and_user(admin: Conn) -> tuple[UUID, UUID]:
    tenant = await one(
        admin,
        "INSERT INTO tenants (name, kind) VALUES ('SYNTHETIC research tenant', 'personal') RETURNING id",
    )
    user = await one(
        admin,
        "INSERT INTO users (email) VALUES ('it-' || gen_random_uuid() || '@example.test') RETURNING id",
    )
    return tenant, user


async def ipo(admin: Conn, name: str) -> tuple[UUID, UUID]:
    found = await rows(
        admin, "SELECT id, current_snapshot_id FROM ipos WHERE company_name = %s", name
    )
    return found[0]["id"], found[0]["current_snapshot_id"]


async def create_report(
    api: Conn, tenant: UUID, user: UUID, ipo_id: UUID, snapshot_id: UUID
) -> UUID:
    """What backend/ does on POST /ipos/{id}/research: report + job + first event, one tx."""
    async with api.transaction():
        await api.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
        report = await one(
            api,
            "INSERT INTO research_reports (tenant_id, owner_user_id, ipo_id, snapshot_id, pipeline_version)"
            " VALUES (%s, %s, %s, %s, 'test') RETURNING id",
            tenant,
            user,
            ipo_id,
            snapshot_id,
        )
        await api.execute(
            "INSERT INTO research_jobs (report_id, tenant_id) VALUES (%s, %s)", (report, tenant)
        )
        await api.execute(
            "INSERT INTO research_events (report_id, tenant_id, seq, type, payload) VALUES (%s, %s, 1, 'job.queued', '{}')",
            (report, tenant),
        )
    return UUID(str(report))


def worker(
    pool: AsyncConnectionPool[Any], store: ResearchStore | None = None, name: str = "w1"
) -> Worker:
    return Worker(
        store or ResearchStore(pool), FakeModelPort(), load_policy(), settings(), worker_id=name
    )


async def drain(w: Worker) -> int:
    n = 0
    while await w.run_once():
        n += 1
    return n


async def report_shape(admin: Conn, report: UUID) -> list[Any]:
    sections = await rows(
        admin,
        "SELECT section, status, validation FROM research_sections WHERE report_id = %s ORDER BY section",
        report,
    )
    claims = await rows(
        admin,
        "SELECT c.section, c.position, c.text, c.status, cc.label, cc.page FROM evidence_claims c"
        " LEFT JOIN claim_citations cc ON cc.claim_id = c.id WHERE c.report_id = %s ORDER BY 1, 2, 5",
        report,
    )
    return [[tuple(s.values()) for s in sections], [tuple(c.values()) for c in claims]]


# --- AC-4.1: a full run --------------------------------------------------------------------


def test_full_run_produces_every_section_with_honest_states() -> None:
    async def t(pool: AsyncConnectionPool[Any], api: Conn, admin: Conn) -> None:
        tenant, user = await tenant_and_user(admin)
        ipo_id, snap = await ipo(admin, "Synthetic Alpha Foods Limited")
        report = await create_report(api, tenant, user, ipo_id, snap)
        await drain(worker(pool))

        r = (
            await rows(
                admin,
                "SELECT status, evidence_set_id, started_at, completed_at FROM research_reports WHERE id = %s",
                report,
            )
        )[0]
        assert r["status"] == "completed_degraded" and r["completed_at"] >= r["started_at"]
        sections = {
            s["section"]: s
            for s in await rows(
                admin, "SELECT * FROM research_sections WHERE report_id = %s", report
            )
        }
        assert set(sections) == set("ABCDEFGHIJ")
        assert sections["D"]["status"] == "ok" and sections["D"]["validation"] == "deterministic"
        for s in "AEF":
            assert sections[s]["status"] == "degraded" and sections[s]["validation"] == "pending"
            assert sections[s]["model"] == "fake-deterministic"
        for s in "BCGHI":
            assert sections[s]["status"] == "unavailable" and sections[s]["reason"]

        # No drafted claim is verified; every citation points into the report's own evidence set.
        assert (
            await one(
                admin,
                "SELECT count(*) FROM evidence_claims WHERE report_id = %s AND section <> 'D' AND status = 'verified'",
                report,
            )
            == 0
        )
        stray = await one(
            admin,
            "SELECT count(*) FROM claim_citations cc JOIN evidence_claims c ON c.id = cc.claim_id"
            " WHERE c.report_id = %s AND NOT EXISTS (SELECT 1 FROM evidence_set_items i"
            " WHERE i.set_id = %s AND i.label = cc.label AND i.document_id = cc.document_id)",
            report,
            r["evidence_set_id"],
        )
        assert stray == 0
        assert (
            await one(
                admin,
                "SELECT count(*) FROM evidence_claims WHERE report_id = %s AND section = 'A'",
                report,
            )
            > 0
        )

        events = await rows(
            admin, "SELECT seq, type FROM research_events WHERE report_id = %s ORDER BY seq", report
        )
        assert [e["seq"] for e in events] == list(range(1, len(events) + 1))  # gap-free
        assert events[0]["type"] == "job.queued" and events[-1]["type"] == "job.completed"
        assert sum(e["type"] == "section.completed" for e in events) == 10

        usage = await rows(
            admin,
            "SELECT section, outcome FROM usage_records WHERE report_id = %s ORDER BY section",
            report,
        )
        assert [u["section"] for u in usage] == ["A", "E", "F", "J"] and {
            u["outcome"] for u in usage
        } == {"ok"}
        assert (
            await one(admin, "SELECT status FROM research_jobs WHERE report_id = %s", report)
            == "succeeded"
        )

    run(t)


def test_two_runs_of_the_same_ipo_are_identical() -> None:
    async def t(pool: AsyncConnectionPool[Any], api: Conn, admin: Conn) -> None:
        tenant, user = await tenant_and_user(admin)
        ipo_id, snap = await ipo(admin, "Synthetic Alpha Foods Limited")
        a = await create_report(api, tenant, user, ipo_id, snap)
        b = await create_report(api, tenant, user, ipo_id, snap)
        await drain(worker(pool))
        assert await report_shape(admin, a) == await report_shape(admin, b)

    run(t)


# --- AC-4.3: crash, resume, leases ----------------------------------------------------------


class CrashingStore(ResearchStore):
    """Fails like a dying worker when it reaches the given section."""

    def __init__(self, pool: AsyncConnectionPool[Any], crash_on: str) -> None:
        super().__init__(pool)
        self.crash_on = crash_on

    async def save_section(
        self, ctx: ReportContext, result: SectionResult, attempt: int, started: Any
    ) -> bool:
        if result.section == self.crash_on:
            raise RuntimeError("simulated crash")
        return await super().save_section(ctx, result, attempt, started)


async def crash_then_resume(
    pool: AsyncConnectionPool[Any], api: Conn, admin: Conn, crash_on: str
) -> tuple[UUID, int]:
    tenant, user = await tenant_and_user(admin)
    ipo_id, snap = await ipo(admin, "Synthetic Beta Logistics Limited")
    report = await create_report(api, tenant, user, ipo_id, snap)
    await worker(pool, CrashingStore(pool, crash_on)).run_once()
    saved_first = int(
        await one(admin, "SELECT count(*) FROM research_sections WHERE report_id = %s", report)
    )
    job = (
        await rows(
            admin,
            "SELECT status, attempt, last_error FROM research_jobs WHERE report_id = %s",
            report,
        )
    )[0]
    assert (job["status"], job["attempt"]) == ("queued", 1) and "simulated crash" in job[
        "last_error"
    ]

    await admin.execute(
        "UPDATE research_jobs SET next_run_at = now() WHERE report_id = %s", (report,)
    )
    await drain(worker(pool, name="w2"))

    assert (
        await one(admin, "SELECT count(*) FROM research_sections WHERE report_id = %s", report)
        == 10
    )
    dupes = await one(
        admin,
        "SELECT count(*) - count(DISTINCT (section, position)) FROM evidence_claims WHERE report_id = %s",
        report,
    )
    assert dupes == 0
    assert (
        await one(admin, "SELECT status FROM research_reports WHERE id = %s", report)
        == "completed_degraded"
    )
    types = [
        e["type"]
        for e in await rows(
            admin, "SELECT type FROM research_events WHERE report_id = %s ORDER BY seq", report
        )
    ]
    assert "job.retrying" in types and types[-1] == "job.completed"
    seqs = [
        e["seq"]
        for e in await rows(
            admin, "SELECT seq FROM research_events WHERE report_id = %s ORDER BY seq", report
        )
    ]
    assert seqs == list(range(1, len(seqs) + 1))
    return report, saved_first


def test_crash_in_the_summary_resumes_with_only_the_summary() -> None:
    async def t(pool: AsyncConnectionPool[Any], api: Conn, admin: Conn) -> None:
        report, saved_first = await crash_then_resume(pool, api, admin, crash_on="J")
        assert saved_first == 9  # A-I committed before J crashed
        attempts = {
            r["section"]: r["attempt"]
            for r in await rows(
                admin, "SELECT section, attempt FROM research_sections WHERE report_id = %s", report
            )
        }
        assert attempts == {**{s: 1 for s in "ABCDEFGHI"}, "J": 2}  # only J was redone

    run(t)


def test_crash_during_parallel_sections_keeps_what_committed_and_duplicates_nothing() -> None:
    async def t(pool: AsyncConnectionPool[Any], api: Conn, admin: Conn) -> None:
        # Sibling saves in flight may be cancelled and rolled back with the crash; whatever did
        # commit must be kept as attempt 1 and never redone.
        report, saved_first = await crash_then_resume(pool, api, admin, crash_on="E")
        attempts = [
            r["attempt"]
            for r in await rows(
                admin, "SELECT attempt FROM research_sections WHERE report_id = %s", report
            )
        ]
        assert attempts.count(1) == saved_first and attempts.count(2) == 10 - saved_first

    run(t)


def test_expired_lease_is_reclaimed_and_concurrent_claims_never_share_a_job() -> None:
    async def t(pool: AsyncConnectionPool[Any], api: Conn, admin: Conn) -> None:
        await drain(worker(pool))  # clear anything left by other tests
        tenant, user = await tenant_and_user(admin)
        ipo_id, snap = await ipo(admin, "Synthetic Epsilon Power Limited")
        report = await create_report(api, tenant, user, ipo_id, snap)

        store = ResearchStore(pool)
        claims = await asyncio.gather(*(store.claim(f"racer{i}", 30) for i in range(5)))
        winners = [c for c in claims if c is not None]
        assert len(winners) == 1  # SKIP LOCKED: exactly one worker gets it

        # The winner "dies": its lease expires and another worker takes over.
        await admin.execute(
            "UPDATE research_jobs SET lease_expires_at = now() - interval '1 second' WHERE report_id = %s",
            (report,),
        )
        reclaimed: ClaimedJob | None = await store.claim("rescuer", 30)
        assert reclaimed is not None and reclaimed.attempt == 2 and reclaimed.report_id == report
        await worker(pool, name="rescuer").process(reclaimed)
        assert (
            await one(admin, "SELECT status FROM research_reports WHERE id = %s", report)
            == "completed_degraded"
        )

    run(t)


def test_jobs_out_of_attempts_are_failed_not_left_running() -> None:
    async def t(pool: AsyncConnectionPool[Any], api: Conn, admin: Conn) -> None:
        await drain(worker(pool))
        tenant, user = await tenant_and_user(admin)
        ipo_id, snap = await ipo(admin, "Synthetic Alpha Foods Limited")
        report = await create_report(api, tenant, user, ipo_id, snap)
        await admin.execute(
            "UPDATE research_jobs SET status = 'running', attempt = max_attempts, lease_owner = 'ghost',"
            " lease_expires_at = now() - interval '1 second' WHERE report_id = %s",
            (report,),
        )
        assert await ResearchStore(pool).claim("w", 30) is None
        assert (
            await one(admin, "SELECT status FROM research_jobs WHERE report_id = %s", report)
            == "failed"
        )

    run(t)


# --- exclusion and isolation ----------------------------------------------------------------


def test_policy_withdrawal_before_the_run_rejects_the_job() -> None:
    async def t(pool: AsyncConnectionPool[Any], api: Conn, admin: Conn) -> None:
        await drain(worker(pool))
        tenant, user = await tenant_and_user(admin)
        ipo_id, snap = await ipo(admin, "Synthetic Gamma Textiles Limited")
        report = await create_report(api, tenant, user, ipo_id, snap)
        await admin.execute(
            "UPDATE ipos SET exclusion_status = 'withdrawn_by_policy' WHERE id = %s", (ipo_id,)
        )
        try:
            await drain(worker(pool))
            assert (
                await one(admin, "SELECT status FROM research_reports WHERE id = %s", report)
                == "rejected_excluded"
            )
            assert (
                await one(
                    admin, "SELECT count(*) FROM research_sections WHERE report_id = %s", report
                )
                == 0
            )
            last = await one(
                admin,
                "SELECT type FROM research_events WHERE report_id = %s ORDER BY seq DESC LIMIT 1",
                report,
            )
            assert last == "job.rejected"
            # Layer L2: no new report can be created for it at all.
            with pytest.raises(psycopg.Error, match="ENTITY_EXCLUDED"):
                await create_report(api, tenant, user, ipo_id, snap)
        finally:
            await admin.execute(
                "UPDATE ipos SET exclusion_status = 'allowed' WHERE id = %s", (ipo_id,)
            )

    run(t)


def test_reports_are_invisible_to_other_tenants() -> None:
    async def t(pool: AsyncConnectionPool[Any], api: Conn, admin: Conn) -> None:
        await drain(worker(pool))
        tenant_a, user_a = await tenant_and_user(admin)
        tenant_b, _ = await tenant_and_user(admin)
        ipo_id, snap = await ipo(admin, "Synthetic Alpha Foods Limited")
        report = await create_report(api, tenant_a, user_a, ipo_id, snap)
        await drain(worker(pool))
        for table in (
            "research_reports",
            "research_sections",
            "evidence_claims",
            "research_events",
            "usage_records",
        ):
            column = "id" if table == "research_reports" else "report_id"
            for tenant in ("", str(tenant_b)):
                async with api.transaction():
                    await api.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
                    n = await one(api, f"SELECT count(*) FROM {table} WHERE {column} = %s", report)  # noqa: S608
                assert n == 0, (table, tenant)
        # And tenant B can't write into tenant A's report.
        async with api.transaction():
            await api.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_b),))
            with pytest.raises(psycopg.Error):
                await api.execute(
                    "INSERT INTO research_events (report_id, tenant_id, seq, type) VALUES (%s, %s, 999, 'x.y')",
                    (report, tenant_a),
                )

    run(t)


# --- review findings on PR #4 ---------------------------------------------------------------


async def last_event(admin: Conn, report: UUID) -> str:
    return str(
        await one(
            admin,
            "SELECT type FROM research_events WHERE report_id = %s ORDER BY seq DESC LIMIT 1",
            report,
        )
    )


def test_sweeper_fails_the_report_and_writes_the_terminal_event() -> None:
    async def t(pool: AsyncConnectionPool[Any], api: Conn, admin: Conn) -> None:
        await drain(worker(pool))
        tenant, user = await tenant_and_user(admin)
        ipo_id, snap = await ipo(admin, "Synthetic Alpha Foods Limited")
        report = await create_report(api, tenant, user, ipo_id, snap)
        await admin.execute(
            "UPDATE research_reports SET status = 'running', started_at = now() WHERE id = %s",
            (report,),
        )
        await admin.execute(
            "UPDATE research_jobs SET status = 'running', attempt = max_attempts, lease_owner = 'ghost',"
            " lease_expires_at = now() - interval '1 second' WHERE report_id = %s",
            (report,),
        )
        await ResearchStore(pool).claim("w", 30)  # runs the sweeper first
        r = (
            await rows(
                admin, "SELECT status, completed_at FROM research_reports WHERE id = %s", report
            )
        )[0]
        assert r["status"] == "failed" and r["completed_at"] is not None
        assert await last_event(admin, report) == "job.failed"

    run(t)


def test_the_jobs_own_attempt_limit_is_used() -> None:
    async def t(pool: AsyncConnectionPool[Any], api: Conn, admin: Conn) -> None:
        await drain(worker(pool))
        tenant, user = await tenant_and_user(admin)
        ipo_id, snap = await ipo(admin, "Synthetic Beta Logistics Limited")
        report = await create_report(api, tenant, user, ipo_id, snap)
        await admin.execute(
            "UPDATE research_jobs SET max_attempts = 1 WHERE report_id = %s", (report,)
        )
        await worker(pool, CrashingStore(pool, "J")).run_once()
        job = (await rows(admin, "SELECT status FROM research_jobs WHERE report_id = %s", report))[
            0
        ]
        assert job["status"] == "failed"  # not stranded as 'queued'
        assert (
            await one(admin, "SELECT status FROM research_reports WHERE id = %s", report)
            == "failed"
        )
        assert await last_event(admin, report) == "job.failed"

    run(t)


def test_a_worker_that_lost_its_lease_can_no_longer_write() -> None:
    async def t(pool: AsyncConnectionPool[Any], api: Conn, admin: Conn) -> None:
        await drain(worker(pool))
        tenant, user = await tenant_and_user(admin)
        ipo_id, snap = await ipo(admin, "Synthetic Alpha Foods Limited")
        report = await create_report(api, tenant, user, ipo_id, snap)
        store = ResearchStore(pool)
        job_a = await store.claim("worker-a", 30)
        assert job_a is not None
        ctx_a = await store.load_report(job_a, "worker-a")
        await admin.execute(
            "UPDATE research_jobs SET lease_expires_at = now() - interval '1 second' WHERE report_id = %s",
            (report,),
        )
        job_b = await store.claim("worker-b", 30)
        assert job_b is not None and job_b.attempt == 2
        before = await one(
            admin, "SELECT count(*) FROM research_events WHERE report_id = %s", report
        )
        with pytest.raises(LeaseLost):
            await store.event(ctx_a, "section.started", {"section": "A"})
        with pytest.raises(LeaseLost):
            await store.set_report(ctx_a, status="failed")
        with pytest.raises(LeaseLost):
            await store.save_section(
                ctx_a,
                SectionResult("B", "unavailable", "deterministic", "x"),
                1,
                datetime.now(UTC),
            )
        assert (
            await one(admin, "SELECT count(*) FROM research_events WHERE report_id = %s", report)
            == before
        )
        assert (
            await one(admin, "SELECT count(*) FROM research_sections WHERE report_id = %s", report)
            == 0
        )
        # Worker B, the rightful owner, finishes normally.
        await worker(pool, name="worker-b").process(job_b)
        assert (
            await one(admin, "SELECT status FROM research_reports WHERE id = %s", report)
            == "completed_degraded"
        )

    run(t)


def test_a_deleted_report_is_cancelled_without_running() -> None:
    async def t(pool: AsyncConnectionPool[Any], api: Conn, admin: Conn) -> None:
        await drain(worker(pool))
        tenant, user = await tenant_and_user(admin)
        ipo_id, snap = await ipo(admin, "Synthetic Alpha Foods Limited")
        report = await create_report(api, tenant, user, ipo_id, snap)
        await admin.execute(
            "UPDATE research_reports SET deleted_at = now() WHERE id = %s", (report,)
        )
        await drain(worker(pool))
        assert (
            await one(admin, "SELECT status FROM research_jobs WHERE report_id = %s", report)
            == "cancelled"
        )
        assert (
            await one(admin, "SELECT count(*) FROM research_sections WHERE report_id = %s", report)
            == 0
        )
        assert (
            await one(admin, "SELECT count(*) FROM usage_records WHERE report_id = %s", report) == 0
        )
        assert await last_event(admin, report) == "job.cancelled"

    run(t)
