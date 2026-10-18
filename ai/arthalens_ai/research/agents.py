"""Section agents and the ADK runtime (ADR-0003).

ADK orchestrates: independent sections run in a ``ParallelAgent``; the summary (J) runs after
them in a ``SequentialAgent``. Each section is a custom ``BaseAgent`` that:
1. skips itself if an earlier attempt already saved it (checkpointing, AC-4.3)
2. re-checks the exclusion policy (layer L4)
3. produces its result: planned -> unavailable; D -> code; A/E/F -> model; J -> model over claims
4. saves it immediately through the sink, so a crash loses at most the section in flight

Agents have no tools. Evidence reaches the model only as delimited data in the user message.
Failures inside one section become an honest "unavailable" for that section; they never
abort the others.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from google.adk.agents import BaseAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from arthalens_ai.policy.exclusion import EntityRef, ExclusionPolicy, evaluate
from arthalens_ai.research.catalog import CATALOG, PARALLEL_SECTIONS, SectionSpec
from arthalens_ai.research.contracts import (
    PlannedPassage,
    SectionId,
    SectionResult,
    UsageRecord,
)
from arthalens_ai.research.integrity import check_citations
from arthalens_ai.research.model import ModelError, ModelPort, ModelRequest, estimate_tokens
from arthalens_ai.research.planner import LabelledPassage, plan_section, render_evidence
from arthalens_ai.research.prompts import system_prompt
from arthalens_ai.research.structure import SnapshotField, build_structure_section

logger = logging.getLogger(__name__)


class SectionSink(Protocol):
    async def event(self, type_: str, payload: dict[str, Any]) -> None: ...

    async def save_section(self, result: SectionResult, attempt: int) -> None: ...


class BudgetExceeded(Exception):
    pass


@dataclass
class TokenBudget:
    """Per-job token budget (brief section 16). Reserve before a call, settle after."""

    limit: int
    used: int = 0

    def reserve(self, estimate: int) -> None:
        if self.used + estimate > self.limit:
            raise BudgetExceeded(f"token budget {self.limit} would be exceeded")
        self.used += estimate

    def settle(self, estimate: int, actual: int) -> None:
        self.used += actual - estimate


@dataclass
class ResearchDeps:
    report_id: UUID
    company_name: str
    attempt: int
    policy: ExclusionPolicy
    model: ModelPort
    sink: SectionSink
    budget: TokenBudget
    passages: list[LabelledPassage]
    snapshot_fields: dict[str, SnapshotField]
    section_timeout_s: float
    done: dict[SectionId, SectionResult] = field(default_factory=dict)
    results: dict[SectionId, SectionResult] = field(default_factory=dict)


class ExcludedDuringRun(Exception):
    pass


async def produce_section(spec: SectionSpec, deps: ResearchDeps) -> SectionResult:
    if spec.kind == "planned":
        return SectionResult(spec.id, "unavailable", "deterministic", spec.planned_reason)
    if spec.kind == "deterministic":
        return build_structure_section(deps.snapshot_fields)
    if spec.kind == "summary":
        return await _summary(spec, deps)
    return await _drafted(spec, deps)


async def _drafted(spec: SectionSpec, deps: ResearchDeps) -> SectionResult:
    plan = plan_section(spec, deps.passages)
    if not plan.covered:
        return SectionResult(spec.id, "unavailable", "pending", plan.reason)
    system, version = system_prompt(spec.id)
    user = (
        f"{render_evidence(plan.passages)}\n\n"
        f"Write section {spec.id} ({spec.title}) for {deps.company_name} "
        "using only the evidence above."
    )
    request = ModelRequest(
        purpose=spec.id,
        system=system,
        user=user,
        claim_type=spec.claim_type,
        keywords=spec.keywords,
        passages=plan.passages,
        timeout_s=deps.section_timeout_s,
    )
    return await _call_model(spec, deps, request, plan.passages, version)


async def _summary(spec: SectionSpec, deps: ResearchDeps) -> SectionResult:
    shown: list[PlannedPassage] = []
    lines: list[str] = []
    for section in ("A", "D", "E", "F"):
        result = deps.results.get(section) or deps.done.get(section)
        if result is None:
            continue
        for claim in result.claims:
            if claim.status == "quarantined":
                continue
            for c in claim.citations:
                shown.append(PlannedPassage(c.label, c.document_id, c.page, c.quote or "", 1.0))
            lines.append(f"[Section {section}] {claim.text}")
    if not lines:
        return SectionResult(
            "J", "unavailable", "pending", "No section produced claims to summarise."
        )
    system, version = system_prompt("J")
    # Each cited quote is shown as a passage, so the summary can only reuse existing citations.
    request = ModelRequest(
        purpose="J",
        system=system,
        user=f"{render_evidence(shown)}\n\nClaims from other sections:\n" + "\n".join(lines),
        claim_type="summary",
        passages=tuple(shown),
        prior_claims=_prior(deps),
        timeout_s=deps.section_timeout_s,
    )
    return await _call_model(spec, deps, request, shown, version)


def _prior(deps: ResearchDeps) -> tuple[Any, ...]:
    from arthalens_ai.research.contracts import DraftCitation
    from arthalens_ai.research.model import PriorClaim

    out = []
    for section in ("A", "D", "E", "F"):
        result = deps.results.get(section) or deps.done.get(section)
        for claim in result.claims if result else ():
            cites = tuple(
                DraftCitation(label=c.label, quote=c.quote or "-")
                for c in claim.citations
                if c.quote
            )
            if claim.status != "quarantined" and cites:
                out.append(PriorClaim(section, claim.text, cites))
    return tuple(out)


async def _call_model(
    spec: SectionSpec,
    deps: ResearchDeps,
    request: ModelRequest,
    shown: list[PlannedPassage] | tuple[PlannedPassage, ...],
    version: str,
) -> SectionResult:
    estimate = estimate_tokens(request.system + request.user) + request.max_output_tokens
    model = deps.model
    try:
        deps.budget.reserve(estimate)
    except BudgetExceeded as exc:
        usage = UsageRecord(model.provider, model.model, 0, 0, 0, "budget")
        return SectionResult(
            spec.id,
            "unavailable",
            "pending",
            f"Skipped: {exc}",
            usage=(usage,),
            prompt_version=version,
        )
    try:
        result = await model.generate(request)
    except ModelError as exc:
        deps.budget.settle(estimate, 0)
        outcome = exc.code if exc.code in ("timeout", "invalid_output") else "error"
        usage = UsageRecord(model.provider, model.model, 0, 0, 0, outcome)  # type: ignore[arg-type]
        return SectionResult(
            spec.id,
            "unavailable",
            "pending",
            f"The model call failed ({exc.code}); nothing was generated for this section.",
            prompt_version=version,
            model=model.model,
            usage=(usage,),
        )
    deps.budget.settle(estimate, result.input_tokens + result.output_tokens)
    usage = UsageRecord(
        result.provider,
        result.model,
        result.input_tokens,
        result.output_tokens,
        result.latency_ms,
        "ok",
        result.estimated_cost_usd,
    )
    claims = check_citations(result.draft, list(shown))
    kept = [c for c in claims if c.status != "quarantined"]
    if not kept:
        status, reason = "unavailable", "No drafted claim cited the evidence it was shown."
    else:
        status, reason = "degraded", "Drafted claims are not yet validated (Milestone 5)."
    return SectionResult(
        spec.id,
        status,  # type: ignore[arg-type]
        "pending",
        reason,
        claims,
        tuple(m[:200] for m in result.draft.missing),
        prompt_version=version,
        model=result.model,
        usage=(usage,),
    )


class SectionAgent(BaseAgent):
    """ADK agent for one report section."""

    section: str
    # Carried, not validated: pydantic can't build validators for Protocol-typed fields
    # (ModelPort, SectionSink) inside ResearchDeps.
    deps: Any

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event]:
        section: SectionId = self.section  # type: ignore[assignment]
        deps: ResearchDeps = self.deps
        if section in deps.done:
            deps.results[section] = deps.done[section]
            return
        if evaluate(deps.policy, EntityRef(name=deps.company_name)).blocked:
            raise ExcludedDuringRun(section)  # layer L4: stop the whole run
        spec = CATALOG[section]
        await deps.sink.event("section.started", {"section": section, "title": spec.title})
        try:
            async with asyncio.timeout(deps.section_timeout_s):
                result = await produce_section(spec, deps)
        except TimeoutError:
            result = SectionResult(section, "unavailable", "pending", "Section deadline exceeded.")
        except Exception as exc:  # one section must not take down the others
            logger.exception("section %s failed", section)
            result = SectionResult(
                section, "unavailable", "pending", f"Internal error ({type(exc).__name__})."
            )
        await deps.sink.save_section(result, deps.attempt)
        deps.results[section] = result
        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            actions=EventActions(state_delta={f"section_{section}": result.status}),
        )


async def run_research(deps: ResearchDeps) -> dict[SectionId, SectionResult]:
    """Run every section: A-I in parallel, then J. Returns all section results."""
    parallel = ParallelAgent(
        name="sections",
        sub_agents=[
            SectionAgent(name=f"section_{s}", section=s, deps=deps) for s in PARALLEL_SECTIONS
        ],
    )
    root = SequentialAgent(
        name="research",
        sub_agents=[parallel, SectionAgent(name="section_J", section="J", deps=deps)],
    )
    sessions = InMemorySessionService()
    user_id, session_id = "worker", str(deps.report_id)
    await sessions.create_session(app_name="arthalens", user_id=user_id, session_id=session_id)
    runner = Runner(app_name="arthalens", agent=root, session_service=sessions)
    message = types.Content(role="user", parts=[types.Part(text="Produce the report sections.")])
    async for _ in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
        pass
    return deps.results
