# ADR-0013: Frontend component, form and chart libraries

**Status:** Accepted · **Date:** 2026-10-17

## Decision
- **Build:** Vite + React + TypeScript (strict).
- **Components:** Radix UI primitives via shadcn/ui-style local components plus Tailwind CSS. Radix provides accessible keyboard/focus/ARIA behaviour, and owning the component source avoids lock-in.
- **Server state:** TanStack Query.
- **Forms:** React Hook Form + Zod (schemas shared from `packages/contracts` / `packages/ipo-rules`).
- **Routing:** React Router (or TanStack Router; confirmed at M6).
- **Charts:** Recharts for financial trends and allocation scenarios, with accessible data tables alongside every chart.
- **Untrusted content:** rendered as text only; ESLint rule bans `dangerouslySetInnerHTML`.
- **A11y checks:** axe-core in Playwright e2e.

## Alternatives
- MUI/Ant Design: faster start, but heavier and harder to make look like a focused financial tool.
- ECharts: more powerful, heavier. Revisit if charting needs outgrow Recharts.
