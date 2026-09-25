"""Company-scoped Library projection and browse boundary."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import case, exists, func, select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.ingestion.service import DiscoveredDocument, SyncAccessDenied
from app.integrations.google_drive import RemoteFolder
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL
from app.library.models import LibraryNode
from app.organizations.models import Membership
from app.workspaces.models import WorkspaceFolder

SOURCE_ROOT_EXTERNAL_ID = "__company_library_source_root__"
PAGE_SIZE_MAX = 100
SEARCH_RESULT_LIMIT = 50
SYNC_RESULT_LIMIT = 20


@dataclass(frozen=True)
class BrowsePage:
    items: list[LibraryNode]
    page: int
    page_size: int
    total: int

    @property
    def pages(self) -> int:
        return max(1, (self.total + self.page_size - 1) // self.page_size)


@dataclass(frozen=True)
class LibraryContext:
    id: UUID
    name: str
    status: str
    source_id: UUID
    source_provider: str
    query_status: str


@dataclass(frozen=True)
class LibrarySync:
    id: UUID
    source_id: UUID
    workspace_folder_id: UUID
    workspace_name: str
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None


@dataclass(frozen=True)
class IndexedDocumentProvenance:
    """A workspace-scoped local document behind a shared library file."""

    workspace_folder_id: UUID
    document_id: UUID


class LibraryService:
    def __init__(self, session: Session):
        self.session = session

    def require_member(self, *, scope: OrganizationScope, user_id: UUID) -> None:
        member = self.session.scalar(
            select(Membership).where(
                Membership.organization_id == scope.organization_id,
                Membership.user_id == user_id,
                Membership.is_active.is_(True),
            )
        )
        if member is None:
            raise SyncAccessDenied("company library access denied")

    def roots(self, *, scope: OrganizationScope, user_id: UUID) -> list[LibraryNode]:
        self.require_member(scope=scope, user_id=user_id)
        return list(
            self.session.scalars(
                select(LibraryNode)
                .where(
                    LibraryNode.organization_id == scope.organization_id,
                    LibraryNode.kind == "source",
                )
                .order_by(LibraryNode.name, LibraryNode.id)
            )
        )

    def source_providers(self, *, scope: OrganizationScope, user_id: UUID) -> dict[UUID, str]:
        """Return provider keys for this member's organization-scoped library roots."""
        self.require_member(scope=scope, user_id=user_id)
        rows = self.session.execute(
            select(DataSource.id, DataSource.provider).where(DataSource.organization_id == scope.organization_id)
        )
        return {source_id: provider for source_id, provider in rows}

    def children(
        self, *, scope: OrganizationScope, user_id: UUID, parent_id: UUID, page: int, page_size: int
    ) -> BrowsePage:
        self.require_member(scope=scope, user_id=user_id)
        parent = self.session.scalar(
            select(LibraryNode).where(
                LibraryNode.id == parent_id,
                LibraryNode.organization_id == scope.organization_id,
            )
        )
        if parent is None or parent.kind == "file":
            raise SyncAccessDenied("company library node unavailable")
        statement = select(LibraryNode).where(
            LibraryNode.organization_id == scope.organization_id,
            LibraryNode.parent_id == parent.id,
        )
        total = int(self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
        items = list(
            self.session.scalars(
                statement.order_by(
                    LibraryNode.kind.desc(), LibraryNode.name, LibraryNode.id
                ).offset((page - 1) * page_size).limit(page_size)
            )
        )
        return BrowsePage(items=items, page=page, page_size=page_size, total=total)

    def workspace_provenance(self, *, scope: OrganizationScope, node: LibraryNode) -> list[UUID]:
        """Return only sync-scope UUIDs that currently index this file.

        The tree itself is provider-centric; this metadata makes an overlap
        auditable without turning each synchronization back into a visual silo.
        """
        if node.kind != "file":
            return []
        return list(
            self.session.scalars(
                select(Document.workspace_folder_id)
                .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
                .where(
                    Document.organization_id == scope.organization_id,
                    WorkspaceFolder.source_id == node.source_id,
                    Document.external_file_id == node.external_id,
                    Document.index_status == "indexed",
                )
                .distinct()
                .order_by(Document.workspace_folder_id)
            )
        )

    def document_provenance(
        self, *, scope: OrganizationScope, node: LibraryNode
    ) -> list[IndexedDocumentProvenance]:
        """Expose only local UUIDs used for authorized file management actions."""
        if node.kind != "file":
            return []
        return [
            IndexedDocumentProvenance(workspace_folder_id=workspace_folder_id, document_id=document_id)
            for workspace_folder_id, document_id in self.session.execute(
                select(Document.workspace_folder_id, Document.id)
                .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
                .where(
                    Document.organization_id == scope.organization_id,
                    WorkspaceFolder.organization_id == scope.organization_id,
                    WorkspaceFolder.source_id == node.source_id,
                    Document.external_file_id == node.external_id,
                    Document.index_status == "indexed",
                )
                .order_by(Document.workspace_folder_id, Document.id)
            )
        ]

    def remove_file_if_unindexed(
        self, *, scope: OrganizationScope, source_id: UUID, external_file_id: str
    ) -> None:
        """Remove a projected file only after its final local index copy disappears."""
        still_indexed = self.session.scalar(
            select(Document.id)
            .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
            .where(
                Document.organization_id == scope.organization_id,
                WorkspaceFolder.organization_id == scope.organization_id,
                WorkspaceFolder.source_id == source_id,
                Document.external_file_id == external_file_id,
                Document.index_status == "indexed",
            )
            .limit(1)
        )
        if still_indexed is not None:
            return
        node = self._by_external(source_id=source_id, external_id=external_file_id)
        if node is not None and node.organization_id == scope.organization_id and node.kind == "file":
            self.session.delete(node)
            self.session.flush()
            self._remove_empty_folders(source_id=source_id)
            self.session.flush()

    def remove_files_if_unindexed(
        self, *, scope: OrganizationScope, source_id: UUID, external_file_ids: tuple[str, ...]
    ) -> None:
        """Prune local file nodes after a whole workspace scope is removed."""
        if not external_file_ids:
            return
        still_indexed = set(
            self.session.scalars(
                select(Document.external_file_id)
                .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
                .where(
                    Document.organization_id == scope.organization_id,
                    WorkspaceFolder.organization_id == scope.organization_id,
                    WorkspaceFolder.source_id == source_id,
                    Document.external_file_id.in_(external_file_ids),
                    Document.index_status == "indexed",
                )
                .distinct()
            )
        )
        stale_nodes = self.session.scalars(
            select(LibraryNode).where(
                LibraryNode.organization_id == scope.organization_id,
                LibraryNode.source_id == source_id,
                LibraryNode.kind == "file",
                LibraryNode.external_id.in_(external_file_ids),
            )
        )
        for node in stale_nodes:
            if node.external_id not in still_indexed:
                self.session.delete(node)
        self.session.flush()
        self._remove_empty_folders(source_id=source_id)
        self.session.flush()

    def search_names(
        self, *, scope: OrganizationScope, user_id: UUID, query: str, limit: int = SEARCH_RESULT_LIMIT
    ) -> list[LibraryNode]:
        self.require_member(scope=scope, user_id=user_id)
        normalized = query.strip()
        if not normalized or len(normalized) > 500:
            raise ValueError("query must contain between 1 and 500 characters")
        return list(
            self.session.scalars(
                select(LibraryNode)
                .where(
                    LibraryNode.organization_id == scope.organization_id,
                    LibraryNode.kind.in_(["folder", "file"]),
                    func.lower(LibraryNode.name).contains(normalized.lower(), autoescape=True),
                )
                .order_by(LibraryNode.kind.desc(), LibraryNode.name, LibraryNode.id)
                .limit(limit)
            )
        )

    def question_contexts(self, *, scope: OrganizationScope, user_id: UUID) -> list[LibraryContext]:
        self.require_member(scope=scope, user_id=user_id)
        indexed_chunks = exists(
            select(DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.organization_id == scope.organization_id,
                Document.workspace_folder_id == WorkspaceFolder.id,
                Document.index_status == "indexed",
                DocumentChunk.organization_id == scope.organization_id,
                DocumentChunk.workspace_folder_id == WorkspaceFolder.id,
            )
        )
        compatible_embeddings = exists(
            select(DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.organization_id == scope.organization_id,
                Document.workspace_folder_id == WorkspaceFolder.id,
                Document.index_status == "indexed",
                DocumentChunk.organization_id == scope.organization_id,
                DocumentChunk.workspace_folder_id == WorkspaceFolder.id,
                DocumentChunk.embedding.is_not(None),
                DocumentChunk.embedding_model == EMBEDDING_MODEL,
            )
        )
        return [
            LibraryContext(
                id=folder.id,
                name=folder.name,
                status=folder.status,
                source_id=folder.source_id,
                source_provider=source.provider,
                query_status=("not_ready" if folder.status not in {"ready", "partial_failure"}
                              else "ready" if has_embeddings else "no_indexed_content" if not has_content
                              else "no_compatible_embeddings"),
            )
            for folder, source, has_content, has_embeddings in self.session.execute(
                select(WorkspaceFolder, DataSource, indexed_chunks.label("has_content"), compatible_embeddings.label("has_embeddings"))
                .join(DataSource, DataSource.id == WorkspaceFolder.source_id)
                .where(
                    WorkspaceFolder.organization_id == scope.organization_id,
                    DataSource.organization_id == scope.organization_id,
                )
                .order_by(WorkspaceFolder.name, WorkspaceFolder.id)
            ).all()
        ]

    def recent_syncs(self, *, scope: OrganizationScope, user_id: UUID) -> list[LibrarySync]:
        self.require_member(scope=scope, user_id=user_id)
        rows = self.session.execute(
            select(ProcessingJob, WorkspaceFolder)
            .join(WorkspaceFolder, WorkspaceFolder.id == ProcessingJob.workspace_folder_id)
            .where(
                ProcessingJob.organization_id == scope.organization_id,
                WorkspaceFolder.organization_id == scope.organization_id,
            )
            .order_by(
                case(
                    (ProcessingJob.status.in_([ProcessingJobStatus.QUEUED, ProcessingJobStatus.SYNCING]), 0),
                    else_=1,
                ),
                ProcessingJob.created_at.desc(),
                ProcessingJob.id.desc(),
            )
            .limit(SYNC_RESULT_LIMIT)
        )
        return [
            LibrarySync(
                id=job.id,
                source_id=folder.source_id,
                workspace_folder_id=folder.id,
                workspace_name=folder.name,
                status=job.status.value,
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                error_code=job.error_code,
            )
            for job, folder in rows
        ]

    def project_successful_sync(
        self,
        *,
        organization_id: UUID,
        source: DataSource,
        documents: list[DiscoveredDocument],
        folders: list[RemoteFolder],
    ) -> None:
        """Upsert only content that reconciled into the document store.

        This deliberately receives provider-neutral values. A new connector only
        needs to supply opaque IDs and parent relationships.
        """
        root = self._root(organization_id=organization_id, source=source)
        folder_by_id = {folder.id: folder for folder in folders}
        for remote_folder in folders:
            self._folder(
                organization_id=organization_id,
                source_id=source.id,
                root=root,
                external_id=remote_folder.id,
                folder_by_id=folder_by_id,
                visited=set(),
            )
        indexed_ids = set(
            self.session.scalars(
                select(Document.external_file_id)
                .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
                .where(
                    Document.organization_id == organization_id,
                    WorkspaceFolder.source_id == source.id,
                    Document.index_status == "indexed",
                )
            )
        )
        for document in documents:
            if document.external_file_id not in indexed_ids:
                continue
            parent = self._folder_parent(
                organization_id=organization_id,
                source_id=source.id,
                root=root,
                parent_ids=document.parent_ids,
                folder_by_id=folder_by_id,
            )
            node = self._by_external(source_id=source.id, external_id=document.external_file_id)
            if node is None:
                node = LibraryNode(
                    organization_id=organization_id,
                    source_id=source.id,
                    parent_id=parent.id,
                    external_id=document.external_file_id,
                    kind="file",
                    name=document.name,
                    mime_type=document.mime_type,
                    source_url=document.source_url,
                )
                self.session.add(node)
            else:
                node.parent_id, node.name, node.mime_type, node.source_url = (
                    parent.id,
                    document.name,
                    document.mime_type,
                    document.source_url,
                )
        # A remote item may leave one sync scope. Keep it while any other
        # scope of this same source still indexes it; remove it only after the
        # last eligible copy disappears from the document store.
        for node in self.session.scalars(
            select(LibraryNode).where(LibraryNode.source_id == source.id, LibraryNode.kind == "file")
        ):
            if node.external_id not in indexed_ids:
                self.session.delete(node)
        self.session.flush()
        self._remove_empty_folders(source_id=source.id)
        self.session.flush()

    def _root(self, *, organization_id: UUID, source: DataSource) -> LibraryNode:
        root = self._by_external(source_id=source.id, external_id=SOURCE_ROOT_EXTERNAL_ID)
        provider_name = {
            "google_drive": "Google Drive",
            "notion": "Notion",
            "onedrive": "OneDrive",
        }.get(source.provider, source.provider.replace("_", " ").title())
        if root is None:
            root = LibraryNode(
                organization_id=organization_id,
                source_id=source.id,
                parent_id=None,
                external_id=SOURCE_ROOT_EXTERNAL_ID,
                kind="source",
                name=provider_name,
                mime_type=None,
                source_url=None,
            )
            self.session.add(root)
            self.session.flush()
        return root

    def _folder_parent(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        root: LibraryNode,
        parent_ids: tuple[str, ...],
        folder_by_id: dict[str, RemoteFolder],
    ) -> LibraryNode:
        parent_external_id = next((item for item in parent_ids if item != "root"), None)
        if parent_external_id is None:
            return root
        return self._folder(
            organization_id=organization_id,
            source_id=source_id,
            root=root,
            external_id=parent_external_id,
            folder_by_id=folder_by_id,
            visited=set(),
        )

    def _folder(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        root: LibraryNode,
        external_id: str,
        folder_by_id: dict[str, RemoteFolder],
        visited: set[str],
    ) -> LibraryNode:
        existing = self._by_external(source_id=source_id, external_id=external_id)
        if external_id in visited:
            return existing or root
        visited.add(external_id)
        remote = folder_by_id.get(external_id)
        if remote is None:
            return existing or root
        parent_external_id = next((item for item in remote.parent_ids if item != "root" and item not in visited), None)
        parent = (
            self._folder(
                organization_id=organization_id,
                source_id=source_id,
                root=root,
                external_id=parent_external_id,
                folder_by_id=folder_by_id,
                visited=visited,
            )
            if parent_external_id is not None
            else root
        )
        if existing is not None:
            existing.parent_id = parent.id
            existing.name = remote.name
            return existing
        node = LibraryNode(
            organization_id=organization_id,
            source_id=source_id,
            parent_id=parent.id,
            external_id=external_id,
            kind="folder",
            name=remote.name,
            mime_type=None,
            source_url=None,
        )
        self.session.add(node)
        self.session.flush()
        return node

    def _by_external(self, *, source_id: UUID, external_id: str) -> LibraryNode | None:
        return self.session.scalar(
            select(LibraryNode).where(
                LibraryNode.source_id == source_id,
                LibraryNode.external_id == external_id,
            )
        )

    def _remove_empty_folders(self, *, source_id: UUID) -> None:
        """Prune only orphaned folder metadata, never a source root."""
        while True:
            empty = [
                node
                for node in self.session.scalars(
                    select(LibraryNode).where(LibraryNode.source_id == source_id, LibraryNode.kind == "folder")
                )
                if self.session.scalar(select(LibraryNode.id).where(LibraryNode.parent_id == node.id).limit(1)) is None
            ]
            if not empty:
                return
            for node in empty:
                self.session.delete(node)
            self.session.flush()
