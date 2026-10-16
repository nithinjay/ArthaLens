# IPO Research & Stock Intelligence Agent

The full spec is in docs/PROJECT_BRIEF.md. Read it before starting any milestone.

## Working rules
- Work one milestone at a time; stop and wait for my verification before the next.
- Keep progress in docs/CHECKLIST.md (done / tested / planned / unverified).
- Never commit secrets. The Gemini key lives only in .env (gitignored); .env.example has placeholders.
- Jio IPO exclusion is enforced server-side and covered by tests.
- Deterministic code for calculations and validation; mock providers for tests.
- Never report a test as passing without running it.