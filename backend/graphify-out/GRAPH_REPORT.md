# Graph Report - backend  (2026-09-23)

## Corpus Check
- 106 files · ~48,139 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 5 file(s) not represented in the graph (top: (none) 2, .render 1, .ini 1)

## Summary
- 1413 nodes · 5532 edges · 74 communities (47 shown, 27 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 854 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `62890ab2`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- DataSource
- User
- MembershipRole
- MicrosoftGraphClient
- WorkspaceFolder
- integrations.py
- WorkspaceService
- ingestion/service.py
- test_google_drive_connection.py
- PlatformStaffAccessService
- Document
- GoogleCredentials
- LibraryService
- test_google_integrations.py
- test_text_search_api.py
- WorkspaceFolderSelection
- test_text_search.py
- IngestionService
- DocumentChunk
- tasks.py
- login
- questions.py
- OrganizationScope
- test_onedrive_delta_cursor_commits_with_successful_ingestion
- NotionOAuthClient
- RemoteFolder
- AIProviderUnavailable
- Evidence
- Settings
- typing
- test_multiscope_questions_api.py
- test_exhausted_embedding_rate_limit_rolls_back_and_marks_job_failed
- ingestion/google_drive.py
- registry.py
- test_structured_logging.py
- os
- logging.py
- config.py
- library.py
- NotionPage
- seed_library
- test_projects_nested_drive_tree_and_merges_overlapping_syncs
- alembic
- sqlalchemy_dialects
- GoogleOAuthUnavailable
- test_google_client_lists_direct_root_files_with_pagination
- 20260913_0012_company_library.py
- readiness
- ExtractedBlock
- GoogleDriveProviderAdapter
- RequestLogMiddleware
- api/__init__.py
- audit_usage/__init__.py
- identity/__init__.py
- ingestion/__init__.py
- app/__init__.py
- integrations/__init__.py
- knowledge/__init__.py
- library/__init__.py
- organizations/__init__.py
- workspaces/__init__.py
- start-render-api.sh
- document-intelligence-api

## God Nodes (most connected - your core abstractions)
1. `OrganizationScope` - 201 edges
2. `select()` - 137 edges
3. `User` - 123 edges
4. `WorkspaceFolder` - 84 edges
5. `IngestionService` - 82 edges
6. `DataSource` - 82 edges
7. `MembershipRole` - 74 edges
8. `Document` - 70 edges
9. `Membership` - 68 edges
10. `GoogleCredentials` - 65 edges

## Surprising Connections (you probably didn't know these)
- `test_authenticated_user_creates_organization_owner_and_audit()` --calls--> `select()`  [INFERRED]
  tests/api/test_auth_and_invitations.py → app/api/integrations.py
- `test_callback_is_idempotent_and_issues_hash_only_opaque_sessions()` --calls--> `select()`  [INFERRED]
  tests/api/test_auth_and_invitations.py → app/api/integrations.py
- `test_callback_rejects_missing_or_mismatched_login_state()` --calls--> `select()`  [INFERRED]
  tests/api/test_auth_and_invitations.py → app/api/integrations.py
- `test_company_listing_and_member_management_are_owner_scoped()` --calls--> `select()`  [INFERRED]
  tests/api/test_auth_and_invitations.py → app/api/integrations.py
- `test_expired_revoked_or_altered_token_cannot_be_accepted()` --calls--> `select()`  [INFERRED]
  tests/api/test_auth_and_invitations.py → app/api/integrations.py

## Import Cycles
- None detected.

## Communities (74 total, 27 thin omitted)

### Community 0 - "DataSource"
Cohesion: 0.08
Nodes (75): UsageRecord, Tenant-scoped saved-query ownership and monthly cost guardrails., Base, CreatedAtMixin, UUIDPrimaryKeyMixin, Identity, opaque-session and AuthKit integration boundaries., UserSession, Durable lifecycle records for asynchronous folder reconciliation. (+67 more)

### Community 1 - "User"
Cohesion: 0.05
Nodes (65): accept_invitation(), callback(), create_invitation(), create_organization(), current_user(), database_session(), deactivate_membership(), InvitationCreateInput (+57 more)

### Community 2 - "MembershipRole"
Cohesion: 0.06
Nodes (60): AuditLog, ValueError, TenantScopeRequired, Membership, MembershipInvitation, MembershipRole, str, _canonical_email() (+52 more)

### Community 3 - "MicrosoftGraphClient"
Cohesion: 0.07
Nodes (33): Any, RuntimeError, A connected source rejected its delegated credentials., SourceRemoteUnauthorized, DeltaPage, MicrosoftGraphClient, OneDriveCipher, OneDriveCredentials (+25 more)

### Community 4 - "WorkspaceFolder"
Cohesion: 0.12
Nodes (50): _is_document_inventory_question(), Protocol, Session, QuestionService, SemanticProvider, WorkspaceFolder, LogCaptureFixture, ask() (+42 more)

### Community 5 - "integrations.py"
Cohesion: 0.11
Nodes (49): callback(), disconnect_source(), FolderInput, folders(), notion_callback(), notion_service(), onedrive_callback(), onedrive_service() (+41 more)

### Community 6 - "WorkspaceService"
Cohesion: 0.09
Nodes (25): create_saved_query(), delete_saved_query(), list_saved_queries(), BaseModel, delete, get, patch, post (+17 more)

### Community 7 - "ingestion/service.py"
Cohesion: 0.13
Nodes (35): ask_organization_question(), ask_question(), document_failures(), documents(), enqueue_sync(), BaseModel, delete, get (+27 more)

### Community 8 - "test_google_drive_connection.py"
Cohesion: 0.11
Nodes (16): CredentialCipher, GoogleConnectionService, GoogleOAuthInvalid, Session, UUID, ValueError, active_member(), FakeGooglePort (+8 more)

### Community 9 - "PlatformStaffAccessService"
Cohesion: 0.13
Nodes (21): get, Session, UUID, Platform-staff support endpoints, deliberately separate from tenant APIs., supported_companies(), supported_company_overview(), An expiring metadata-only support grant for exactly one tenant., StaffAccessGrant (+13 more)

### Community 10 - "Document"
Cohesion: 0.20
Nodes (33): ProcessingJobStatus, str, DiscoveredDocument, Extracted content returned by an authorized source adapter., Document, Requires TEST_DATABASE_URL to be a dedicated disposable PostgreSQL database., run_alembic(), test_foundation_migration_applies_and_reverts_on_disposable_postgres() (+25 more)

### Community 11 - "GoogleCredentials"
Cohesion: 0.12
Nodes (10): GoogleCredentials, GoogleDriveOAuthClient, Response, List files in a selected folder and all descendants without retaining bytes., RemoteFile, FakeGooglePort, MonkeyPatch, test_google_client_marks_unauthorized_account_metadata_as_remote_unauthorized() (+2 more)

### Community 12 - "LibraryService"
Cohesion: 0.14
Nodes (14): LibraryNode, BrowsePage, LibraryContext, LibraryService, LibrarySync, Session, UUID, Return only sync-scope UUIDs that currently index this file. The tree itself is… (+6 more)

### Community 13 - "test_google_integrations.py"
Cohesion: 0.15
Nodes (30): create_organization(), google_api(), login(), fixture, parametrize, Session, sessionmaker, TestClient (+22 more)

### Community 14 - "test_text_search_api.py"
Cohesion: 0.18
Nodes (26): corpus(), fixture, create_organization(), FakeIngestionDispatcher, FakeSemanticProvider, login(), fixture, MonkeyPatch (+18 more)

### Community 15 - "WorkspaceFolderSelection"
Cohesion: 0.20
Nodes (22): GoogleDriveDocumentProvider, Fetch an authorized scope union, then retain extracted text only in the DB., GoogleRemoteUnauthorized, One Google Drive root contributing to a logical workspace.…, WorkspaceFolderSelection, docx_bytes(), encrypted_credentials(), FakeGoogleDriveClient (+14 more)

### Community 16 - "test_text_search.py"
Cohesion: 0.18
Nodes (24): _excerpt(), RuntimeError, Session, UUID, Folder-scoped textual retrieval with a PostgreSQL FTS fast path., SearchUnavailable, TextSearchHit, TextSearchPage (+16 more)

### Community 17 - "IngestionService"
Cohesion: 0.19
Nodes (10): UsageService, ProcessingJob, IngestionService, datetime, Session, Atomically reserve a queued or abandoned job for one worker., Apply one successful full reconciliation. A source failure must call…, Persist a discovered snapshot only while this worker owns the job. (+2 more)

### Community 18 - "DocumentChunk"
Cohesion: 0.19
Nodes (21): DocumentChunk, _embedding_input(), EmbeddingService, Create vectors only for chunks already isolated to one workspace., Use document/section context for vectors while keeping citations verbatim., document(), FakeEmbeddingProvider, finish_sync() (+13 more)

### Community 19 - "tasks.py"
Cohesion: 0.16
Nodes (18): get_settings(), build_engine(), build_session_factory(), Session, sessionmaker, session_dependency(), create_celery_app(), Celery (+10 more)

### Community 20 - "login"
Cohesion: 0.14
Nodes (19): connect_onedrive(), create_organization(), FakeAuthGateway, login(), onedrive_api(), fixture, MonkeyPatch, Session (+11 more)

### Community 21 - "questions.py"
Cohesion: 0.19
Nodes (19): _cosine_similarity(), _deduplicate_indexed_copies(), _document_inventory_evidence(), _document_recency(), _estimated_tokens(), _evidence_context_chars(), _has_distinctive_exact_term(), _hybrid_score() (+11 more)

### Community 22 - "OrganizationScope"
Cohesion: 0.27
Nodes (6): select(), OrganizationScope, UUID, Delete one confirmed local knowledge scope, never its Drive source., Aggregate safe failure codes for platform support without exposing files., Return only operational folder metadata after platform grant authorization.

### Community 23 - "test_onedrive_delta_cursor_commits_with_successful_ingestion"
Cohesion: 0.09
Nodes (3): test_onedrive_delta_cursor_commits_with_successful_ingestion(), scalars(), types

### Community 24 - "NotionOAuthClient"
Cohesion: 0.14
Nodes (9): NotionOAuthClient, Session, Read a page's block tree, including toggles, columns and child pages. Notion…, MonkeyPatch, test_notion_authorization_url_contains_state_and_redirect(), test_notion_client_reads_the_oauth_owner_email_from_its_bot_profile(), request(), test_notion_page_blocks_include_nested_children() (+1 more)

### Community 25 - "RemoteFolder"
Cohesion: 0.12
Nodes (8): Return safe folder metadata for the Company Library projection. This is…, GoogleDrivePort, Protocol, RemoteFolder, NotionDocumentProvider, read_page(), PostgreSQLGooglePort, test_postgres_source_and_workspace_folder_are_tenant_scoped_and_idempotent()

### Community 26 - "AIProviderUnavailable"
Cohesion: 0.13
Nodes (11): AIProviderRateLimited, AIProviderUnavailable, GeneratedAnswer, Response, RuntimeError, Read output text from the raw Responses REST envelope, not SDK conveniences., _response_output_text(), _retry_after_seconds() (+3 more)

### Community 27 - "Evidence"
Cohesion: 0.18
Nodes (15): _answer_without_source_links(), Strip accidental model-generated URLs; source links belong to citations., Retain link labels while consuming balanced URL parentheses., _remove_url_preserving_punctuation(), _strip_markdown_links(), Evidence, _number_answer_sources(), Translate selected evidence markers to the visible document-list ordinals. (+7 more)

### Community 28 - "Settings"
Cohesion: 0.18
Nodes (9): Runtime configuration with no permissive production defaults., Settings, NotionProviderAdapter, OneDriveProviderAdapter, BaseSettings, _options_request(), MonkeyPatch, test_pilot_api_allows_only_configured_browser_origin() (+1 more)

### Community 29 - "typing"
Cohesion: 0.14
Nodes (10): CeleryIngestionDispatcher, IngestionDispatcher, Celery, Protocol, UUID, Celery dispatch boundary used by the API after a sync job is committed., Outbound invitation delivery boundary., ResendInvitationDelivery (+2 more)

### Community 30 - "test_multiscope_questions_api.py"
Cohesion: 0.24
Nodes (16): ask(), parametrize, Independent HTTP regressions for authorized cross-tool retrieval., test_answer_links_are_removed_but_document_references_keep_original_urls(), test_broad_scope_quota_blocks_model_and_preserves_counter(), test_empty_or_pending_context_is_safe_without_model(), test_foreign_source_join_cannot_supply_evidence_or_provider_metadata(), test_invalid_scope_is_rejected_before_generation() (+8 more)

### Community 31 - "test_exhausted_embedding_rate_limit_rolls_back_and_marks_job_failed"
Cohesion: 0.12
Nodes (5): MonkeyPatch, The Celery boundary must retain the prior committed snapshot on a 429., test_exhausted_embedding_rate_limit_rolls_back_and_marks_job_failed(), discover(), scalars()

### Community 32 - "ingestion/google_drive.py"
Cohesion: 0.14
Nodes (15): _extract_blocks(), _extract_text(), _markdown_blocks(), Google Drive discovery and text extraction behind the ingestion boundary., docx, docx_opc_exceptions, docx_oxml_table, docx_oxml_text_paragraph (+7 more)

### Community 33 - "registry.py"
Cohesion: 0.20
Nodes (11): DiscoveryResult, Either a complete scope snapshot or one provider's incremental delta., ProviderCapabilities, ProviderNotConfigured, Protocol, RuntimeError, Provider-neutral contracts for external knowledge sources., SourceProvider (+3 more)

### Community 34 - "test_structured_logging.py"
Cohesion: 0.23
Nodes (11): database_is_ready(), Perform one bounded non-sensitive database query for readiness., event_record(), ListHandler, make_application(), LogRecord, TestClient, Build the app with a non-connecting PostgreSQL URL for middleware tests. (+3 more)

### Community 35 - "os"
Cohesion: 0.18
Nodes (9): Config, os, pathlib, subprocess, sys, fixture, pytest_configure(), Return the explicitly configured disposable PostgreSQL database URL.… (+1 more)

### Community 36 - "logging.py"
Cohesion: 0.26
Nodes (8): configure_observability(), JsonFormatter, LogRecord, Serialize approved operational fields without logging request content or…, parametrize, test_google_connection_logs_render_operational_fields_without_oauth_secrets(), test_json_logging_does_not_emit_auth_or_invitation_secrets(), test_json_formatter_allows_safe_retrieval_metrics_without_serializing_content()

### Community 37 - "config.py"
Cohesion: 0.24
Nodes (9): app_api, functools, pydantic, pydantic_settings, make_health_client(), TestClient, test_liveness_returns_ok_without_database_dependency(), test_readiness_failure_is_explainable_without_leaking_driver_details() (+1 more)

### Community 38 - "library.py"
Cohesion: 0.47
Nodes (10): library_children(), library_question_contexts(), library_roots(), library_search(), library_syncs(), _node(), get, Session (+2 more)

### Community 39 - "NotionPage"
Cohesion: 0.22
Nodes (8): NotionPage, test_notion_discover_reads_pages_concurrently_with_stable_order(), decrypt(), list_pages(), test_notion_discover_skips_empty_metadata_pages(), decrypt(), list_pages(), test_notion_page_keeps_source_metadata()

### Community 40 - "seed_library"
Cohesion: 0.42
Nodes (11): api(), login(), fixture, MonkeyPatch, Session, sessionmaker, TestClient, seed_library() (+3 more)

### Community 41 - "test_projects_nested_drive_tree_and_merges_overlapping_syncs"
Cohesion: 0.47
Nodes (9): fixture, seed_company(), seed_document(), session(), test_children_are_bounded_and_stably_paged(), test_library_metadata_search_and_sync_statuses_are_member_scoped(), test_projection_excludes_nonindexed_files_and_isolates_organizations(), test_projection_refreshes_remote_folder_names_and_parents() (+1 more)

### Community 44 - "GoogleOAuthUnavailable"
Cohesion: 0.43
Nodes (3): GoogleOAuthUnavailable, RuntimeError, UnconfiguredGoogleDrivePort

### Community 46 - "20260913_0012_company_library.py"
Cohesion: 0.60
Nodes (3): _offline_backfill(), _online_backfill(), upgrade()

### Community 47 - "readiness"
Cohesion: 0.40
Nodes (5): liveness(), get, Request, readiness(), JSONResponse

### Community 48 - "ExtractedBlock"
Cohesion: 0.50
Nodes (5): _chunk_block(), _chunk_document(), ExtractedBlock, A structurally bounded piece of extracted text and its known location., Pack paragraph/sentence units to a conservative word-token budget. This avoids…

### Community 50 - "RequestLogMiddleware"
Cohesion: 0.50
Nodes (3): Request, RequestLogMiddleware, BaseHTTPMiddleware

## Knowledge Gaps
- **2 isolated node(s):** `document-intelligence-api`, `start-render-api.sh script`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 370 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **27 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `OrganizationScope` connect `OrganizationScope` to `DataSource`, `User`, `MembershipRole`, `WorkspaceFolder`, `integrations.py`, `WorkspaceService`, `ingestion/service.py`, `test_google_drive_connection.py`, `PlatformStaffAccessService`, `Document`, `LibraryService`, `test_text_search.py`, `IngestionService`, `DocumentChunk`, `tasks.py`, `questions.py`, `RemoteFolder`, `library.py`, `test_projects_nested_drive_tree_and_merges_overlapping_syncs`?**
  _High betweenness centrality (0.146) - this node is a cross-community bridge._
- **Why does `User` connect `User` to `DataSource`, `MembershipRole`, `WorkspaceFolder`, `integrations.py`, `library.py`, `ingestion/service.py`, `WorkspaceService`, `PlatformStaffAccessService`, `seed_library`, `Document`, `test_projects_nested_drive_tree_and_merges_overlapping_syncs`, `test_google_integrations.py`, `test_text_search_api.py`, `test_text_search.py`, `DocumentChunk`, `login`, `OrganizationScope`, `test_multiscope_questions_api.py`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Why does `GoogleCredentials` connect `GoogleCredentials` to `ingestion/google_drive.py`, `DataSource`, `NotionPage`, `test_google_drive_connection.py`, `GoogleOAuthUnavailable`, `test_google_integrations.py`, `test_google_client_lists_direct_root_files_with_pagination`, `WorkspaceFolderSelection`, `NotionOAuthClient`, `RemoteFolder`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Are the 50 inferred relationships involving `OrganizationScope` (e.g. with `create_invitation()` and `deactivate_membership()`) actually correct?**
  _`OrganizationScope` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Are the 130 inferred relationships involving `select()` (e.g. with `OrganizationScope` and `User`) actually correct?**
  _`select()` has 130 INFERRED edges - model-reasoned connections that need verification._
- **Are the 68 inferred relationships involving `User` (e.g. with `accept_invitation()` and `create_invitation()`) actually correct?**
  _`User` has 68 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `WorkspaceFolder` (e.g. with `IngestionService` and `reconcile_workspace_folder()`) actually correct?**
  _`WorkspaceFolder` has 27 INFERRED edges - model-reasoned connections that need verification._