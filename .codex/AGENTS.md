# Project reviewer agents

This folder contains project-local Codex reviewer profiles and the skills they use.
They are read-only by default: review agents may inspect files, run safe validation,
and report findings, but must not modify application code unless the user explicitly
asks for fixes.

## Available agents

- `agents/code-reviewer.md` — correctness, security, reliability, test coverage, and
  maintainability of implementation details.
- `agents/architecture-reviewer.md` — system boundaries, data ownership, lifecycle
  invariants, failure recovery, deployment, and long-term design risks.
- `agents/review-orchestrator.md` — runs both review lenses and produces one
  deduplicated report with prioritized findings and follow-up actions.

Each focused agent loads its matching skill from `.codex/skills/`. The orchestrator
loads both skills and treats `README.md`, `docs/`, `AGENTS.md`, source, tests, and
runtime configuration as evidence to reconcile rather than assuming documentation
is correct.

## Review contract

Every finding must include:

1. Severity: `P0` blocker, `P1` high risk, `P2` medium risk, or `P3` low risk.
2. Location: an exact file and line or symbol when possible.
3. Evidence: the observed behavior or code path.
4. Impact: who or what can fail, including security or data consequences.
5. Recommendation: the smallest concrete next step.

Do not report style preferences as defects. If no actionable findings are supported,
say so and list the validation performed plus residual uncertainty.
