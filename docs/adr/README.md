# Architecture decision records

Architecture decision records (ADRs) explain why a durable technical choice was
made, the alternatives considered, and its operational consequences. They are
part of the maintained project documentation and are reviewed with code.

## Records

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-authoritative-relational-store.md) | Accepted | Keep application records authoritative in the relational store and vectors rebuildable |
| [0002](0002-pluggable-llm-provider-architecture.md) | Accepted | Pluggable LLM provider architecture for retrieval summarization |


## Workflow

1. Copy [`template.md`](template.md) to the next zero-padded number and a short
   kebab-case title, for example `0002-replace-job-runner.md`.
2. Set the status to `Proposed`, describe the context and realistic alternatives,
   and include migration, failure-recovery, security, and operational effects.
3. Add the record to the table above and open it with the implementation PR (or
   before implementation when the decision needs broader agreement).
4. During review, resolve material design questions in the ADR rather than only
   in transient PR comments.
5. Change the status to `Accepted` when merged. Accepted records are immutable
   historical context: create a new ADR that `Supersedes` the old one instead of
   rewriting the original decision.

Small implementation choices that do not alter system boundaries, ownership,
public contracts, persistence, privacy, or operations do not require an ADR.
