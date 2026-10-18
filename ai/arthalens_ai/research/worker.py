"""Research worker: claims jobs and runs them (request lifecycle steps 2-9).

    python -m arthalens_ai.research.worker            # loop forever (the ai-worker service)
    python -m arthalens_ai.research.worker --once     # process at most one job, then exit

Per job: lease + heartbeat -> exclusion re-check (L4) -> pin the report's evidence set ->
load checkpointed sections -> run the ADK pipeline under a deadline -> finalise. Transient
failures are retried with backoff up to the job's max_attempts; saved sections are never
redone or duplicated.
"""

import argparse
import asyncio
import contextlib
import logging
import os
import random
import signal
import socket
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg_pool import AsyncConnectionPool
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from arthalens_ai.policy.exclusion import EntityRef, ExclusionPolicy, evaluate, load_policy
from arthalens_ai.research.agents import ExcludedDuringRun, ResearchDeps, TokenBudget, run_research
from arthalens_ai.research.catalog import CATALOG
from arthalens_ai.research.contracts import SectionResult
from arthalens_ai.research.model import FakeModelPort, GeminiModelPort, ModelPort
from arthalens_ai.research.store import ClaimedJob, ReportContext, ResearchStore

logger = logging.getLogger("arthalens.worker")

PIPELINE_VERSION = "m4.1"


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    environment: str = Field(default="development", alias="APP_ENV")
    database_url: SecretStr = Field(alias="DATABASE_URL")
    model_provider: str = Field(default="fake", alias="MODEL_PROVIDER")  # fake | gemini
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str | None = Field(default=None, alias="GEMINI_MODEL")
    # Optional USD prices per million tokens, for cost estimates. Unset: cost is not estimated.
    gemini_input_usd_per_mtok: float | None = Field(
        default=None, alias="GEMINI_INPUT_USD_PER_MTOK", ge=0
    )
    gemini_output_usd_per_mtok: float | None = Field(
        default=None, alias="GEMINI_OUTPUT_USD_PER_MTOK", ge=0
    )
    lease_s: int = Field(default=60, alias="RESEARCH_LEASE_SECONDS", ge=10)
    poll_s: float = Field(default=2.0, alias="RESEARCH_POLL_SECONDS", gt=0)
    job_deadline_s: float = Field(default=900.0, alias="RESEARCH_JOB_DEADLINE_SECONDS", gt=0)
    section_deadline_s: float = Field(
        default=180.0, alias="RESEARCH_SECTION_DEADLINE_SECONDS", gt=0
    )
    token_budget: int = Field(default=200_000, alias="RESEARCH_TOKEN_BUDGET", gt=0)
    log_level: str = Field(default="info", alias="LOG_LEVEL")

    @model_validator(mode="after")
    def _model_choice(self) -> "WorkerSettings":
        if self.model_provider not in ("fake", "gemini"):
            raise ValueError("MODEL_PROVIDER must be 'fake' or 'gemini'")
        if self.model_provider == "fake" and self.environment == "production":
            raise ValueError("the fake model is for development and tests only")
        if self.model_provider == "gemini" and not (self.gemini_api_key and self.gemini_model):
            raise ValueError("MODEL_PROVIDER=gemini needs GEMINI_API_KEY and GEMINI_MODEL")
        return self


def build_model(settings: WorkerSettings) -> ModelPort:
    if settings.model_provider == "gemini":
        assert settings.gemini_api_key and settings.gemini_model  # noqa: S101 - validated above
        prices = None
        if (
            settings.gemini_input_usd_per_mtok is not None
            and settings.gemini_output_usd_per_mtok is not None
        ):
            prices = (settings.gemini_input_usd_per_mtok, settings.gemini_output_usd_per_mtok)
        return GeminiModelPort(
            settings.gemini_api_key.get_secret_value(), settings.gemini_model, prices
        )
    return FakeModelPort()


@dataclass
class _Sink:
    store: ResearchStore
    ctx: ReportContext
    started: dict[str, datetime]

    async def event(self, type_: str, payload: dict[str, Any]) -> None:
        if type_ == "section.started":
            self.started[payload["section"]] = datetime.now(UTC)
        await self.store.event(self.ctx, type_, payload)

    async def save_section(self, result: SectionResult, attempt: int) -> None:
        started = self.started.get(result.section, datetime.now(UTC))
        await self.store.save_section(self.ctx, result, attempt, started)


def final_status(results: dict[str, SectionResult]) -> str:
    """'completed' only if every implemented section is ok; otherwise 'completed_degraded'.
    In Milestone 4 drafted sections are at most 'degraded', so reports are degraded."""
    implemented = [r for s, r in results.items() if CATALOG[s].kind != "planned"]  # type: ignore[index]
    return (
        "completed"
        if implemented and all(r.status == "ok" for r in implemented)
        else "completed_degraded"
    )


