"""Ingestion pipeline: discover -> exclusion check -> load -> resolve -> derive status -> snapshot.

Each IPO is processed independently: one bad source marks the run ``partial`` instead of
stopping it, and every failure is counted and recorded on the run.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal, Protocol
from uuid import UUID

from arthalens_ai.contracts.ipo import IpoStatus
from arthalens_ai.domain.resolve import EvidenceDoc, RawObservation, Resolution, resolve_all
from arthalens_ai.domain.status import derive_status, ist_today
from arthalens_ai.ingestion.models import Candidate, LoadedDocument
from arthalens_ai.ingestion.searchport import Blocked, SearchPort
from arthalens_ai.policy.exclusion import ExclusionPolicy, normalize_name

logger = logging.getLogger(__name__)

RunStatus = Literal["succeeded", "partial", "failed"]


@dataclass(frozen=True)
class SnapshotDraft:
    company_name: str
    normalized_name: str
    is_synthetic: bool
    policy_version: int
    documents: tuple[LoadedDocument, ...]
    resolution: Resolution
    status: IpoStatus
    status_as_of: date
    fingerprint: str
    checked_at: datetime


@dataclass(frozen=True)
class SaveOutcome:
    ipo_id: UUID
    version: int
    created: bool  # False when the content was unchanged and no snapshot was written


class IngestionRepository(Protocol):
    async def start_run(self, provider: str) -> UUID: ...

    async def finish_run(
        self, run_id: UUID, status: RunStatus, counts: dict[str, int], error: str | None
    ) -> None: ...

    async def record_quarantine(self, run_id: UUID, blocked: Blocked) -> None: ...

    async def save_snapshot(self, run_id: UUID, draft: SnapshotDraft) -> SaveOutcome: ...

    async def reconcile_policy(self, policy: ExclusionPolicy) -> int: ...


@dataclass
class RunReport:
    run_id: UUID
    status: RunStatus
    counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def build_observations(candidate: Candidate, docs: list[LoadedDocument]) -> list[RawObservation]:
    by_ref = {
        d.ref: EvidenceDoc(
            key=d.ref,
            authority=d.spec.authority,
            published_at=d.spec.published_at,
            text=d.text,
            pages=d.extraction.page_texts(),
        )
        for d in docs
    }
    return [
        RawObservation(raw_field=name, raw_value=o.value, quote=o.quote, doc=by_ref[o.source])
        for name, observations in candidate.data.fields.items()
        for o in observations
    ]


def fingerprint(resolution: Resolution, status: IpoStatus, docs: list[LoadedDocument]) -> str:
    """Stable hash of everything a snapshot shows. Same inputs -> same hash -> no new version."""
    sha_by_ref = {d.ref: d.sha256 for d in docs}
    payload = {
        "status": status,
        "fields": {
            name: [
                f.status,
                f.value,
                sha_by_ref[f.winner.doc.key] if f.winner else None,
                f.winner.quote if f.winner else None,
                f.winner.page if f.winner else None,
                f.note,
            ]
            for name, f in sorted(resolution.fields.items())
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class IngestionPipeline:
    def __init__(
        self,
        port: SearchPort,
        repo: IngestionRepository,
        policy: ExclusionPolicy,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._port = port
        self._repo = repo
        self._policy = policy
        self._clock = clock

    async def run(self, provider: str) -> RunReport:
        run_id = await self._repo.start_run(provider)
        report = RunReport(run_id=run_id, status="succeeded")
        counts = report.counts
        for key in ("discovered", "quarantined", "created", "unchanged", "failed", "withdrawn"):
            counts[key] = 0

        try:
            discovery = self._port.discover(provider)
        except Exception as exc:
            report.status = "failed"
            report.errors.append(f"discovery failed: {type(exc).__name__}: {exc}"[:500])
            await self._repo.finish_run(run_id, "failed", counts, report.errors[0])
            return report

        counts["discovered"] = len(discovery.allowed) + len(discovery.blocked)
        for blocked in discovery.blocked:
            # Name and source URL only: nothing about the entity is loaded or stored.
            await self._repo.record_quarantine(run_id, blocked)
            counts["quarantined"] += 1
            logger.info("quarantined %s (%s)", blocked.result.rule_id, blocked.result.reason)

        for candidate in discovery.allowed:
            try:
                outcome = await self._repo.save_snapshot(run_id, await self._draft(candidate))
                counts["created" if outcome.created else "unchanged"] += 1
            except Exception as exc:  # one bad IPO must not stop the run
                counts["failed"] += 1
                report.errors.append(f"{candidate.name}: {type(exc).__name__}: {exc}"[:500])
                logger.warning("ingestion failed for one candidate: %s", type(exc).__name__)

        counts["withdrawn"] = await self._repo.reconcile_policy(self._policy)
        if counts["failed"]:
            report.status = "failed" if counts["failed"] == len(discovery.allowed) else "partial"
        error = "; ".join(report.errors)[:2000] or None
        await self._repo.finish_run(run_id, report.status, counts, error)
        return report

    async def _draft(self, candidate: Candidate) -> SnapshotDraft:
        docs = await self._port.load_documents(candidate)
        resolution = resolve_all(build_observations(candidate, docs))
        now = self._clock()
        today = ist_today(now)
        status = derive_status(resolution, today)
        return SnapshotDraft(
            company_name=candidate.name,
            normalized_name=normalize_name(candidate.name),
            is_synthetic=candidate.data.synthetic,
            policy_version=self._policy.version,
            documents=tuple(docs),
            resolution=resolution,
            status=status,
            status_as_of=today,
            fingerprint=fingerprint(resolution, status, docs),
            checked_at=now,
        )
