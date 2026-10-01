"""Company-scoped Library projection and browse boundary."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import case, delete, exists, func, select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.ingestion.service import DiscoveredDocument, SyncAccessDenied
from app.integrations.google_drive import RemoteFolder
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL
from app.library.models import LibraryExclusion, LibraryNode
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


@dataclass(frozen=True)
class CatalogFileSnapshot:
    id: UUID
    name: str
    index_status: str
    excerpt: str | None
    document_id: UUID | None = None
    source_url: str | None = None
    source_provider: str | None = None
    # Leading indexed (embedded) chunks of the file, in document order; the input of a per-file summary.
    chunks: tuple[str, ...] = ()


# Bounds on the chunks a catalog snapshot carries for a per-file summary.
SNAPSHOT_MAX_CHUNKS = 6
SNAPSHOT_MAX_CHUNK_CHARS = 6000


@dataclass(frozen=True)
class MentionCandidate:
    node: LibraryNode
    source_provider: str
    path: str
    query_status: str


@dataclass(frozen=True)
class QuestionSelection:
    folder_ids: list[UUID]
    document_ids: set[UUID] | None
    coverage: dict[str, int]
    accepted_node_ids: list[UUID]


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

    def indexed_documents_under(
        self, *, scope: OrganizationScope, user_id: UUID, node_id: UUID, allow_source: bool = False
    ) -> list[IndexedDocumentProvenance]:
        """Indexed documents of every file below one folder node (any depth)."""
        self.require_member(scope=scope, user_id=user_id)
        folder = self.session.scalar(
            select(LibraryNode).where(
                LibraryNode.id == node_id,
                LibraryNode.organization_id == scope.organization_id,
                LibraryNode.kind.in_(["folder", "source"] if allow_source else ["folder"]),
            )
        )
        if folder is None:
            raise SyncAccessDenied("company library node unavailable")
        files: list[LibraryNode] = []
        pending = [folder.id]
        while pending:
            children = list(
                self.session.scalars(
                    select(LibraryNode).where(
                        LibraryNode.organization_id == scope.organization_id,
                        LibraryNode.parent_id.in_(pending),
                    )
                )
            )
            files.extend(child for child in children if child.kind == "file")
            pending = [child.id for child in children if child.kind == "folder"]
        documents = self.documents_for_nodes(scope=scope, nodes=files)
        return [reference for references in documents.values() for reference in references]

    def remove_folder_catalog(self, *, scope: OrganizationScope, node_id: UUID) -> None:
        """Remove only the explicitly selected local subtree, retaining siblings and source."""
        node = self.session.scalar(select(LibraryNode).where(
            LibraryNode.id == node_id,
            LibraryNode.organization_id == scope.organization_id,
            LibraryNode.kind == "folder",
        ))
        if node is None:
            raise SyncAccessDenied("company library node unavailable")
        levels = [[node.id]]
        while children := list(self.session.scalars(select(LibraryNode.id).where(
            LibraryNode.organization_id == scope.organization_id,
            LibraryNode.source_id == node.source_id,
            LibraryNode.parent_id.in_(levels[-1]),
        ))):
            levels.append(children)
        nodes = list(self.session.scalars(select(LibraryNode).where(
            LibraryNode.organization_id == scope.organization_id,
            LibraryNode.source_id == node.source_id,
            LibraryNode.id.in_([item for level in levels for item in level]),
        )))
        self._remember_exclusions(scope=scope, source_id=node.source_id,
                                  items={item.external_id: item.kind for item in nodes})
        # Children first also works with databases enforcing immediate foreign keys.
        for ids in reversed(levels):
            self.session.execute(delete(LibraryNode).where(
                LibraryNode.organization_id == scope.organization_id,
                LibraryNode.source_id == node.source_id,
                LibraryNode.id.in_(ids),
            ))
        self.session.flush()

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

    def documents_for_nodes(
        self, *, scope: OrganizationScope, nodes: list[LibraryNode]
    ) -> dict[UUID, list[IndexedDocumentProvenance]]:
        """Load indexed document references for a browse page in one query."""
        files = [node for node in nodes if node.kind == "file"]
        if not files:
            return {}
        node_ids_by_source_external: dict[tuple[UUID, str], list[UUID]] = {}
        for node in files:
            node_ids_by_source_external.setdefault((node.source_id, node.external_id), []).append(node.id)
        result: dict[UUID, list[IndexedDocumentProvenance]] = {}
        rows = self.session.execute(
            select(
                WorkspaceFolder.source_id, Document.external_file_id,
                Document.workspace_folder_id, Document.id,
            )
            .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
            .where(
                Document.organization_id == scope.organization_id,
                WorkspaceFolder.organization_id == scope.organization_id,
                WorkspaceFolder.source_id.in_({node.source_id for node in files}),
                Document.external_file_id.in_({node.external_id for node in files}),
                Document.index_status == "indexed",
            )
            .order_by(Document.workspace_folder_id, Document.id)
        )
        for source_id, external_id, workspace_folder_id, document_id in rows:
            for node_id in node_ids_by_source_external.get((source_id, external_id), []):
                result.setdefault(node_id, []).append(
                    IndexedDocumentProvenance(workspace_folder_id, document_id)
                )
        return result

    def remove_file_if_unindexed(
        self, *, scope: OrganizationScope, source_id: UUID, external_file_id: str
    ) -> None:
        """Remove the last local copy and permanently exclude its provider identity."""
        source = self.session.scalar(
            select(DataSource.id).where(
                DataSource.id == source_id,
                DataSource.organization_id == scope.organization_id,
            )
        )
        if source is None:
            raise SyncAccessDenied("source tenant mismatch")
        indexed = self.session.scalar(select(Document.id).join(
            WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id,
        ).where(
            Document.organization_id == scope.organization_id,
            WorkspaceFolder.organization_id == scope.organization_id,
            WorkspaceFolder.source_id == source_id,
            Document.external_file_id == external_file_id,
            Document.index_status == "indexed",
        ).limit(1))
        if indexed is not None:
            return
        self._remember_exclusions(scope=scope, source_id=source_id, items={external_file_id: "file"})
        self.session.execute(delete(LibraryNode).where(
            LibraryNode.organization_id == scope.organization_id,
            LibraryNode.source_id == source_id,
            LibraryNode.external_id == external_file_id,
            LibraryNode.kind == "file",
        ))
        self.session.flush()

    def remove_files_if_unindexed(
        self, *, scope: OrganizationScope, source_id: UUID, external_file_ids: tuple[str, ...]
    ) -> None:
        """Retain synchronized provider metadata after a workspace is removed."""
        # Deleting a sync workspace is not an explicit removal of provider items.
        if not self.session.scalar(select(DataSource.id).where(
            DataSource.id == source_id, DataSource.organization_id == scope.organization_id,
        )):
            raise SyncAccessDenied("source tenant mismatch")

    def _remember_exclusions(
        self, *, scope: OrganizationScope, source_id: UUID, items: dict[str, str]
    ) -> None:
        existing = set(self.session.scalars(select(LibraryExclusion.external_id).where(
            LibraryExclusion.organization_id == scope.organization_id,
            LibraryExclusion.source_id == source_id,
        )))
        self.session.add_all([LibraryExclusion(organization_id=scope.organization_id,
            source_id=source_id, external_id=external_id, kind=kind)
            for external_id, kind in items.items() if external_id not in existing])
        self.session.flush()

    def filter_excluded_content(
        self, *, organization_id: UUID, source_id: UUID,
        documents: list[DiscoveredDocument], folders: list[RemoteFolder],
        workspace_folder_id: UUID | None = None,
    ) -> tuple[list[DiscoveredDocument], list[RemoteFolder]]:
        """Filter discovery before indexing/projection, including newly discovered descendants.

        A removal binds the sync spaces that existed when it was made. A space
        selected afterwards is a newer explicit choice and sees its whole tree.
        """
        conditions = [
            LibraryExclusion.organization_id == organization_id,
            LibraryExclusion.source_id == source_id,
        ]
        if workspace_folder_id is not None:
            conditions.append(LibraryExclusion.created_at >= select(WorkspaceFolder.created_at).where(
                WorkspaceFolder.id == workspace_folder_id).scalar_subquery())
        exclusions = list(self.session.scalars(select(LibraryExclusion).where(*conditions)))
        if not exclusions:
            return documents, folders
        blocked = {item.external_id for item in exclusions}
        blocked_folders = {item.external_id for item in exclusions if item.kind == "folder"}
        source = self.session.get(DataSource, source_id)
        if source is not None and source.provider == "notion":
            from app.integrations.notion import NOTION_CONTAINER_PREFIX
            blocked_folders.update(NOTION_CONTAINER_PREFIX + id for id in tuple(blocked_folders)
                                   if not id.startswith(NOTION_CONTAINER_PREFIX))
        nodes = list(self.session.scalars(select(LibraryNode).where(
            LibraryNode.organization_id == organization_id, LibraryNode.source_id == source_id,
        )))
        by_id = {node.id: node for node in nodes}
        parents = {node.external_id: (by_id[node.parent_id].external_id,)
                   if node.parent_id in by_id else () for node in nodes if node.kind == "folder"}
        parents.update({folder.id: folder.parent_ids for folder in folders})
        while descendants := {key for key, values in parents.items()
                              if set(values) & blocked_folders} - blocked_folders:
            blocked_folders.update(descendants)
        blocked.update(blocked_folders)
        return (
            [item for item in documents if item.external_file_id not in blocked
             and not set(item.parent_ids) & blocked_folders],
            [folder for folder in folders if folder.id not in blocked],
        )

    def forget_stale_exclusions(self, *, organization_id: UUID, source_id: UUID) -> None:
        """Drop removals that no remaining sync space of the source still honours."""
        oldest_space = self.session.scalar(select(func.min(WorkspaceFolder.created_at)).where(
            WorkspaceFolder.organization_id == organization_id,
            WorkspaceFolder.source_id == source_id,
        ))
        stale = delete(LibraryExclusion).where(
            LibraryExclusion.organization_id == organization_id,
            LibraryExclusion.source_id == source_id,
        )
        if oldest_space is not None:
            stale = stale.where(LibraryExclusion.created_at < oldest_space)
        self.session.execute(stale)
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

    def catalog_children(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str],
        mentions: list[tuple[str, UUID]], parent_id: UUID, page: int, page_size: int,
    ) -> tuple[list[LibraryNode], int]:
        if not 1 <= page <= 10_000 or not 1 <= page_size <= PAGE_SIZE_MAX:
            raise ValueError("invalid direct-child page")
        allowed = self._authorized_catalog_nodes(
            scope=scope, user_id=user_id, providers=providers, mentions=mentions,
        )
        parent = allowed.get(parent_id)
        if parent is None or parent.kind == "file":
            raise SyncAccessDenied("catalog node is outside the authorized selection")
        children = sorted(
            (node for node in allowed.values() if node.parent_id == parent_id),
            key=lambda node: (node.kind != "folder", node.name.casefold(), str(node.id)),
        )
        offset = (page - 1) * page_size
        return children[offset:offset + page_size], len(children)

    def catalog_search(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str],
        mentions: list[tuple[str, UUID]], query: str, limit: int = SEARCH_RESULT_LIMIT,
    ) -> list[LibraryNode]:
        normalized = query.strip().casefold()
        if not normalized or len(normalized) > 500:
            raise ValueError("query must contain between 1 and 500 characters")
        return [
            node for node in sorted(
                self._authorized_catalog_nodes(
                    scope=scope, user_id=user_id, providers=providers, mentions=mentions,
                ).values(),
                key=lambda node: (node.kind != "folder", node.name.casefold(), str(node.id)),
            )
            if node.kind in {"folder", "file"} and normalized in node.name.casefold()
        ][:limit]

    def catalog_file_snapshots(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str], node_ids: list[UUID],
        validate_references: bool = True, inventory_folder_ids: dict[UUID, UUID] | None = None,
    ) -> list[CatalogFileSnapshot]:
        """Reauthorize persisted inventory references before reading local content."""
        self.require_member(scope=scope, user_id=user_id)
        if not node_ids:
            return []
        normalized_providers = {
            "google_drive" if provider == "google" else provider for provider in providers
        }
        nodes = self._selection_nodes(scope=scope)
        sources = {
            source_id: provider
            for source_id, provider in self.session.execute(
                select(DataSource.id, DataSource.provider).where(
                    DataSource.organization_id == scope.organization_id
                )
            )
        }
        ready_sources = set(
            self.session.scalars(
                select(WorkspaceFolder.source_id).where(
                    WorkspaceFolder.organization_id == scope.organization_id,
                    WorkspaceFolder.status.in_(["ready", "partial_failure"]),
                )
            )
        )
        files: list[LibraryNode] = []
        for node_id in node_ids:
            node = nodes.get(node_id)
            inventory_folder = nodes.get(inventory_folder_ids[node_id]) if inventory_folder_ids else None
            if validate_references and (
                node is None
                or node.kind != "file"
                or node.source_id not in ready_sources
                or ("google_drive" if sources.get(node.source_id) == "google" else sources.get(node.source_id))
                not in normalized_providers
                or self._node_path(node, nodes) is None
                or (inventory_folder_ids is not None and (
                    inventory_folder is None
                    or inventory_folder.kind != "folder"
                    or not self._descends_from(node, inventory_folder, nodes)
                ))
            ):
                raise SyncAccessDenied("catalog file is outside the authorized selection")
            if node is None or node.kind != "file":
                raise SyncAccessDenied("catalog file is unavailable")
            files.append(node)
        rows = self.session.execute(
            select(
                WorkspaceFolder.source_id, Document.external_file_id, Document.id,
                Document.source_url, DocumentChunk.text,
            )
            .select_from(Document)
            .outerjoin(
                DocumentChunk,
                DocumentChunk.document_id == Document.id,
            )
            .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
            .where(
                Document.organization_id == scope.organization_id,
                WorkspaceFolder.organization_id == scope.organization_id,
                Document.index_status == "indexed",
                Document.external_file_id.in_({node.external_id for node in files}),
                WorkspaceFolder.source_id.in_({node.source_id for node in files}),
            )
            .order_by(Document.external_file_id, Document.id, DocumentChunk.position)
        )
        indexed: dict[tuple[UUID, str], tuple[UUID, str, str | None]] = {}
        chunks: dict[tuple[UUID, str], list[str]] = {}
        for source_id, external_file_id, document_id, source_url, text in rows:
            key = (source_id, external_file_id)
            first = indexed.setdefault(key, (document_id, source_url, text))
            collected = chunks.setdefault(key, [])
            if (
                first[0] == document_id and text and text.strip()
                and len(collected) < SNAPSHOT_MAX_CHUNKS
                and (not collected or sum(map(len, collected)) + len(text) <= SNAPSHOT_MAX_CHUNK_CHARS)
            ):
                collected.append(text)
        snapshots: list[CatalogFileSnapshot] = []
        for node in files:
            document = indexed.get((node.source_id, node.external_id))
            snapshots.append(
                CatalogFileSnapshot(
                    id=node.id,
                    name=node.name,
                    index_status="indexed" if document is not None else "not_indexed",
                    excerpt=document[2] if document is not None else None,
                    document_id=document[0] if document is not None else None,
                    source_url=(document[1] if document is not None else None) or node.source_url,
                    source_provider=sources.get(node.source_id),
                    chunks=tuple(chunks.get((node.source_id, node.external_id), ())),
                )
            )
        return snapshots

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

    def _indexed_selection_documents(
        self, *, scope: OrganizationScope, folder_ids: list[UUID]
    ) -> list[tuple[UUID, UUID, str]]:
        if not folder_ids:
            return []
        return list(self.session.execute(
            select(Document.id, WorkspaceFolder.source_id, Document.external_file_id)
            .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
            .join(DataSource, DataSource.id == WorkspaceFolder.source_id)
            .where(
                Document.organization_id == scope.organization_id,
                Document.workspace_folder_id.in_(folder_ids),
                Document.index_status == "indexed",
                WorkspaceFolder.organization_id == scope.organization_id,
                WorkspaceFolder.status.in_(["ready", "partial_failure"]),
                DataSource.organization_id == scope.organization_id,
            )
        ))

    def _selection_nodes(self, *, scope: OrganizationScope) -> dict[UUID, LibraryNode]:
        return {node.id: node for node in self.session.scalars(
            select(LibraryNode).join(DataSource, DataSource.id == LibraryNode.source_id).where(
                LibraryNode.organization_id == scope.organization_id,
                DataSource.organization_id == scope.organization_id,
            )
        )}

    def _authorized_catalog_nodes(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str],
        mentions: list[tuple[str, UUID]],
    ) -> dict[UUID, LibraryNode]:
        """Rebuild a catalog authorization set for every tool invocation."""
        selection = self.resolve_question_selection(
            scope=scope, user_id=user_id, providers=providers, mentions=mentions,
        )
        nodes = self._selection_nodes(scope=scope)
        contexts = self.question_contexts(scope=scope, user_id=user_id)
        normalized_providers = {"google_drive" if provider == "google" else provider for provider in providers}
        allowed_sources = {
            context.source_id
            for context in contexts
            if ("google_drive" if context.source_provider == "google" else context.source_provider)
            in normalized_providers
            and context.id in selection.folder_ids
        }
        roots = [nodes[node_id] for node_id in selection.accepted_node_ids]
        allowed: dict[UUID, LibraryNode] = {}
        for node in nodes.values():
            if node.source_id not in allowed_sources:
                continue
            if roots and not any(self._descends_from(node, root, nodes) for root in roots):
                continue
            allowed[node.id] = node
        return allowed

    @staticmethod
    def _node_path(node: LibraryNode, nodes: dict[UUID, LibraryNode]) -> str | None:
        parts = [node.name]
        visited = {node.id}
        current = node
        while current.parent_id is not None:
            parent = nodes.get(current.parent_id)
            if parent is None or parent.source_id != node.source_id or parent.id in visited:
                return None
            visited.add(parent.id)
            parts.append(parent.name)
            current = parent
        return "/".join(reversed(parts)) if current.kind == "source" else None

    @staticmethod
    def _descends_from(node: LibraryNode, ancestor: LibraryNode, nodes: dict[UUID, LibraryNode]) -> bool:
        current = node
        visited: set[UUID] = set()
        while current.id not in visited and current.source_id == ancestor.source_id:
            if current.id == ancestor.id:
                return True
            visited.add(current.id)
            if current.parent_id is None:
                break
            current = nodes.get(current.parent_id)
            if current is None:
                break
        return False

    def mention_candidates(
        self, *, scope: OrganizationScope, user_id: UUID, query: str, limit: int = 20
    ) -> list[MentionCandidate]:
        self.require_member(scope=scope, user_id=user_id)
        normalized = query.strip().casefold()
        if len(normalized) > 500 or not 1 <= limit <= 50:
            raise ValueError("invalid mention search")
        contexts = self.question_contexts(scope=scope, user_id=user_id)
        eligible = [item.id for item in contexts if item.status in {"ready", "partial_failure"}]
        documents = self._indexed_selection_documents(scope=scope, folder_ids=eligible)
        indexed_files = {(source_id, external_id) for _, source_id, external_id in documents}
        nodes = self._selection_nodes(scope=scope)
        indexed_folder_ids: set[UUID] = set()
        for file in nodes.values():
            if file.kind != "file" or (file.source_id, file.external_id) not in indexed_files:
                continue
            current = file
            visited = {file.id}
            while current.parent_id is not None:
                parent = nodes.get(current.parent_id)
                if parent is None or parent.source_id != file.source_id or parent.id in visited:
                    break
                if parent.kind == "folder":
                    indexed_folder_ids.add(parent.id)
                visited.add(parent.id)
                current = parent
        providers = {item.source_id: item.source_provider for item in contexts}
        source_statuses: dict[UUID, set[str]] = {}
        for context in contexts:
            source_statuses.setdefault(context.source_id, set()).add(context.query_status)
        found: list[MentionCandidate] = []
        for node in nodes.values():
            if node.kind not in {"file", "folder"}:
                continue
            path = self._node_path(node, nodes)
            if path is None or normalized not in path.casefold():
                continue
            if node.kind == "file":
                has_index = (node.source_id, node.external_id) in indexed_files
            else:
                has_index = node.id in indexed_folder_ids
            if has_index and node.source_id in providers:
                statuses = source_statuses[node.source_id]
                query_status = (
                    "ready" if "ready" in statuses else
                    "no_compatible_embeddings" if "no_compatible_embeddings" in statuses else
                    "no_indexed_content"
                )
                found.append(MentionCandidate(node, providers[node.source_id], path, query_status))
        return sorted(found, key=lambda item: (item.path.casefold(), str(item.node.id)))[:limit]

    def resolve_question_selection(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str],
        mentions: list[tuple[str, UUID]],
    ) -> QuestionSelection:
        self.require_member(scope=scope, user_id=user_id)
        contexts = self.question_contexts(scope=scope, user_id=user_id)
        selected = [item for item in contexts if
                    ("google_drive" if item.source_provider == "google" else item.source_provider) in providers]
        eligible = [item for item in selected if item.status in {"ready", "partial_failure"}]
        coverage = {
            "total_folders": len(selected), "eligible_folders": len(eligible),
            "pending_folders": len(selected) - len(eligible),
        }
        folder_ids = [item.id for item in eligible]
        if not mentions:
            return QuestionSelection(folder_ids, None, coverage, [])
        nodes = self._selection_nodes(scope=scope)
        source_providers = {item.source_id: item.source_provider for item in selected}
        documents = self._indexed_selection_documents(scope=scope, folder_ids=folder_ids)
        document_ids: set[UUID] = set()
        for kind, node_id in mentions:
            node = nodes.get(node_id)
            if node is None or node.kind != kind or node.source_id not in source_providers:
                raise ValueError("mention is unavailable")
            if self._node_path(node, nodes) is None:
                raise ValueError("mention is unavailable")
            matching_files = [node] if kind == "file" else [
                file for file in nodes.values() if file.kind == "file" and self._descends_from(file, node, nodes)
            ]
            keys = {(file.source_id, file.external_id) for file in matching_files}
            matched = {document_id for document_id, source_id, external_id in documents
                       if (source_id, external_id) in keys}
            if not matched:
                raise ValueError("mention is unavailable")
            document_ids.update(matched)
        return QuestionSelection(folder_ids, document_ids, coverage, [node_id for _, node_id in mentions])

    def authorize_mentions(
        self, *, scope: OrganizationScope, user_id: UUID, root_ids: list[UUID] | None,
        requested_ids: list[UUID],
    ) -> list[tuple[str, UUID]]:
        """Nodes a credential may query: requested ones inside its roots (roots themselves if none asked).

        Fails closed: an unknown/foreign node, a vanished root or a node outside the roots is denied.
        """
        self.require_member(scope=scope, user_id=user_id)
        nodes = self._selection_nodes(scope=scope)
        roots = []
        for root_id in dict.fromkeys(root_ids or []):
            root = nodes.get(root_id)
            if root is None or root.kind not in {"folder", "file"}:
                raise SyncAccessDenied("credential root is unavailable")
            roots.append(root)
        chosen = list(dict.fromkeys(requested_ids or [root.id for root in roots]))
        mentions: list[tuple[str, UUID]] = []
        for node_id in chosen:
            node = nodes.get(node_id)
            if node is None or node.kind not in {"folder", "file"}:
                raise SyncAccessDenied("node outside the credential scope")
            if roots and not any(self._descends_from(node, root, nodes) for root in roots):
                raise SyncAccessDenied("node outside the credential scope")
            mentions.append((node.kind, node.id))
        return mentions

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
        workspace_folder_id: UUID | None = None,
    ) -> None:
        """Upsert the synchronized provider metadata into the local catalog.

        This deliberately receives provider-neutral values. A new connector only
        needs to supply opaque IDs and parent relationships.
        """
        if source.organization_id != organization_id:
            raise SyncAccessDenied("source tenant mismatch")
        documents, folders = self.filter_excluded_content(organization_id=organization_id,
            source_id=source.id, documents=documents, folders=folders,
            workspace_folder_id=workspace_folder_id)
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
        for document in documents:
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
                node.kind = "file"
                node.parent_id, node.name, node.mime_type, node.source_url = (
                    parent.id,
                    document.name,
                    document.mime_type,
                    document.source_url,
                )
        self.session.flush()
        if workspace_folder_id is None:
            return
        if source.provider == "notion":
            self._remove_notion_legacy_folders(source=source, root=root)
            self._remove_empty_folders(source_id=source.id,
                                      preserved_external_ids={folder.id for folder in folders})
        # A delta only carries what changed and the catalog is shared by every
        # space of the source: prune just the files this space saw disappear
        # at the source and that no other space still keeps.
        live = select(Document.external_file_id).join(
            WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id,
        ).where(
            WorkspaceFolder.source_id == source.id,
            Document.index_status != "removed",
        )
        gone = set(self.session.scalars(select(Document.external_file_id).where(
            Document.organization_id == organization_id,
            Document.workspace_folder_id == workspace_folder_id,
            Document.index_status == "removed",
            Document.external_file_id.not_in(live),
        )))
        if not gone:
            return
        stale = list(self.session.scalars(select(LibraryNode).where(
            LibraryNode.source_id == source.id,
            LibraryNode.kind == "file",
            LibraryNode.external_id.in_(gone),
        )))
        parents = {node.parent_id for node in stale if node.parent_id is not None}
        for node in stale:
            self.session.delete(node)
        self.session.flush()
        self._remove_empty_folders(
            source_id=source.id,
            preserved_external_ids={folder.id for folder in folders},
            candidate_ids=parents,
        )
        self.session.flush()

    def _remove_notion_legacy_folders(self, *, source: DataSource, root: LibraryNode) -> None:
        """Discard old search placeholders once their document ID is repaired.

        Keep legacy folders backed by another unsynchronized space until its
        own content is rebuilt. Never delete a live file from that space.
        """
        from app.integrations.notion import NOTION_CONTAINER_PREFIX

        live = set(self.session.scalars(select(Document.external_file_id).join(
            WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id,
        ).where(WorkspaceFolder.source_id == source.id, Document.index_status != "removed")))
        legacy = list(self.session.scalars(select(LibraryNode).where(
            LibraryNode.source_id == source.id, LibraryNode.kind == "folder",
            ~LibraryNode.external_id.startswith(NOTION_CONTAINER_PREFIX),
        )))
        for node in legacy:
            if node.external_id in live:
                continue
            replacement = self._by_external(source_id=source.id,
                                            external_id=NOTION_CONTAINER_PREFIX + node.external_id)
            for child in self.session.scalars(select(LibraryNode).where(LibraryNode.parent_id == node.id)):
                child.parent_id = replacement.id if replacement else root.id
            self.session.flush()
            self.session.delete(node)
        self.session.flush()

    def _root(self, *, organization_id: UUID, source: DataSource) -> LibraryNode:
        root = self._by_external(source_id=source.id, external_id=SOURCE_ROOT_EXTERNAL_ID)
        provider_name = {
            "google_drive": "Google Drive",
            "notion": "Notion",
            "onedrive": "OneDrive",
            "sharepoint": "SharePoint",
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
            if remote.kind in {"page", "database", "data_source"}:
                existing.mime_type = f"application/x-notion-{remote.kind}"
            return existing
        node = LibraryNode(
            organization_id=organization_id,
            source_id=source_id,
            parent_id=parent.id,
            external_id=external_id,
            kind="folder",
            name=remote.name,
            mime_type=f"application/x-notion-{remote.kind}" if remote.kind in {"page", "database", "data_source"} else None,
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

    def _remove_empty_folders(
        self, *, source_id: UUID, preserved_external_ids: set[str] | None = None,
        candidate_ids: set[UUID] | None = None,
    ) -> None:
        """Prune only orphaned folder metadata, never a source root.

        With ``candidate_ids`` only those folders and, once emptied, their
        ancestors are considered, so folders of other spaces stay untouched.
        """
        while True:
            occupied_parent_ids = set(
                self.session.scalars(
                    select(LibraryNode.parent_id)
                    .where(LibraryNode.source_id == source_id, LibraryNode.parent_id.is_not(None))
                    .distinct()
                )
            )
            empty = [
                node
                for node in self.session.scalars(
                    select(LibraryNode).where(LibraryNode.source_id == source_id, LibraryNode.kind == "folder")
                )
                if node.id not in occupied_parent_ids
                and node.external_id not in (preserved_external_ids or set())
                and (candidate_ids is None or node.id in candidate_ids)
            ]
            if not empty:
                return
            if candidate_ids is not None:
                candidate_ids = {node.parent_id for node in empty if node.parent_id is not None}
            for node in empty:
                self.session.delete(node)
            self.session.flush()
