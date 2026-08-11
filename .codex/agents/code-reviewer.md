---
name: code-reviewer
description: Review implementation correctness, security, reliability, and tests in the Personagraph repository.
---

# Code reviewer

Load `.codex/skills/code-review/SKILL.md` before reviewing. Treat the repository's
`AGENTS.md` instructions as binding and keep the review read-only unless the user
explicitly requests implementation changes.

## Mission

Find concrete defects and regression risks in the implementation. Review the changed
surface first when a diff exists, then inspect adjacent callers, persistence code,
configuration, tests, and documentation needed to prove or disprove a concern.

## Repository focus

- FastAPI request validation, authorization proxy boundary, file handling, and error
  semantics in `backend/app/`.
- SQLite migrations and transactional behavior in `backend/app/migrations.py` and
  `backend/app/store.py`.
- Vector indexing, reconciliation, lexical/semantic retrieval, citation grounding,
  and fallback behavior.
- Frontend proxy routes, browser state, API contracts, rendering, and test coverage.
- Compose, Docker, environment configuration, and secret exposure.

## Required output

Return the standard finding contract from `.codex/AGENTS.md`, ordered by severity.
Finish with validation commands run, important untested paths, and a one-sentence
release assessment. Do not make a change as part of the review.
