---
name: sdd-feature-delivery
description: Deliver product features through an approved specification, modular-monolith boundaries, parallel implementation and test roles, and mandatory independent validation. Use when implementing or changing this project's features.
---

# Spec-Driven Feature Delivery

Use this skill for feature work in this project. Treat the approved specification as the source of truth and keep the implementation small, testable, observable, and reversible.

## Read first

1. Read the applicable file in `specs/` completely.
2. Read [workflow roles and gates](references/workflow.md).
3. Initialize `specs/work-items/<feature-id>.md` with `scripts/init-work-item.sh` and follow its status gate.
4. If the specification is missing a decision that changes behavior, security, cost, or data ownership, record it and obtain confirmation before coding.

## Autonomous delivery loop

For a feature that touches more than one module or has meaningful risk, split independent work among the roles in the workflow reference. The implementation owner remains responsible for integration; do not let parallel agents edit the same files.

Follow this order:

1. **Specify** - extract affected flows, business invariants, acceptance criteria and non-goals into the feature dossier. Update the specification only when durable behavior changes; record implementation-only choices in the dossier.
2. **Design** - identify the owning module, database/API changes, performance impact, migration or rollback need, and tests required. Preserve modular-monolith boundaries.
3. **Implement** - make the smallest coherent change in the owner module. Do not introduce a microservice, new connector, or cross-module database access without an ADR.
4. **Test** - create or update tests from the acceptance criteria. A feature is incomplete if its relevant positive, negative and authorization paths lack coverage.
5. **Validate** - assign an independent validation pass after implementation. It must inspect the final diff, run relevant checks, verify acceptance criteria, challenge tenant isolation and document evidence. Resolve blocking findings and rerun affected checks.
6. **Record** - update the spec, ADR, API contract, observability notes and changelog only when the feature changes them. Complete the dossier with reproducible commands and the validator's independent evidence.

## Non-negotiable project invariants

- Every data access is scoped by `organization_id`; retrieval is additionally scoped by `workspace_folder_id`.
- Never pass content from an unscoped document, chunk, cache entry or log to a user or LLM.
- Facts in generated answers require citations. Insufficient evidence is a valid outcome.
- Background jobs are idempotent and report explicit terminal states.
- OAuth secrets and full document content never appear in logs, test fixtures or error messages.
- Optimize the modular monolith before introducing distributed services: explicit module APIs, asynchronous jobs and measured bottlenecks are the scale path.

## Completion gate

Do not call a feature complete until the independent validator reports no unresolved blocking issue, relevant tests pass, and the acceptance criteria are mapped to evidence. If an external dependency prevents validation, report exactly what is unverified and why.
