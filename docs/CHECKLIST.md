# Project Checklist

Legend: **done** = written/implemented · **tested** = verified by a test or check that was actually run · **planned** = not started · **unverified** = assumption not yet confirmed

_Last updated: 2026-10-17_

## Milestone 0: Requirements and architecture (awaiting your review)

| Item | State | Location |
|---|---|---|
| Requirements (FR/NFR, assumptions, open questions) | done | [requirements.md](requirements.md) |
| Request lifecycle + Phase 2 extension | done | [architecture/request-lifecycle.md](architecture/request-lifecycle.md) |
| System architecture, components, service responsibilities | done | [architecture/system-architecture.md](architecture/system-architecture.md) |
| Data-flow diagram with trust boundaries | done | same, §4 |
| Repository structure + planned commands | done | same, §6–7 |
| Threat model | done | [security/threat-model.md](security/threat-model.md) |
| Source-provider strategy | done | [architecture/source-provider-strategy.md](architecture/source-provider-strategy.md) |
| ADRs 0001–0013 | done (Proposed) | [decisions/](decisions/README.md) |
| Acceptance criteria | done | [acceptance-criteria.md](acceptance-criteria.md) |
| Mermaid diagrams render | unverified | Not rendered in this session; check in your IDE/GitHub preview |
| User approval of M0 | planned | You |

No code has been written and no tests exist yet, so nothing is in the **tested** state.

## Unverified assumptions to resolve
- Indian IPO application rules in requirements §4 (to verify against SEBI/RHP at M7).
- Terms of use for NSE/BSE/SEBI programmatic access (before M2 live adapters).
- Exact Google ADK APIs and current Gemini model IDs (at M4, against pinned versions).
- Open questions Q1–Q6 in requirements §6.

## Later milestones
| Milestone | State |
|---|---|
| M1 Foundation | planned |
| M2 IPO ingestion + exclusion | planned |
| M3 Evidence ledger | planned |
| M4 Research orchestration | planned |
| M5 Validation & repair | planned |
| M6 Research UI | planned |
| M7 Calculator | planned |
| M8 Security & reliability | planned |
| M9 Stock intelligence | planned |
| M10 Observability & evals | planned |
| M11 Production deployment | planned |
| M12 Enterprise FDE extensions | planned |
