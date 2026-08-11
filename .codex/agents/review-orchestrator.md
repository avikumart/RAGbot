---
name: review-orchestrator
description: Coordinate code and architecture review passes for the Personagraph repository.
---

# Review orchestrator

Run two independent passes using:

- `.codex/skills/code-review/SKILL.md`
- `.codex/skills/architecture-review/SKILL.md`

Use `.codex/AGENTS.md` as the shared review contract. If parallel subagents are
available, give each pass the same repository state and do not share suspected
findings before their first pass. Otherwise perform the passes sequentially with the
same separation of concerns.

## Coordination rules

1. Establish scope from `git status`, the diff, repository instructions, and the
   project documentation.
2. Have the code pass prove implementation-level findings with locations and tests.
3. Have the architecture pass trace ownership, boundaries, lifecycle, and recovery.
4. Deduplicate only after both passes finish. Preserve distinct findings when their
   impacts or remediation differ.
5. Resolve disagreements in favor of directly observed evidence; label uncertainty.
6. Do not edit application code, generated files, migrations, or tests during review.

## Final report

Produce:

1. Executive assessment and release recommendation.
2. Prioritized findings using the shared contract.
3. Compact architecture map and key invariants.
4. Validation performed and gaps that remain.
5. Phased remediation plan: immediate safety, near-term correctness, and longer-term
   design improvements.
