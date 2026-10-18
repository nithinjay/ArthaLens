# ADR-0003: Google ADK as orchestration runtime behind our own port

**Status:** Accepted · **Date:** 2026-10-17

## Context
The brief requires Google ADK + Gemini, bounded agents with typed contracts, parallel sections, and bounded repair. It also requires model providers behind interfaces.

## Decision
- Use ADK for **orchestration only**: workflow composition (sequential stages, parallel section fan-out, loop-style bounded repair), LLM agent definitions with structured output schemas, and session/state for a run.
- Wrap it behind our own interfaces:
  - `ResearchRuntime.run(job) -> ReportResult`. The worker calls this, never ADK directly.
  - `ModelPort` for generation/classification/entailment calls. The Gemini implementation is the first adapter. Model IDs live in versioned config, not code.
- **Deterministic steps stay plain Python** and are invoked by ADK, never re-implemented as LLM agents: retrieval planner (core), SearchPort, ledger writes, metrics engine, validator, composer.
- Agent tool permissions are **read-only** (read evidence passages, read metrics). No agent has a tool that writes evidence or approves claims.
- Pin the ADK version. Each upgrade goes through the regression eval suite.

## Consequences
- + ADK's workflow agents map naturally onto fan-out and bounded loops, and Gemini integration is native.
- + `ResearchRuntime`/`ModelPort` keep the domain testable with `FakeModelPort` and portable to local models (Stage 8).
- − ADK is evolving quickly, so its APIs may change. The port limits blast radius.
- − Some ADK conveniences (built-in search tools, memory services) are deliberately **not** used, because they would bypass the evidence ledger. Exact ADK APIs used will be confirmed against the pinned version in Milestone 4.

## Alternatives
- **Hand-rolled asyncio orchestration:** fully transparent, but goes against the brief and reinvents tracing and session handling.
- **LangGraph / other frameworks:** viable, but no reason to deviate from the brief.
