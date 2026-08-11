---
name: architecture-review
description: Review a system's architecture, data ownership, boundaries, lifecycle invariants, failure recovery, privacy, and operational risks; use for architecture reviews or repository-wide design assessment.
---

# Architecture review skill

## Workflow

1. Read `AGENTS.md`, `README.md`, and the relevant `docs/` pages. Establish the
   intended components, deployment topology, data stores, trust boundaries, and
   operational commands.
2. Build a compact map of clients, API boundaries, authoritative stores, rebuildable
   stores, background or repair paths, external providers, and persistence volumes.
3. Trace these flows end to end: upload/index, question/answer, deletion/cleanup, and
   startup/migration/backfill. For each flow record state transitions, commit points,
   retries, and what happens after a process or dependency fails.
4. Test architectural claims against code and configuration. Pay special attention to
   authority versus cache, cross-service identity propagation, document/person/session
   scoping, citation provenance, migration ordering, model/schema compatibility,
   idempotency, observability, and backup/restore assumptions.
5. Evaluate the system across security and privacy, correctness and consistency,
   availability and recovery, scalability/resource limits, operability, and change
   safety. Rank only risks with a plausible trigger and material consequence.
6. Use focused tests, static inspection, and safe local commands to validate important
   claims. Do not edit application code or create migrations as part of the review.

## Personagraph invariants to verify

- SQLite is authoritative for document text, metadata, conversations, and citation
  snapshots; Qdrant is rebuildable and never the source of cited text.
- A committed upload remains usable if vector indexing fails, and its status exposes
  the repair path.
- A committed deletion cannot be undone by a filesystem or vector cleanup failure.
- Session identity is derived by the trusted proxy and owner scope is enforced for all
  session/chat persistence operations.
- Retrieval scope is applied on every candidate path and stale vector hits cannot leak
  deleted or out-of-scope content.
- Migrations are append-only, transactional, idempotent, and safe for legacy data.

## Output contract

Start with an executive architecture assessment. Include a compact text component map
and the invariants checked. Findings use:

```text
[P1] Short title
Location: path/to/file.py:123, component, or configuration key
Evidence: observed flow or mismatch between design and implementation.
Impact: concrete data, privacy, availability, correctness, or operating consequence.
Recommendation: phased, smallest practical next step.
```

End with `Validation`, `Residual risks`, and recommendations grouped as immediate
safety, near-term correctness, and longer-term design. Label inferences and unknowns.
