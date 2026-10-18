"""In-memory test double for IngestionRepository. Mirrors the Postgres semantics that matter:
fingerprint-based de-duplication, per-IPO versions and quarantine upserts."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from arthalens_ai.ingestion.pipeline import RunStatus, SaveOutcome, SnapshotDraft
from arthalens_ai.ingestion.searchport import Blocked
from arthalens_ai.policy.exclusion import EntityRef, ExclusionPolicy, evaluate


@dataclass
class InMemoryRepo:
    runs: dict[UUID, dict[str, object]] = field(default_factory=dict)
    quarantine: dict[str, Blocked] = field(default_factory=dict)
    ipos: dict[str, UUID] = field(default_factory=dict)
    snapshots: dict[UUID, list[SnapshotDraft]] = field(default_factory=dict)
    withdrawn: set[UUID] = field(default_factory=set)

    async def start_run(self, provider: str) -> UUID:
        run_id = uuid4()
        self.runs[run_id] = {"provider": provider, "status": "running"}
        return run_id

    async def finish_run(
        self, run_id: UUID, status: RunStatus, counts: dict[str, int], error: str | None
    ) -> None:
        self.runs[run_id].update(status=status, counts=dict(counts), error=error)

    async def record_quarantine(self, run_id: UUID, blocked: Blocked) -> None:
        self.quarantine[blocked.candidate.name] = blocked

    async def save_snapshot(self, run_id: UUID, draft: SnapshotDraft) -> SaveOutcome:
        ipo_id = self.ipos.setdefault(draft.normalized_name, uuid4())
        history = self.snapshots.setdefault(ipo_id, [])
        if history and history[-1].fingerprint == draft.fingerprint:
            return SaveOutcome(ipo_id, len(history), created=False)
        history.append(draft)
        return SaveOutcome(ipo_id, len(history), created=True)

    async def reconcile_policy(self, policy: ExclusionPolicy) -> int:
        count = 0
        for ipo_id, history in self.snapshots.items():
            name = history[-1].company_name
            if ipo_id not in self.withdrawn and evaluate(policy, EntityRef(name=name)).blocked:
                self.withdrawn.add(ipo_id)
                count += 1
        return count

    def latest(self, company_name: str) -> SnapshotDraft:
        for history in self.snapshots.values():
            if history[-1].company_name == company_name:
                return history[-1]
        raise KeyError(company_name)
