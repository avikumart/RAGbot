---
name: code-review
description: Review a repository or diff for actionable implementation defects, security issues, reliability risks, contract violations, and missing regression coverage; use for code-review or pull-request review requests.
---

# Code review skill

## Workflow

1. Read `AGENTS.md` and determine whether the review targets the working tree, a
   branch diff, a named feature, or the full repository. Capture the baseline with
   `git status --short` and `git diff --stat`; do not assume a clean tree.
2. Read the relevant README and `docs/` pages before judging behavior. Treat docs as
   a contract to verify, not proof that the code follows it.
3. Map changed entry points to callers, persistence, configuration, external services,
   and tests. Follow data across boundaries instead of reviewing isolated lines.
4. Inspect high-risk behavior first:
   - authentication, authorization, identity binding, CORS, secrets, and privacy;
   - untrusted file names, upload size/type handling, path containment, and cleanup;
   - SQL parameters, transactions, foreign keys, migrations, and partial commits;
   - async/sync boundaries, timeouts, retries, idempotency, concurrency, and resource
     limits;
   - retrieval scope, stale data, ranking, citations, fallback behavior, and error
     messages;
   - frontend/backend request contracts, serialization, browser persistence, and
     optimistic retry behavior.
5. For each suspected issue, reproduce or disprove it with a focused read-only test,
   existing test, static inspection, or minimal safe command. Prefer evidence over
   hypothetical hardening advice.
6. Run the narrowest relevant validation first. For this repository, prefer `npm run
   lint`, `npm test`, focused backend pytest commands, and `./scripts/local_checks.sh`
   when the environment supports them. Report skipped commands and why.

## Finding bar

Report only actionable findings. A finding needs a specific location, a realistic
trigger, and a concrete consequence. Do not report formatting, naming, or refactors
unless they cause a correctness, security, reliability, performance, or maintenance
problem. Check whether tests or downstream code already make the suspected behavior
safe before reporting it.

Use severity `P0` (release blocker/data or security catastrophe), `P1` (high-impact
defect or likely security/privacy issue), `P2` (meaningful correctness/reliability
risk), or `P3` (low-impact defect or worthwhile hardening).

## Output contract

Start with the highest-risk finding, not a process summary. For every finding use:

```text
[P1] Short title
Location: path/to/file.py:123 or SymbolName
Evidence: what the code does and the trigger.
Impact: concrete user, data, security, or operational consequence.
Recommendation: smallest practical fix or test.
```

End with `Validation`, `Coverage gaps`, and `Release assessment`. If no findings are
supported, explicitly say “No actionable findings found” and still state what was
checked and what remains uncertain.
