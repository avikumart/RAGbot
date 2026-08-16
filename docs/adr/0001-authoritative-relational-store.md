# 0001: Keep application records authoritative in the relational store

- Status: Accepted
- Date: 2026-08-15
- Deciders: project maintainers
- Supersedes: none
- Superseded by: none

## Context

Personagraph needs durable document, conversation, ownership, citation, and
cleanup state while also supporting semantic retrieval. Vector search systems
are optimized for nearest-neighbor lookup but are a poor authority for relational
constraints, transactional deletion, authorization checks, and exact cited text.
Keeping complete chunks in both stores would create conflicting sources of truth
and make partial failures ambiguous.

## Decision

The backend relational database is authoritative for application records and
exact source text. Qdrant contains only rebuildable embeddings plus identifiers,
hashes, model metadata, and scoping metadata needed to find candidates.

All vector candidates are checked against authorized relational rows, and the
API reads cited excerpts from those rows. Relational writes commit before vector
indexing. Deletion commits relational state first, then performs retryable file
and vector cleanup. A database-engine change may replace the relational
implementation without changing these ownership rules.

## Alternatives considered

### Store authoritative chunks in Qdrant

This removes a lookup after semantic search but weakens transaction, constraint,
and authorization guarantees and makes vector availability part of the core data
durability contract.

### Store full chunks in both systems

Duplication can improve read locality but introduces synchronization and stale
citation risks. It also makes incident recovery depend on choosing which copy is
correct.

### Remove semantic storage

Lexical-only retrieval is simpler and remains a supported fallback, but it does
not satisfy the desired semantic matching behavior.

## Consequences

- Qdrant can be deleted, recreated, or migrated through deterministic backfill.
- Vector outages degrade retrieval without making accepted documents disappear.
- Retrieval performs an authoritative relational read before returning evidence.
- Database backup and restore procedures must cover relational data and managed
  uploads; vector backups are optional acceleration rather than correctness data.
- Schema and database-engine migrations must preserve identifiers referenced by
  vector payloads.

## Validation

Automated tests cover scoped vector validation, lexical fallback, idempotent
backfill, orphan removal, deletion ordering, and retryable managed-file cleanup.
The complete stack check exercises the API with its configured database and
Qdrant services.
