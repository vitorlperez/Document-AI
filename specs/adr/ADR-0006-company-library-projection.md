# ADR-0006: Company Library as a provider-neutral projection

## Status

Accepted

## Context

Drive selections are synchronization scopes, not separate companies or separate bodies of knowledge. A Company can select overlapping folders today and will add other providers later. Rendering each synchronization as an isolated workspace makes duplicated files, disconnected navigation and future multi-source browsing inevitable.

The product needs one Company Library with Finder-style navigation, while preserving the established authorization rule: stored document content, lexical search and RAG remain scoped by both organization and workspace folder.

## Decision

Create a `library` module that owns a provider-neutral, organization-scoped read projection. A library node has a local UUID, source UUID, opaque provider external ID, parent UUID, kind (`source`, `folder`, or `file`), and safe display metadata. The ingestion workflow updates this projection only from selected documents and their ancestor folder metadata after a successful reconciliation.

The Company Library deduplicates a remote item by `(source_id, external_id)`. `workspace_folder_id` remains in the document store for synchronization lifecycle, auditing, and scoped retrieval; it is exposed only as provenance, not as the primary visual hierarchy. The initial browser lists indexed file nodes and their ancestor folders. Older documents with no path node are safely listed below their source root.

## Consequences

- A second sync that overlaps an earlier one enriches the same Company Library tree rather than creating another visual data silo.
- Future providers implement the same projection contract without changing browser URLs, which use local UUIDs.
- Library browsing is organization-scoped and membership-checked. It does not relax the `organization_id + workspace_folder_id` boundary of search or questions; a separate approved feature is required for company-wide retrieval.
- Folder discovery adds metadata work to a successful source sync. Child browsing is paged and indexed by parent to keep it bounded.
