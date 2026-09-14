# Workflow roles and validation gates

## Roles

Use these as separate subagent assignments when parallel work is useful. Keep their scopes disjoint.

### Specification analyst

Reads the feature request and approved spec. Produces: affected requirements, open decisions, acceptance criteria, module owner, data and API impact, and a test matrix. Does not modify production code.

### Implementation owner

Implements the approved checklist in the owning module. Adds instrumentation and updates narrow documentation when behavior changes. Does not waive failing tests or validator findings.

### Test engineer

Derives tests from acceptance criteria and invariants. Adds unit, integration or end-to-end coverage as appropriate; always include an authorization or isolation case when data retrieval is touched. Runs focused tests first, then the required suite.

### Feature validator

Independently reviews the final diff and test evidence. It checks: acceptance criteria, regressions, tenant and folder isolation, citation or error behavior, idempotency where jobs change, performance risks and observability. It reports findings by blocking, important, or suggestion. It does not implement changes unless asked.

## Feature dossier

Every feature has a durable dossier at `specs/work-items/<feature-id>.md`. Create it with `scripts/init-work-item.sh <feature-id> "<title>"` before delegation. The dossier is the handoff contract and must contain:

- status: `draft`, `ready`, `implementing`, `validating`, `blocked`, or `done`;
- source specification and acceptance criteria;
- decisions, decision owner, and ADR links;
- module/file ownership assigned to each agent;
- test matrix and exact commands run;
- validator findings, independent evidence, and final gate decision.

Do not start implementation while status is `draft` or `blocked`; do not set it to `done` while a Blocking finding remains.

## Decision policy

- An agent may make an implementation choice autonomously only when it is already bounded by an approved spec and does not alter scope, data ownership, authorization, retention, external provider, material cost, or public API behavior.
- Record durable technical choices in `specs/adr/`.
- A missing decision in one of the protected areas is blocking and must be escalated to the user. Other low-risk choices are recorded in the feature dossier and may proceed.

## Delegation and ownership rules

1. The specification analyst works read-only and fills the dossier's ready checklist.
2. Before parallel work, name the module and files owned by each agent in the dossier. Two write agents must never own the same production or test file.
3. Test design may run in parallel with implementation planning. Test implementation may run in parallel only when its file ownership does not overlap the implementation owner.
4. In a shared working tree, use parallel agents only for read-only analysis, test design, or disjoint files. Use isolated worktrees when Git is available and concurrent writes are needed.
5. The validator runs after integration, does not edit code, independently reruns relevant commands, and records its own evidence in the dossier. It may inspect the diff and spec but must not treat the implementation owner's summary as proof.
6. For a small isolated feature, one agent may implement and test; independent validation remains mandatory.

## Required evidence by change type

| Change | Minimum evidence |
| --- | --- |
| API or UI behavior | Acceptance test plus a negative/error path |
| Data model or migration | Migration test, rollback consideration and tenant-scoping test |
| Retrieval or RAG | Evaluation fixture, citation check and insufficient-evidence test |
| Background job | Idempotency, retry and terminal-state tests |
| Authentication or authorization | Positive and cross-organization denial tests |
| Performance-sensitive path | Measured query or request budget and regression check |

## Performance evidence

For a performance-sensitive change, the dossier defines a reproducible workload: dataset shape, relevant request or query, local/runtime baseline, target budget, command and result. Do not claim a p95 target without this evidence. Performance checks are advisory during the empty-project phase and become release gates once the benchmark harness exists.

## Definition of Ready

A feature can enter implementation only when the dossier is `ready`, its owning module and files are assigned, inputs/outputs, acceptance criteria, authorization behavior, failure states, observability, test evidence and any protected decisions are known.

## Definition of Done

The dossier is `done`; acceptance criteria are mapped to evidence; tests and commands are reproducible; the validator has independently rerun relevant checks; no Blocking finding remains; telemetry covers relevant success/failure states; and the specification or ADR reflects every durable behavior or decision change.