class Worker:
    def __init__(
        self,
        store: ResearchStore,
        model: ModelPort,
        policy: ExclusionPolicy,
        settings: WorkerSettings,
        worker_id: str | None = None,
    ) -> None:
        self.store = store
        self.model = model
        self.policy = policy
        self.settings = settings
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        logger.info("worker %s started (model=%s)", self.worker_id, self.model.model)
        while not self._stop.is_set():
            if not await self.run_once():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), self.settings.poll_s)

    async def run_once(self) -> bool:
        job = await self.store.claim(self.worker_id, self.settings.lease_s)
        if job is None:
            return False
        heartbeat = asyncio.create_task(self._heartbeat(job))
        try:
            await self.process(job)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
        return True

    async def _heartbeat(self, job: ClaimedJob) -> None:
        while True:
            await asyncio.sleep(self.settings.lease_s / 3)
            if not await self.store.renew_lease(job, self.worker_id, self.settings.lease_s):
                logger.warning("lost the lease on job %s", job.job_id)
                return

    async def process(self, job: ClaimedJob) -> None:
        ctx = await self.store.load_report(job)
        verdict = evaluate(self.policy, EntityRef(name=ctx.company_name))
        if verdict.blocked or ctx.ipo_exclusion_status != "allowed":
            await self._reject_excluded(job, ctx, verdict.rule_id)
            return
        if ctx.started_at is None:
            await self.store.set_report(ctx, status="running", started_at=datetime.now(UTC))
        await self.store.event(
            ctx, "job.started", {"attempt": job.attempt, "model": self.model.model}
        )
        try:
            async with asyncio.timeout(self.settings.job_deadline_s):
                results = await self._run(job, ctx)
        except ExcludedDuringRun:
            await self._reject_excluded(job, ctx, None)
            return
        except Exception as exc:
            await self._failed_attempt(job, ctx, exc)
            return
        status = final_status(results)
        await self.store.set_report(ctx, status=status, completed_at=datetime.now(UTC))
        await self.store.event(ctx, "job.completed", {"status": status})
        await self.store.finish_job(job, self.worker_id, "succeeded", None)
        logger.info("report %s %s", ctx.report_id, status)

    async def _run(self, job: ClaimedJob, ctx: ReportContext) -> dict[str, SectionResult]:
        set_id = await self.store.ensure_evidence_set(ctx)
        passages = await self.store.load_passages(ctx, set_id)
        fields = await self.store.load_snapshot_fields(ctx, set_id)
        done = await self.store.load_done_sections(ctx)
        documents = len({p.label for p in passages})
        await self.store.event(
            ctx, "evidence.ready", {"documents": documents, "resumed_sections": sorted(done)}
        )
        deps = ResearchDeps(
            report_id=ctx.report_id,
            company_name=ctx.company_name,
            attempt=job.attempt,
            policy=self.policy,
            model=self.model,
            sink=_Sink(self.store, ctx, {}),
            budget=TokenBudget(self.settings.token_budget),
            passages=passages,
            snapshot_fields=fields,
            section_timeout_s=self.settings.section_deadline_s,
            done=done,
        )
        return await run_research(deps)  # type: ignore[return-value]

    async def _reject_excluded(
        self, job: ClaimedJob, ctx: ReportContext, rule_id: str | None
    ) -> None:
        await self.store.set_report(
            ctx,
            status="rejected_excluded",
            completed_at=datetime.now(UTC),
            error="Excluded by product policy",
        )
        await self.store.event(ctx, "job.rejected", {"code": "ENTITY_EXCLUDED", "rule_id": rule_id})
        await self.store.finish_job(job, self.worker_id, "rejected_excluded", "excluded by policy")

    async def _failed_attempt(self, job: ClaimedJob, ctx: ReportContext, exc: Exception) -> None:
        error = f"{type(exc).__name__}: {exc}"[:1000]
        logger.warning("job %s attempt %d failed: %s", job.job_id, job.attempt, type(exc).__name__)
        max_attempts = 3
        if job.attempt < max_attempts:
            delay = int(5 * 2 ** (job.attempt - 1) * (1 + random.random()))  # noqa: S311
            await self.store.event(
                ctx, "job.retrying", {"attempt": job.attempt, "in_seconds": delay}
            )
            await self.store.retry_later(job, self.worker_id, delay, error)
        else:
            await self.store.set_report(
                ctx,
                status="failed",
                completed_at=datetime.now(UTC),
                error="The research job failed after repeated attempts.",
            )
            await self.store.event(ctx, "job.failed", {"attempts": job.attempt})
            await self.store.finish_job(job, self.worker_id, "failed", error)


async def _main(once: bool) -> int:
    settings = WorkerSettings()  # values come from the environment
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(levelname)s %(name)s %(message)s"
    )
    pool = AsyncConnectionPool(
        settings.database_url.get_secret_value(),
        min_size=1,
        max_size=12,
        kwargs={"autocommit": True},
        open=False,
    )
    await pool.open()
    try:
        worker = Worker(ResearchStore(pool), build_model(settings), load_policy(), settings)
        if once:
            await worker.run_once()
            return 0
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, worker.stop)
        await worker.run_forever()
        return 0
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="arthalens-worker")
    parser.add_argument("--once", action="store_true", help="process at most one job and exit")
    sys.exit(asyncio.run(_main(parser.parse_args().once)))


if __name__ == "__main__":
    main()


__all__ = ["UUID", "Worker", "WorkerSettings", "final_status", "main"]
