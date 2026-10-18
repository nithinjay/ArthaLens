"""SearchPort: the single entry point to external sources (brief section 8, ADR-0003).

Providers find candidate IPOs and load their documents. SearchPort applies exclusion layer L5
*between* those steps: a blocked entity is returned for quarantine and its documents are never
read or fetched. It re-checks before loading, so a caller can't skip the first check.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from arthalens_ai.contracts.ipo import RetrievalMethod
from arthalens_ai.ingestion.models import Candidate, LoadedDocument
from arthalens_ai.policy.exclusion import EntityRef, ExclusionPolicy, ExclusionResult, evaluate


class IpoSourceProvider(Protocol):
    name: str

    @property
    def retrieval_method(self) -> RetrievalMethod: ...

    def candidates(self) -> list[Candidate]: ...

    async def load_documents(self, candidate: Candidate) -> list[LoadedDocument]: ...


@dataclass(frozen=True)
class Blocked:
    candidate: Candidate
    result: ExclusionResult


@dataclass(frozen=True)
class Discovery:
    allowed: list[Candidate]
    blocked: list[Blocked]


class EntityBlockedError(Exception):
    def __init__(self, result: ExclusionResult) -> None:
        super().__init__(f"entity blocked by {result.rule_id} ({result.decision})")
        self.result = result


class SearchPort:
    def __init__(self, providers: Mapping[str, IpoSourceProvider], policy: ExclusionPolicy) -> None:
        self._providers = dict(providers)
        self._policy = policy

    def _provider(self, name: str) -> IpoSourceProvider:
        if name not in self._providers:
            raise KeyError(f"provider {name!r} is not enabled; enabled: {sorted(self._providers)}")
        return self._providers[name]

    def check(self, candidate: Candidate) -> ExclusionResult:
        entity = EntityRef(name=candidate.name, identifiers=candidate.data.identifiers)
        return evaluate(self._policy, entity, "ipo")

    def discover(self, provider: str) -> Discovery:
        allowed, blocked = [], []
        for candidate in self._provider(provider).candidates():
            result = self.check(candidate)
            if result.blocked:
                blocked.append(Blocked(candidate, result))
            else:
                allowed.append(candidate)
        return Discovery(allowed, blocked)

    async def load_documents(self, candidate: Candidate) -> list[LoadedDocument]:
        result = self.check(candidate)
        if result.blocked:
            raise EntityBlockedError(result)
        return await self._provider(candidate.provider).load_documents(candidate)
