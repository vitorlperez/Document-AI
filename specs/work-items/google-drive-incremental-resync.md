# google-drive-incremental-resync - Google Drive incremental resync

**Status:** done

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
| Given a selection without a cursor, when resync runs, then it captures a start token and indexes a complete snapshot | Unit | covered in Google provider tests; complete suite passed |
| Given a valid cursor, when files change, then only in-scope changed files are fetched and removals are reconciled | Unit | Changed-file, selected-root, and removed-subtree tests |
| Given a moved folder, invalid cursor, or expired cursor, when resync runs, then it safely falls back to a complete snapshot | Unit | Removed-subtree and expired-cursor snapshot tests |
| Given a failed or manually requested document reprocess, when no remote change event exists, then only that document is fetched again | Unit/task | Forced-ID discovery and task propagation tests |
| Given any indexing/projection failure, when the task rolls back, then the old cursor remains committed | Task integration | Existing shared ingestion behavior |

## Commands and results

| Command | Result | Run by | Independent rerun |
| --- | --- | --- | --- |
| `backend/.venv/bin/pytest -q` (cwd `backend/`) | 293 passed, 6 skipped | pane-58 | independent review approved |
| Focused provider suite (`test_google_drive_ingestion`, `test_google_drive_connection`, `test_notion_integration`, `test_onedrive`, `test_onedrive_ingestion_task`, `test_ingestion_service`) | 77 passed | pane-52 | Fresh rerun |
| `backend/.venv/bin/ruff check ...` (affected modules/tests) | Passed | pane-58 | fresh focused rerun passed |
| `git diff --check` | Passed | pane-58 | fresh rerun passed |
| `.tools/graphify/bin/graphify update .` | Passed; 3208 nodes, 8270 edges, 234 communities before final test additions | Implementation owner | Rerun pending |

## Validator report

- Blocking: none.
- Important: none.
- Suggestions: retain coverage for Changes pagination, cursor expiry, scope filtering, and folder ancestry fallback.
- Independent evidence: pane-58 reports four review findings corrected with no residual; backend suite 293 passed/6 skipped, lint and graphify passed. Pane-52 independently reran 77 focused provider tests and Ruff.
- Gate decision: approved.
