# google-drive-incremental-resync - Google Drive incremental resync

**Status:** validating

## Source and outcome

- Source specification: `specs/001-mvp-document-intelligence.md`, §§7, 13; ADR-0003.
- User outcome: resync Google Drive without downloading and extracting every unchanged file.
- Non-goals: scheduled polling, webhook delivery, and changes to OneDrive behavior.

## Decisions

| Decision | Owner | Status | ADR / rationale |
| --- | --- | --- | --- |
| Use Drive Changes API with a per-selection encrypted page token; full snapshot initially and after invalid tokens or folder ancestry changes | Implementation | selected for this delivery | Existing `DiscoveryResult` contract and encrypted selection cursor; matches incremental sync model used by OneDrive |
| Advance tokens in the same transaction as successful indexing | Implementation | existing task contract | Cursor persistence already occurs after indexing and projection, in the successful task commit |

## Ready checklist

- [x] Acceptance criteria written in Given/When/Then form.
- [x] Owning module, API/data impact and failure states identified.
- [x] Authorization, tenant and workspace-folder impact assessed.
- [x] Performance and observability impact assessed.
- [x] Protected decisions approved or marked not applicable.

## Ownership

| Role | Module/files owned | Deliverable |
| --- | --- | --- |
| Specification analyst | Read-only | Requirements summarized here |
| Implementation owner | `backend/app/integrations/google_drive.py`, `backend/app/ingestion/google_drive.py`, `backend/app/integrations/registry.py`, tests and spec | Changes API discovery and encrypted cursor support |
| Test engineer | Same feature files | No separate assignment in this worker delivery |
| Feature validator | Read-only | Independent gate not completed in this worker delivery |

## Acceptance criteria and test matrix

| Criterion | Test layer | Evidence |
| --- | --- | --- |
| Given a selection without a cursor, when resync runs, then it captures a start token and indexes a complete snapshot | Unit | Pending |
| Given a valid cursor, when files change, then only in-scope changed files are fetched and removals are reconciled | Unit | Pending |
| Given a moved folder, invalid cursor, or expired cursor, when resync runs, then it safely falls back to a complete snapshot | Unit | Pending |
| Given any indexing/projection failure, when the task rolls back, then the old cursor remains committed | Task integration | Existing shared ingestion behavior |

## Commands and results

| Command | Result | Run by | Independent rerun |
| --- | --- | --- | --- |
| `python -m compileall -q backend/app/integrations/google_drive.py backend/app/ingestion/google_drive.py backend/app/integrations/registry.py` | Passed | Implementation owner | Pending |
| `git diff --check -- backend/app/integrations/google_drive.py backend/app/ingestion/google_drive.py backend/app/integrations/registry.py specs/adr/0003-pilot-sync-ai-and-usage.md specs/work-items/google-drive-incremental-resync.md` | Passed | Implementation owner | Pending |
| `.tools/graphify/bin/graphify update .` | Passed; 3173 nodes, 8176 edges, 241 communities | Implementation owner | Not applicable |
| Google Drive sync unit tests | Not run | Implementation owner | Pending |

## Validator report

- Blocking: independent validation and sync unit-test evidence pending.
- Important: none recorded.
- Suggestions: add Google Changes API and provider unit tests, including overlap and folder fallback.
- Independent evidence: pending.
- Gate decision: not yet complete.
