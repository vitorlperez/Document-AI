"""Company-scoped Library projection and browse boundary."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import String, case, cast, delete, exists, func, literal, or_, select, union_all
from sqlalchemy.orm import Session, aliased

from app.core.scoping import OrganizationScope
from app.core.sqlids import ids_clause
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.ingestion.service import DiscoveredDocument, SyncAccessDenied
from app.integrations.google_drive import RemoteFolder
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.queryability import folder_is_queryable
from app.knowledge.questions import EMBEDDING_MODEL
from app.library.models import LibraryExclusion, LibraryNode, ManualSyncRun
from app.library.tool_groups import (
    LEGACY_SHARED_ROOT_NAME,
    display_node_name,
    provider_label,
    tool_group,
    tool_groups,
)
from app.library.visibility import restrict_to_visible
from app.organizations.models import Membership
from app.spaces.access import SpaceAccess, SpaceAccessResolver, SpaceRef
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection

SOURCE_ROOT_EXTERNAL_ID = "__company_library_source_root__"
PAGE_SIZE_MAX = 100
SEARCH_RESULT_LIMIT = 50
SYNC_RESULT_LIMIT = 20
MENTION_CANDIDATE_CAP = 2000  # name-narrowed candidates whose full path is built for one @ query


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
    sync_in_progress: bool = False
    source_status: str = "connected"
    spaces: tuple[SpaceRef, ...] = ()


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
class AuthorizedCatalog:
    """One resolution of the catalog a request may read.

    `nodes` is the authorized subset, `folder_ids` the admitted workspace folders and `all_nodes`
    the organization's full node map, reusable for further resolutions in the same request.
    """

    nodes: dict[UUID, LibraryNode]
    folder_ids: frozenset[UUID]
    all_nodes: dict[UUID, LibraryNode]


@dataclass(frozen=True)
class IndexedDocumentProvenance:
    """A workspace-scoped local document behind a shared library file."""

    workspace_folder_id: UUID
    document_id: UUID


@dataclass(frozen=True)
class FileIndexing:
    """Safe indexing state of one library file (specs/library-indexing-status.md)."""

    state: str
    error_code: str | None = None
    document_id: UUID | None = None
    workspace_folder_id: UUID | None = None
    indexed_at: datetime | None = None


# Best state first: one indexed copy in any space makes the file indexed.
INDEXING_PRECEDENCE = ("indexed", "failed", "skipped", "ignored", "not_found_in_source")
DOCUMENT_STATUS_TO_STATE = {
    "indexed": "indexed", "failed": "failed", "skipped": "skipped", "ignored": "ignored",
    "removed": "not_found_in_source", "deleted": "not_found_in_source",
}


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
    coverage: dict[str, int | bool]
    accepted_node_ids: list[UUID]


def question_coverage(contexts: list[LibraryContext]) -> dict[str, int | bool]:
    """Availability and synchronization overlap during progressive indexing.

    An eligible folder has queryable content, even while more files are pending.
    Terminal problems make coverage partial without claiming a sync is still running.
    """
    eligible = sum(item.query_status == "ready" for item in contexts)
    pending = sum(item.sync_in_progress or item.status in {"pending", "queued", "syncing"}
                  for item in contexts)
    return {
        "total_folders": len(contexts), "eligible_folders": eligible,
        "pending_folders": pending,
        "partial": bool(pending or eligible < len(contexts)
                        or any(item.status == "partial_failure" for item in contexts)),
    }


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

    def access_for(
        self, *, scope: OrganizationScope, user_id: UUID, space_ids: Collection[UUID] | None = None
    ) -> SpaceAccess:
        """What this person may read right now (membership check included): the one door of Block D."""
        return SpaceAccessResolver(self.session).resolve(scope=scope, user_id=user_id, space_ids=space_ids)

    def roots(
        self, *, scope: OrganizationScope, user_id: UUID, access: SpaceAccess | None = None
    ) -> list[LibraryNode]:
        access = access or self.access_for(scope=scope, user_id=user_id)
        return list(
            self.session.scalars(
                restrict_to_visible(self.session, access, scope.organization_id, select(LibraryNode).where(
                    LibraryNode.organization_id == scope.organization_id,
                    LibraryNode.kind == "source",
                ))
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

    def robot_access_states(
        self, *, scope: OrganizationScope, nodes: Collection[LibraryNode]
    ) -> dict[UUID, tuple[str, datetime | None]]:
        """Folders of the robot Drive mode whose share was revoked, keyed by node id."""
        from app.integrations.google_sa_models import DriveFolderLink

        folders = {node.external_id: node.id for node in nodes if node.kind == "folder" and node.external_id}
        if not folders:
            return {}
        rows = self.session.execute(
            select(DriveFolderLink.external_folder_id, DriveFolderLink.status, DriveFolderLink.purge_after).where(
                DriveFolderLink.organization_id == scope.organization_id,
                DriveFolderLink.external_folder_id.in_(folders),
                DriveFolderLink.status.in_(("suspect", "access_lost", "purge_scheduled")),
            )
        )
        return {
            folders[external]: ("purge_scheduled" if state == "purge_scheduled" else "access_lost", purge_after)
            for external, state, purge_after in rows
        }

    def _same_tool_roots(self, *, scope: OrganizationScope, parent: LibraryNode) -> list[UUID]:
        """A source root stands for its whole tool: Drive by OAuth and Drive by shared folder are one "Google Drive"."""
        if parent.kind != "source":
            return [parent.id]
        providers = {
            source_id: provider for source_id, provider in self.session.execute(
                select(DataSource.id, DataSource.provider).where(DataSource.organization_id == scope.organization_id))
        }
        group = tool_group(providers.get(parent.source_id))
        sibling_sources = [source_id for source_id, provider in providers.items() if tool_group(provider) == group]
        roots = list(self.session.scalars(select(LibraryNode.id).where(
            LibraryNode.organization_id == scope.organization_id, LibraryNode.kind == "source",
            LibraryNode.source_id.in_(sibling_sources))))
        return roots or [parent.id]

    def children(
        self, *, scope: OrganizationScope, user_id: UUID, parent_id: UUID, page: int, page_size: int,
        access: SpaceAccess | None = None,
    ) -> BrowsePage:
        access = access or self.access_for(scope=scope, user_id=user_id)
        parent = self.session.scalar(
            select(LibraryNode).where(
                LibraryNode.id == parent_id,
                LibraryNode.organization_id == scope.organization_id,
            )
        )
        if parent is None or parent.kind == "file":
            raise SyncAccessDenied("company library node unavailable")
        if parent.kind != "source" and self.session.scalar(restrict_to_visible(
            self.session, access, scope.organization_id,
            select(LibraryNode.id).where(LibraryNode.id == parent.id))) is None:
            raise SyncAccessDenied("company library node unavailable")  # same answer as a node that does not exist
        statement = restrict_to_visible(self.session, access, scope.organization_id, select(LibraryNode).where(
            LibraryNode.organization_id == scope.organization_id,
            LibraryNode.parent_id.in_(self._same_tool_roots(scope=scope, parent=parent)),
        ))
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
        self, *, scope: OrganizationScope, user_id: UUID, node_id: UUID, allow_source: bool = False,
        access: SpaceAccess | None = None, system_view: bool = False,
    ) -> list[IndexedDocumentProvenance]:
        """Indexed documents, in scopes the person can read, of every file below one folder node (any depth).

        ``system_view`` is for administration (reprocess, remove from index) after the caller checked the admin
        role: it acts on every scope, whatever the Spaces of the person."""
        if system_view:
            self.require_member(scope=scope, user_id=user_id)
            access = None
        else:
            access = access or self.access_for(scope=scope, user_id=user_id)
        folder = self.session.scalar(
            select(LibraryNode).where(
                LibraryNode.id == node_id,
                LibraryNode.organization_id == scope.organization_id,
                LibraryNode.kind.in_(["folder", "source"] if allow_source else ["folder"]),
            )
        )
        if folder is None:
            raise SyncAccessDenied("company library node unavailable")
        files = list(self.session.scalars(select(LibraryNode).where(
            LibraryNode.id.in_(self._descendants_query(scope, [folder.id])), LibraryNode.kind == "file")))
        documents = self.documents_for_nodes(scope=scope, nodes=files, access=access)
        return [reference for references in documents.values() for reference in references]

    def _descendants_query(self, scope: OrganizationScope, roots):
        """``select(id)`` of the nodes (roots included) at any depth below ``roots`` (ids or a ``select(id)``)."""
        seeds = (LibraryNode.id.in_(roots) if hasattr(roots, "subquery")
                 else ids_clause(self.session, LibraryNode.id, roots))
        tree = select(LibraryNode.id).where(
            LibraryNode.organization_id == scope.organization_id, seeds,
        ).cte("descendants", recursive=True)
        child = aliased(LibraryNode)
        tree = tree.union(select(child.id).where(
            child.parent_id == tree.c.id, child.organization_id == scope.organization_id))
        return select(tree.c.id)

    def indexed_documents_page(
        self, *, scope: OrganizationScope, workspace_folder_id: UUID, page: int, page_size: int
    ) -> tuple[list[Document], int]:
        """One page of the indexed documents of a scope plus the total (the caller checked access to the folder)."""
        base = (Document.organization_id == scope.organization_id,
                Document.workspace_folder_id == workspace_folder_id, Document.index_status == "indexed")
        total = int(self.session.scalar(select(func.count()).select_from(Document).where(*base)) or 0)
        rows = list(self.session.scalars(
            select(Document).where(*base).order_by(Document.name, Document.id)
            .offset((page - 1) * page_size).limit(page_size)))
        return rows, total

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
            ids_clause(self.session, LibraryNode.parent_id, levels[-1]),
        ))):
            levels.append(children)
        nodes = list(self.session.scalars(select(LibraryNode).where(
            LibraryNode.organization_id == scope.organization_id,
            LibraryNode.source_id == node.source_id,
            ids_clause(self.session, LibraryNode.id, [item for level in levels for item in level]),
        )))
        self._remember_exclusions(scope=scope, source_id=node.source_id,
                                  items={item.external_id: item.kind for item in nodes})
        # Children first also works with databases enforcing immediate foreign keys.
        for ids in reversed(levels):
            self.session.execute(delete(LibraryNode).where(
                LibraryNode.organization_id == scope.organization_id,
                LibraryNode.source_id == node.source_id,
                ids_clause(self.session, LibraryNode.id, ids),
            ))
        self.session.flush()

    def workspace_provenance(
        self, *, scope: OrganizationScope, node: LibraryNode, access: SpaceAccess | None
    ) -> list[UUID]:
        """Return only sync-scope UUIDs that currently index this file (and the person may read).

        ``access=None`` is the system view (unrestricted); member-facing callers always pass theirs.
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
                    *self._readable_folders(access, Document.workspace_folder_id),
                )
                .distinct()
                .order_by(Document.workspace_folder_id)
            )
        )

    def _readable_folders(self, access: SpaceAccess | None, column) -> tuple:
        """Predicate keeping only scopes the person can read; none for the system view or the legacy answer."""
        if access is None or access.unrestricted:
            return ()
        return (ids_clause(self.session, column, access.folder_ids),)

    def document_provenance(
        self, *, scope: OrganizationScope, node: LibraryNode, access: SpaceAccess | None
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
                    *self._readable_folders(access, Document.workspace_folder_id),
                )
                .order_by(Document.workspace_folder_id, Document.id)
            )
        ]

    def documents_for_nodes(
        self, *, scope: OrganizationScope, nodes: list[LibraryNode], access: SpaceAccess | None
    ) -> dict[UUID, list[IndexedDocumentProvenance]]:
        """Load indexed document references for a browse page in one query."""
        return self.documents_and_indexing_for_nodes(scope=scope, nodes=nodes, access=access)[0]

    def indexing_for_nodes(
        self, *, scope: OrganizationScope, nodes: list[LibraryNode], access: SpaceAccess | None
    ) -> dict[UUID, FileIndexing]:
        """Indexing state of each file node of a page (no document text is read)."""
        return self.documents_and_indexing_for_nodes(scope=scope, nodes=nodes, access=access)[1]

    def documents_and_indexing_for_nodes(
        self, *, scope: OrganizationScope, nodes: list[LibraryNode], access: SpaceAccess | None
    ) -> tuple[dict[UUID, list[IndexedDocumentProvenance]], dict[UUID, FileIndexing]]:
        """Indexed provenance and indexing state of a browse page, from one query over `documents`.

        Only scopes in ``access`` count: a copy of the file in a scope the person cannot read is invisible here."""
        files = [node for node in nodes if node.kind == "file"]
        if not files:
            return {}, {}
        node_ids_by_source_external: dict[tuple[UUID, str], list[UUID]] = {}
        for node in files:
            node_ids_by_source_external.setdefault((node.source_id, node.external_id), []).append(node.id)
        provenance: dict[UUID, list[IndexedDocumentProvenance]] = {}
        best: dict[tuple[UUID, str], FileIndexing] = {}
        rows = self.session.execute(
            select(
                WorkspaceFolder.source_id, Document.external_file_id, Document.workspace_folder_id,
                Document.id, Document.index_status, Document.error_code, Document.indexed_at,
            )
            .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
            .where(
                Document.organization_id == scope.organization_id,
                WorkspaceFolder.organization_id == scope.organization_id,
                ids_clause(self.session, WorkspaceFolder.source_id, {node.source_id for node in files}),
                ids_clause(self.session, Document.external_file_id, {node.external_id for node in files}),
                *self._readable_folders(access, Document.workspace_folder_id),
            )
            .order_by(Document.workspace_folder_id, Document.id)
        ).all()
        for source_id, external_id, folder_id, document_id, status, error_code, indexed_at in rows:
            if status == "indexed":
                for node_id in node_ids_by_source_external.get((source_id, external_id), []):
                    provenance.setdefault(node_id, []).append(
                        IndexedDocumentProvenance(folder_id, document_id)
                    )
            state = DOCUMENT_STATUS_TO_STATE.get(status)
            if state is None:
                continue
            key = (source_id, external_id)
            current = best.get(key)
            if current is None or INDEXING_PRECEDENCE.index(state) < INDEXING_PRECEDENCE.index(current.state):
                best[key] = FileIndexing(
                    state=state, document_id=document_id, workspace_folder_id=folder_id,
                    error_code=error_code if state in {"failed", "skipped", "ignored"} else None,
                    indexed_at=indexed_at if state == "indexed" else None,
                )
        indexing = {
            node.id: best.get((node.source_id, node.external_id), FileIndexing(state="pending"))
            for node in files
        }
        return provenance, indexing

    def spaces_for_nodes(
        self, *, scope: OrganizationScope, nodes: Collection[LibraryNode], access: SpaceAccess
    ) -> dict[UUID, tuple[SpaceRef, ...]]:
        """Space badges of a page of nodes, from the caller's own Spaces only, in a constant number of queries.

        A file carries the Spaces of every readable scope that holds a live copy; a folder the union over the files
        below it; a source root the Spaces of its readable scopes."""
        if not access.spaces or not nodes:
            return {}
        org = scope.organization_id
        files = [node for node in nodes if node.kind == "file"]
        folders = [node for node in nodes if node.kind == "folder"]
        sources = {node.source_id for node in nodes if node.kind == "source"}
        folder_sets: dict[UUID, set[UUID]] = {}
        live = (Document.organization_id == org, Document.index_status.not_in(("removed", "deleted")),
                ids_clause(self.session, Document.workspace_folder_id, access.folder_ids))
        if files:
            by_key: dict[tuple[UUID, str], list[UUID]] = {}
            for node in files:
                by_key.setdefault((node.source_id, node.external_id), []).append(node.id)
            for source_id, external_id, folder_id in self.session.execute(
                select(WorkspaceFolder.source_id, Document.external_file_id, Document.workspace_folder_id)
                .select_from(Document).join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
                .where(*live, ids_clause(self.session, WorkspaceFolder.source_id, {n.source_id for n in files}),
                       ids_clause(self.session, Document.external_file_id, {n.external_id for n in files}))
                .distinct()
            ):
                for node_id in by_key.get((source_id, external_id), ()):
                    folder_sets.setdefault(node_id, set()).add(folder_id)
        if folders:
            below = select(LibraryNode.id.label("root"), LibraryNode.id.label("node")).where(
                LibraryNode.organization_id == org, ids_clause(self.session, LibraryNode.id, [n.id for n in folders]),
            ).cte("badge_subtree", recursive=True)
            child = aliased(LibraryNode)
            below = below.union(select(below.c.root, child.id).where(
                child.parent_id == below.c.node, child.organization_id == org))
            file_node = aliased(LibraryNode)
            for root_id, folder_id in self.session.execute(
                select(below.c.root, Document.workspace_folder_id)
                .select_from(below).join(file_node, file_node.id == below.c.node)
                .join(WorkspaceFolder, WorkspaceFolder.source_id == file_node.source_id)
                .join(Document, (Document.workspace_folder_id == WorkspaceFolder.id)
                      & (Document.external_file_id == file_node.external_id))
                .where(file_node.kind == "file", *live, WorkspaceFolder.organization_id == org).distinct()
            ):
                folder_sets.setdefault(root_id, set()).add(folder_id)
        if sources:
            by_source: dict[UUID, set[UUID]] = {}
            for folder_id, source_id in self.session.execute(
                select(WorkspaceFolder.id, WorkspaceFolder.source_id).where(
                    WorkspaceFolder.organization_id == org, ids_clause(self.session, WorkspaceFolder.id, access.folder_ids),
                    ids_clause(self.session, WorkspaceFolder.source_id, sources))
            ):
                by_source.setdefault(source_id, set()).add(folder_id)
            for node in nodes:
                if node.kind == "source":
                    folder_sets[node.id] = by_source.get(node.source_id, set())
        result: dict[UUID, tuple[SpaceRef, ...]] = {}
        for node_id, folder_ids in folder_sets.items():
            merged = {ref.id: ref for folder_id in folder_ids for ref in access.spaces_of(folder_id)}
            result[node_id] = tuple(sorted(merged.values(), key=lambda ref: (ref.name.casefold(), str(ref.id))))
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
        return self.search_page(scope=scope, user_id=user_id, query=query, page=1, page_size=limit).items

    def search_page(
        self, *, scope: OrganizationScope, user_id: UUID, query: str, page: int, page_size: int,
        access: SpaceAccess | None = None,
    ) -> BrowsePage:
        access = access or self.access_for(scope=scope, user_id=user_id)
        normalized = query.strip()
        if not normalized or len(normalized) > 500:
            raise ValueError("query must contain between 1 and 500 characters")
        statement = restrict_to_visible(self.session, access, scope.organization_id, select(LibraryNode).where(
            LibraryNode.organization_id == scope.organization_id,
            LibraryNode.kind.in_(["folder", "file"]),
            func.lower(LibraryNode.name).contains(normalized.lower(), autoescape=True),
        ))
        total = int(self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
        items = list(self.session.scalars(
            statement.order_by(LibraryNode.kind.desc(), LibraryNode.name, LibraryNode.id)
            .offset((page - 1) * page_size).limit(page_size)
        ))
        return BrowsePage(items=items, page=page, page_size=page_size, total=total)

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

    def catalog_inventory(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str],
        mentions: list[tuple[str, UUID]], limit: int = 500,
        inventory_folder_ids: dict[UUID, UUID] | None = None,
    ) -> tuple[list[LibraryNode], int]:
        """Files in the authorized local catalog, including files awaiting indexing.

        Historical references are checked as catalog references, not content selections.
        Known withdrawn or denied-folder files are excluded; explicit references fail closed.
        Folder inventory means direct children, consistent with catalog_children.
        """
        catalog = self.authorized_catalog(
            scope=scope, user_id=user_id, providers=providers, mentions=[],
        )
        rows = self.session.execute(
            select(WorkspaceFolder.source_id, Document.external_file_id,
                   Document.workspace_folder_id, Document.index_status)
            .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
            .where(Document.organization_id == scope.organization_id,
                   WorkspaceFolder.organization_id == scope.organization_id)
        ).all()
        known = {(source, external) for source, external, _folder, _status in rows}
        live = {(source, external) for source, external, folder, status in rows
                if folder in catalog.folder_ids and status not in {"removed", "deleted"}}
        allowed = {
            node.id: node for node in catalog.nodes.values()
            if self._node_path(node, catalog.all_nodes) is not None
            and (node.kind != "file" or (node.source_id, node.external_id) in live
                 or (node.source_id, node.external_id) not in known)
        }
        roots = []
        for kind, node_id in dict.fromkeys(mentions):
            node = allowed.get(node_id)
            if node is None or node.kind != kind or kind not in {"file", "folder"}:
                raise SyncAccessDenied("catalog reference is outside the authorized selection")
            parent_id = (inventory_folder_ids or {}).get(node_id)
            parent = allowed.get(parent_id) if parent_id else None
            if parent_id and (parent is None or node.parent_id != parent.id):
                raise SyncAccessDenied("catalog reference left its inventory folder")
            roots.append(node)
        files = [node for node in allowed.values() if node.kind == "file" and (
            not roots or any(node.id == root.id if root.kind == "file"
                             else node.parent_id == root.id for root in roots)
        )]
        files.sort(key=lambda node: (node.name.casefold(), str(node.id)))
        if roots and all(node.kind == "file" for node in roots):
            files = roots  # Preserve the visible ordering of historical references and ordinals.
        return files[:limit], len(files)

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
        """Reauthorize persisted inventory references before reading local content.

        Authority is the person's own Spaces (A1): the node map, the admitted scopes and the documents read
        are all bounded by ``access.folder_ids``, never by the organization."""
        access = self.access_for(scope=scope, user_id=user_id)
        if not node_ids:
            return []
        normalized_providers = tool_groups(providers)
        nodes = self._selection_nodes(scope=scope, access=access)
        sources = {
            source_id: provider
            for source_id, provider in self.session.execute(
                select(DataSource.id, DataSource.provider).where(
                    DataSource.organization_id == scope.organization_id
                )
            )
        }
        admitted_folders = list(self.session.scalars(
            select(WorkspaceFolder.id).where(
                WorkspaceFolder.organization_id == scope.organization_id,
                ids_clause(self.session, WorkspaceFolder.id, access.folder_ids),
                folder_is_queryable(),
            )
        ))
        ready_sources = set(
            self.session.scalars(
                select(WorkspaceFolder.source_id).where(
                    WorkspaceFolder.organization_id == scope.organization_id,
                    ids_clause(self.session, WorkspaceFolder.id, admitted_folders),
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
                or tool_group(sources.get(node.source_id)) not in normalized_providers
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
        documents = (
            select(
                WorkspaceFolder.source_id, Document.external_file_id, Document.id,
                Document.source_url, Document.workspace_folder_id,
            )
            .select_from(Document)
            .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
            .where(
                Document.organization_id == scope.organization_id,
                WorkspaceFolder.organization_id == scope.organization_id,
                Document.index_status == "indexed",
                ids_clause(self.session, Document.workspace_folder_id, admitted_folders),
                ids_clause(self.session, Document.external_file_id, {node.external_id for node in files}),
                ids_clause(self.session, WorkspaceFolder.source_id, {node.source_id for node in files}),
            )
            .subquery()
        )
        # Window functions work on PostgreSQL and SQLite. Bound the rows AND text
        # returned by SQL, rather than fetching every chunk and discarding it in Python.
        ranked_chunks = (
            select(
                DocumentChunk.document_id, DocumentChunk.position,
                func.substr(DocumentChunk.text, 1, SNAPSHOT_MAX_CHUNK_CHARS).label("text"),
                func.row_number().over(
                    partition_by=DocumentChunk.document_id,
                    order_by=DocumentChunk.position,
                ).label("chunk_rank"),
            )
            .join(documents, documents.c.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.organization_id == scope.organization_id,
                DocumentChunk.workspace_folder_id == documents.c.workspace_folder_id,
                func.length(func.trim(DocumentChunk.text)) > 0,
            )
            .subquery()
        )
        rows = self.session.execute(
            select(
                documents.c.source_id, documents.c.external_file_id, documents.c.id,
                documents.c.source_url, ranked_chunks.c.text,
            )
            .outerjoin(ranked_chunks, (
                (ranked_chunks.c.document_id == documents.c.id)
                & (ranked_chunks.c.chunk_rank <= SNAPSHOT_MAX_CHUNKS)
            ))
            .order_by(documents.c.external_file_id, documents.c.id, ranked_chunks.c.position)
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

    def sync_status(self, *, scope: OrganizationScope, user_id: UUID) -> list[dict]:
        """Folder sync progress, with isolated file failures reported as partial.

        Members see the scopes they can read; owners/admins see the operational state of every scope (never names
        of files), so a failing Space they are not in is still theirs to fix."""
        access = self.access_for(scope=scope, user_id=user_id)
        contexts = self.question_contexts(scope=scope, user_id=user_id, access=access)
        operational = access.unrestricted or access.org_admin
        folders = list(self.session.scalars(select(WorkspaceFolder).where(
            WorkspaceFolder.organization_id == scope.organization_id,
            *(() if operational else (ids_clause(self.session, WorkspaceFolder.id, access.folder_ids),)))))
        listed_folder_ids = {folder.id for folder in folders}
        active_first = case((ProcessingJob.status.in_([
            ProcessingJobStatus.QUEUED, ProcessingJobStatus.SYNCING,
        ]), 0), else_=1)
        ordering = (active_first, ProcessingJob.created_at.desc(), ProcessingJob.id.desc())
        file_scope = exists(select(ManualSyncRun.id).where(
            ManualSyncRun.id == ProcessingJob.manual_run_id,
            ManualSyncRun.organization_id == scope.organization_id,
            ManualSyncRun.scope_kind.in_(["file", "files"]),
        ))

        def newest_jobs(is_file_scope):
            conditions = (ProcessingJob.organization_id == scope.organization_id,
                          ids_clause(self.session, ProcessingJob.workspace_folder_id, listed_folder_ids),
                          file_scope if is_file_scope else ~file_scope)
            # File retries cannot replace a completed/active folder-wide sync.
            job_order = ordering if not is_file_scope else (
                ProcessingJob.created_at.desc(), ProcessingJob.id.desc())
            statement = select(ProcessingJob).where(*conditions)
            if self.session.get_bind().dialect.name == "postgresql":
                statement = statement.distinct(ProcessingJob.workspace_folder_id).order_by(
                    ProcessingJob.workspace_folder_id, *job_order,
                )
            else:
                # SQLite test portability; production uses PostgreSQL DISTINCT ON.
                ranked = select(ProcessingJob.id, func.row_number().over(
                    partition_by=ProcessingJob.workspace_folder_id, order_by=job_order,
                ).label("position")).where(*conditions).subquery()
                statement = statement.where(ProcessingJob.id.in_(
                    select(ranked.c.id).where(ranked.c.position == 1),
                )).order_by(ProcessingJob.workspace_folder_id)
            return list(self.session.scalars(statement))

        jobs = newest_jobs(False)
        latest = {job.workspace_folder_id: job for job in jobs}
        file_jobs = [job for job in newest_jobs(True)
                     if job.workspace_folder_id not in latest
                     or (job.created_at, job.id) > (
                         latest[job.workspace_folder_id].created_at,
                         latest[job.workspace_folder_id].id)]
        progress = {}
        projections = []
        for job in jobs:
            task = ManualSyncRun.progress[str(job.id)]
            condition = (ManualSyncRun.id == job.manual_run_id if job.manual_run_id else
                         (ManualSyncRun.scope_kind == "sync")
                         & (ManualSyncRun.scope_external_id == str(job.id)))
            projections.append(select(
                literal(str(job.id)).label("job_id"), task["stage"].as_string().label("stage"),
                task["processed"].as_integer().label("processed"),
                task["total"].as_integer().label("total"),
                task["failed"].as_integer().label("failed"),
                task["skipped"].as_integer().label("skipped"),
            ).where(ManualSyncRun.organization_id == scope.organization_id, condition))
        if projections:
            # Only the scalar counters cross the database boundary. No full JSON
            # snapshot/outcomes deserialization, including for legacy manual runs.
            counters = union_all(*projections)
            if self.session.get_bind().dialect.name == "postgresql":
                job_key = cast(ProcessingJob.id, String)
                task = ManualSyncRun.progress[job_key]
                counters = select(
                    job_key.label("job_id"), task["stage"].as_string().label("stage"),
                    task["processed"].as_integer().label("processed"),
                    task["total"].as_integer().label("total"),
                    task["failed"].as_integer().label("failed"),
                task["skipped"].as_integer().label("skipped"),
                ).join(ProcessingJob, or_(
                    ManualSyncRun.id == ProcessingJob.manual_run_id,
                    (ProcessingJob.manual_run_id.is_(None))
                    & (ManualSyncRun.scope_kind == "sync")
                    & (ManualSyncRun.scope_external_id == job_key),
                )).where(
                    ManualSyncRun.organization_id == scope.organization_id,
                    ProcessingJob.organization_id == scope.organization_id,
                    ProcessingJob.id.in_([job.id for job in jobs]),
                )
            for row in self.session.execute(counters).mappings():
                progress[row["job_id"]] = {
                    "stage": row["stage"], "processed": row["processed"] or 0,
                    "total": row["total"] or 0, "failed": row["failed"] or 0,
                    "skipped": row["skipped"] or 0,
                }
        roots = {node.source_id: node.id for node in self.session.scalars(select(LibraryNode).where(
            LibraryNode.organization_id == scope.organization_id, LibraryNode.kind == "source",
        ))}
        items = []
        priorities = ["syncing", "queued", "failed", "partial_failure", "ready", "idle"]
        stages = ["discovering", "indexing", "embedding", "done"]
        for source in self.session.scalars(select(DataSource).where(
            DataSource.organization_id == scope.organization_id,
        ).order_by(DataSource.provider, DataSource.id)):
            spaces = [folder for folder in folders if folder.source_id == source.id]
            if not spaces and not operational:
                continue  # a tool with no scope the person can read does not exist for them
            source_jobs = [latest[folder.id] for folder in spaces if folder.id in latest]
            tasks = [progress.get(str(job.id), {}) for job in source_jobs]
            states = [job.status.value for job in source_jobs]
            states.extend(folder.status if folder.status in priorities else "idle"
                          for folder in spaces if folder.id not in latest)
            queryable = any(context.query_status == "ready" for context in contexts
                            if context.source_id == source.id)
            file_failures = [job for job in file_jobs
                             if job.workspace_folder_id in {folder.id for folder in spaces}
                             and job.status in {ProcessingJobStatus.FAILED, ProcessingJobStatus.PARTIAL_FAILURE}]
            if file_failures and queryable:
                states.append("partial_failure")
            state = next((value for value in priorities if value in states), "idle")
            if state == "failed" and queryable:
                # The newest job failed but earlier content is still searchable: not a dead tool.
                state = "partial_failure"
            active = [progress.get(str(job.id), {}).get("stage") for job in source_jobs
                      if job.status in {ProcessingJobStatus.QUEUED, ProcessingJobStatus.SYNCING}]
            stage = next((value for value in stages if value in active), None) if active else (
                "done" if source_jobs else None)
            started_jobs = [job for job in source_jobs if job.status in {
                ProcessingJobStatus.QUEUED, ProcessingJobStatus.SYNCING,
            }] if active else source_jobs
            starts = [job.started_at for job in started_jobs if job.started_at]
            synced = [folder.last_synced_at for folder in spaces if folder.last_synced_at]
            root_id = roots.get(source.id)
            items.append({
                "source_id": str(source.id), "provider": "google_drive" if source.provider == "google" else source.provider,
                "library_node_id": str(root_id) if root_id else None,
                "state": state, "stage": stage,
                "processed": sum(task.get("processed", 0) for task in tasks),
                "total": sum(task.get("total", 0) for task in tasks),
                "failed": sum(task.get("failed", 0) for task in tasks),
                "skipped": sum(task.get("skipped", 0) for task in tasks),
                "queryable": queryable,
                "started_at": min(starts).isoformat() if starts else None,
                "last_synced_at": max(synced).isoformat() if synced else None,
                "error_code": next((job.error_code for job in source_jobs + file_failures if job.error_code), None),
            })
        return items

    def question_contexts(
        self, *, scope: OrganizationScope, user_id: UUID, space_ids: Collection[UUID] | None = None,
        access: SpaceAccess | None = None,
    ) -> list[LibraryContext]:
        """Scopes the person can ask about: the resolver's answer, never "every folder of the organization".

        ``access`` lets a caller that already resolved this request's access avoid resolving twice."""
        access = access or SpaceAccessResolver(self.session).resolve(scope=scope, user_id=user_id, space_ids=space_ids)
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
                source_status=source.status,
                spaces=access.spaces_of(folder.id),
                sync_in_progress=has_active_job,
                query_status=("not_ready" if not folder_is_queryable(folder, self.session, has_embeddings=has_embeddings)
                              else "ready" if has_embeddings else "no_indexed_content" if not has_content
                              else "no_compatible_embeddings"),
            )
            for folder, source, has_content, has_embeddings, has_active_job in self.session.execute(
                select(WorkspaceFolder, DataSource, indexed_chunks.label("has_content"), compatible_embeddings.label("has_embeddings"),
                       exists(select(ProcessingJob.id).where(
                           ProcessingJob.workspace_folder_id == WorkspaceFolder.id,
                           ProcessingJob.organization_id == scope.organization_id,
                           ProcessingJob.status.in_([ProcessingJobStatus.QUEUED, ProcessingJobStatus.SYNCING]),
                       )).label("has_active_job"))
                .join(DataSource, DataSource.id == WorkspaceFolder.source_id)
                .where(
                    WorkspaceFolder.organization_id == scope.organization_id,
                    DataSource.organization_id == scope.organization_id,
                    ids_clause(self.session, WorkspaceFolder.id, access.folder_ids),
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
                ids_clause(self.session, Document.workspace_folder_id, folder_ids),
                Document.index_status == "indexed",
                WorkspaceFolder.organization_id == scope.organization_id,
                folder_is_queryable(),
                DataSource.organization_id == scope.organization_id,
            )
        ))

    def _selection_nodes(
        self, *, scope: OrganizationScope, access: SpaceAccess | None = None
    ) -> dict[UUID, LibraryNode]:
        """The node map of a request. With ``access`` only the nodes the person may see are loaded (ancestors
        included, so paths still resolve); ``None`` is the system view used by internal callers."""
        statement = select(LibraryNode).join(DataSource, DataSource.id == LibraryNode.source_id).where(
            LibraryNode.organization_id == scope.organization_id,
            DataSource.organization_id == scope.organization_id,
        )
        if access is not None:
            statement = restrict_to_visible(self.session, access, scope.organization_id, statement)
        return {node.id: node for node in self.session.scalars(statement)}

    def _authorized_catalog_nodes(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str],
        mentions: list[tuple[str, UUID]],
    ) -> dict[UUID, LibraryNode]:
        """Rebuild a catalog authorization set for every tool invocation."""
        return self.authorized_catalog(
            scope=scope, user_id=user_id, providers=providers, mentions=mentions,
        ).nodes

    def authorized_catalog(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str],
        mentions: list[tuple[str, UUID]], all_nodes: dict[UUID, LibraryNode] | None = None,
    ) -> AuthorizedCatalog:
        """Authorized nodes and admitted folder ids from a single selection resolution.

        Same rule as every catalog tool; pass the `all_nodes` of an earlier result to avoid reloading
        the catalog when resolving again in the same request.
        """
        access = self.access_for(scope=scope, user_id=user_id)
        nodes = all_nodes if all_nodes is not None else self._selection_nodes(scope=scope, access=access)
        selection = self.resolve_question_selection(
            scope=scope, user_id=user_id, providers=providers, mentions=mentions, all_nodes=nodes, access=access,
        )
        contexts = self.question_contexts(scope=scope, user_id=user_id, access=access)
        normalized_providers = tool_groups(providers)
        allowed_sources = {
            context.source_id
            for context in contexts
            if tool_group(context.source_provider) in normalized_providers
            and context.id in selection.folder_ids
        }
        root_ids = list(dict.fromkeys(selection.accepted_node_ids))
        under_roots = set(self.session.scalars(self._descendants_query(scope, root_ids))) if root_ids else None
        allowed: dict[UUID, LibraryNode] = {}
        for node in nodes.values():
            if node.source_id not in allowed_sources:
                continue
            if under_roots is not None and node.id not in under_roots:
                continue
            allowed[node.id] = node
        return AuthorizedCatalog(allowed, frozenset(selection.folder_ids), nodes)

    @staticmethod
    def _node_path(node: LibraryNode, nodes: dict[UUID, LibraryNode]) -> str | None:
        parts = [display_node_name(node.kind, node.name)]
        visited = {node.id}
        current = node
        while current.parent_id is not None:
            parent = nodes.get(current.parent_id)
            if parent is None or parent.source_id != node.source_id or parent.id in visited:
                return None
            visited.add(parent.id)
            parts.append(display_node_name(parent.kind, parent.name))
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

    def node_paths(self, *, scope: OrganizationScope, node_ids: list[UUID]) -> dict[UUID, str]:
        """Full path (source/…/folder) of each existing node; vanished or detached nodes are omitted."""
        nodes = self._selection_nodes(scope=scope)
        paths = {}
        for node_id in node_ids:
            node = nodes.get(node_id)
            path = self._node_path(node, nodes) if node is not None else None
            if path is not None:
                paths[node_id] = path
        return paths

    def mention_candidates(
        self, *, scope: OrganizationScope, user_id: UUID, query: str, limit: int = 20,
        access: SpaceAccess | None = None,
    ) -> list[MentionCandidate]:
        """``@`` suggestions, resolved in the database (spike M4/M5): only nodes that lead to indexed content in
        a scope the person can read, narrowed by name before any path is built."""
        access = access or self.access_for(scope=scope, user_id=user_id)
        normalized = query.strip().casefold()
        if len(normalized) > 500 or not 1 <= limit <= 50:
            raise ValueError("invalid mention search")
        contexts = self.question_contexts(scope=scope, user_id=user_id, access=access)
        eligible = [item.id for item in contexts if folder_is_queryable(item, self.session)]
        if not eligible:
            return []
        providers = {item.source_id: item.source_provider for item in contexts}
        source_statuses: dict[UUID, set[str]] = {}
        for context in contexts:
            source_statuses.setdefault(context.source_id, set()).add(context.query_status)
        org = scope.organization_id
        indexed_file = exists(
            select(Document.id).select_from(Document)
            .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
            .join(DataSource, DataSource.id == WorkspaceFolder.source_id)
            .where(
                Document.organization_id == org, Document.external_file_id == LibraryNode.external_id,
                WorkspaceFolder.source_id == LibraryNode.source_id, Document.index_status == "indexed",
                ids_clause(self.session, Document.workspace_folder_id, eligible),
                WorkspaceFolder.organization_id == org, folder_is_queryable(), DataSource.organization_id == org))
        seeds = select(LibraryNode.id, LibraryNode.parent_id).where(
            LibraryNode.organization_id == org, LibraryNode.kind == "file", indexed_file,
        ).cte("mention_closure", recursive=True)
        parent = aliased(LibraryNode)
        closure = seeds.union(select(parent.id, parent.parent_id).where(
            parent.id == seeds.c.parent_id, parent.organization_id == org))
        # the path contains the query: its last segment sits in the node's own name or in an ancestor's name
        last = normalized.rsplit("/", 1)[-1]
        candidates = select(LibraryNode).where(
            LibraryNode.organization_id == org, LibraryNode.kind.in_(["file", "folder"]),
            LibraryNode.id.in_(select(closure.c.id)))
        if last:
            by_name = aliased(LibraryNode)
            named = select(by_name.id).where(
                by_name.organization_id == org, func.lower(by_name.name).contains(last, autoescape=True))
            candidates = candidates.where(LibraryNode.id.in_(self._descendants_query(scope, named)))
        found: list[MentionCandidate] = []
        rows = list(self.session.scalars(
            candidates.order_by(func.lower(LibraryNode.name), LibraryNode.id).limit(MENTION_CANDIDATE_CAP)))
        nodes = self._ancestor_map(scope, rows)
        for node in rows:
            path = self._node_path(node, nodes)
            if path is None or normalized not in path.casefold() or node.source_id not in providers:
                continue
            statuses = source_statuses[node.source_id]
            query_status = (
                "ready" if "ready" in statuses else
                "no_compatible_embeddings" if "no_compatible_embeddings" in statuses else
                "no_indexed_content"
            )
            found.append(MentionCandidate(node, providers[node.source_id], path, query_status))
        return sorted(found, key=lambda item: (item.path.casefold(), str(item.node.id)))[:limit]

    def locate(
        self, *, scope: OrganizationScope, user_id: UUID, node_id: UUID | None = None,
        document_id: UUID | None = None, access: SpaceAccess | None = None,
    ) -> tuple[MentionCandidate, list[LibraryNode]]:
        """Resolve a library node (or the node of an indexed document) to what the UI needs to jump to it: the
        mention candidate and the chain of ancestors (source first). Anything the person may not see answers like
        a node that does not exist (``SyncAccessDenied``)."""
        if (node_id is None) == (document_id is None):
            raise ValueError("exactly one of node_id and document_id is required")
        access = access or self.access_for(scope=scope, user_id=user_id)
        org = scope.organization_id
        if document_id is not None:
            row = self.session.execute(
                select(Document.external_file_id, WorkspaceFolder.source_id).join(
                    WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id).where(
                    Document.id == document_id, Document.organization_id == org,
                    WorkspaceFolder.organization_id == org)).first()
            if row is None:
                raise SyncAccessDenied("company library node unavailable")
            found = self.session.scalar(select(LibraryNode.id).where(
                LibraryNode.organization_id == org, LibraryNode.source_id == row.source_id,
                LibraryNode.external_id == row.external_file_id, LibraryNode.kind == "file"))
            if found is None:
                raise SyncAccessDenied("company library node unavailable")
            node_id = found
        nodes = self._selection_nodes(scope=scope, access=access)  # only what the person may see, ancestors included
        node = nodes.get(node_id)
        path = self._node_path(node, nodes) if node is not None else None
        if node is None or path is None or node.kind not in ("file", "folder"):
            raise SyncAccessDenied("company library node unavailable")
        chain: list[LibraryNode] = []
        current = node
        while current.parent_id is not None:
            current = nodes[current.parent_id]
            chain.append(current)
        chain.reverse()
        contexts = self.question_contexts(scope=scope, user_id=user_id, access=access)
        provider = next((item.source_provider for item in contexts if item.source_id == node.source_id), None)
        if provider is None:
            raise SyncAccessDenied("company library node unavailable")
        statuses = {item.query_status for item in contexts if item.source_id == node.source_id}
        query_status = (
            "ready" if "ready" in statuses else
            "no_compatible_embeddings" if "no_compatible_embeddings" in statuses else "no_indexed_content")
        return MentionCandidate(node, provider, path, query_status), chain

    def _ancestor_map(self, scope: OrganizationScope, nodes: Collection[LibraryNode]) -> dict[UUID, LibraryNode]:
        """The given nodes and every ancestor, enough to build their paths (one recursive CTE)."""
        if not nodes:
            return {}
        up = select(LibraryNode.id, LibraryNode.parent_id).where(
            LibraryNode.organization_id == scope.organization_id,
            ids_clause(self.session, LibraryNode.id, [node.id for node in nodes]),
        ).cte("ancestors", recursive=True)
        parent = aliased(LibraryNode)
        up = up.union(select(parent.id, parent.parent_id).where(
            parent.id == up.c.parent_id, parent.organization_id == scope.organization_id))
        return {node.id: node for node in self.session.scalars(select(LibraryNode).where(
            LibraryNode.id.in_(select(up.c.id))))}

    def resolve_question_selection(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str],
        mentions: list[tuple[str, UUID]], all_nodes: dict[UUID, LibraryNode] | None = None,
        access: SpaceAccess | None = None,
    ) -> QuestionSelection:
        access = access or self.access_for(scope=scope, user_id=user_id)
        contexts = self.question_contexts(scope=scope, user_id=user_id, access=access)
        selected = [item for item in contexts if
                    tool_group(item.source_provider) in tool_groups(providers)]
        eligible = [item for item in selected if folder_is_queryable(item, self.session)]
        coverage = question_coverage(selected)
        folder_ids = [item.id for item in eligible]
        if not mentions:
            return QuestionSelection(folder_ids, None, coverage, [])
        nodes = all_nodes if all_nodes is not None else self._selection_nodes(scope=scope, access=access)
        source_providers = {item.source_id: item.source_provider for item in selected}
        documents = self._indexed_selection_documents(scope=scope, folder_ids=folder_ids)
        document_ids: set[UUID] = set()
        for kind, node_id in mentions:
            node = nodes.get(node_id)
            if node is None or node.kind != kind or node.source_id not in source_providers:
                raise ValueError("mention is unavailable")
            if self._node_path(node, nodes) is None:
                raise ValueError("mention is unavailable")
            keys = {(node.source_id, node.external_id)} if kind == "file" else {
                (source_id, external_id) for source_id, external_id in self.session.execute(
                    select(LibraryNode.source_id, LibraryNode.external_id).where(
                        LibraryNode.id.in_(self._descendants_query(scope, [node.id])), LibraryNode.kind == "file"))}
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
        access = self.access_for(scope=scope, user_id=user_id)
        nodes = self._selection_nodes(scope=scope, access=access)
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
        access = self.access_for(scope=scope, user_id=user_id)
        operational = access.unrestricted or access.org_admin
        rows = self.session.execute(
            select(ProcessingJob, WorkspaceFolder)
            .join(WorkspaceFolder, WorkspaceFolder.id == ProcessingJob.workspace_folder_id)
            .where(
                ProcessingJob.organization_id == scope.organization_id,
                WorkspaceFolder.organization_id == scope.organization_id,
                *(() if operational else (ids_clause(self.session, WorkspaceFolder.id, access.folder_ids),)),
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
        partial: bool = False,
        full_snapshot: bool = False,
        removed_file_ids: Collection[str] = (),
    ) -> None:
        """Upsert the synchronized provider metadata into the local catalog.

        This deliberately receives provider-neutral values. A new connector only
        needs to supply opaque IDs and parent relationships.

        A complete snapshot also prunes the catalog files of the source that it
        did not see and that no space indexes (orphans); an incremental run
        prunes only the orphans the source reported as gone.
        """
        if source.organization_id != organization_id:
            raise SyncAccessDenied("source tenant mismatch")
        documents, folders = self.filter_excluded_content(organization_id=organization_id,
            source_id=source.id, documents=documents, folders=folders,
            workspace_folder_id=workspace_folder_id)
        root = self._root(organization_id=organization_id, source=source)
        notion_candidates = (
            self._notion_projection_candidates(source_id=source.id,
                                              workspace_folder_id=workspace_folder_id)
            if source.provider == "notion" and workspace_folder_id is not None else set()
        )
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
        if workspace_folder_id is None or partial:
            return
        if source.provider == "notion":
            self._remove_notion_legacy_folders(source=source, root=root)
            self._remove_empty_folders(source_id=source.id,
                                      preserved_external_ids={folder.id for folder in folders},
                                      candidate_ids=notion_candidates)
        if full_snapshot:
            seen = {document.external_file_id for document in documents}
            self.prune_orphan_file_nodes(
                organization_id=organization_id, source_id=source.id,
                keep_external_ids=seen, preserved_folder_external_ids={folder.id for folder in folders},
            )
        elif removed_file_ids:
            self.prune_orphan_file_nodes(
                organization_id=organization_id, source_id=source.id,
                only_external_ids=set(removed_file_ids),
                preserved_folder_external_ids={folder.id for folder in folders},
            )
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
            ids_clause(self.session, LibraryNode.external_id, gone),
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

    def orphan_file_ids(self, *, organization_id: UUID, source_id: UUID) -> set[str]:
        """External IDs of catalog files of the source that no space holds a live document for."""
        return {node.external_id for node in self._orphan_file_nodes(
            organization_id=organization_id, source_id=source_id)}

    def prune_orphan_file_nodes(
        self, *, organization_id: UUID, source_id: UUID,
        keep_external_ids: Collection[str] = (), only_external_ids: Collection[str] | None = None,
        preserved_folder_external_ids: Collection[str] = (),
    ) -> int:
        """Drop catalog files without a live document in any space, then the folders they emptied.

        ``keep_external_ids`` protects files a complete snapshot just saw (they are
        ingested by that same run); ``only_external_ids`` limits the sweep to files the
        source reported gone. Idempotent; files with any live document are never touched.
        """
        keep, only = set(keep_external_ids), None if only_external_ids is None else set(only_external_ids)
        stale = [node for node in self._orphan_file_nodes(organization_id=organization_id, source_id=source_id)
                 if node.external_id not in keep and (only is None or node.external_id in only)]
        if not stale:
            return 0
        parents = {node.parent_id for node in stale if node.parent_id is not None}
        for node in stale:
            self.session.delete(node)
        self.session.flush()
        self._remove_empty_folders(
            source_id=source_id, preserved_external_ids=set(preserved_folder_external_ids), candidate_ids=parents,
        )
        self.session.flush()
        return len(stale)

    def _orphan_file_nodes(self, *, organization_id: UUID, source_id: UUID) -> list[LibraryNode]:
        live = select(Document.external_file_id).join(
            WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id,
        ).where(
            WorkspaceFolder.source_id == source_id,
            Document.organization_id == organization_id,
            Document.index_status != "removed",
        )
        return list(self.session.scalars(select(LibraryNode).where(
            LibraryNode.organization_id == organization_id,
            LibraryNode.source_id == source_id,
            LibraryNode.kind == "file",
            LibraryNode.external_id.not_in(live),
        )))

    def _notion_projection_candidates(self, *, source_id: UUID,
                                     workspace_folder_id: UUID) -> set[UUID]:
        """Prune only the prior hierarchy of this space, including empty bases.

        Empty containers have no document provenance. Use their saved selections
        to distinguish this space's stale containers from another space's catalog.
        Capture before upserting, while old document parents are still available.
        """
        from app.integrations.notion import NOTION_CONTAINER_PREFIX, notion_item_id

        nodes = list(self.session.scalars(select(LibraryNode).where(
            LibraryNode.source_id == source_id)))
        by_id = {node.id: node for node in nodes}
        selections = list(self.session.scalars(select(WorkspaceFolderSelection).where(
            WorkspaceFolderSelection.workspace_folder_id == workspace_folder_id)))
        if any(selection.kind == "all_accessible" for selection in selections):
            return {node.id for node in nodes if node.kind == "folder"}
        roots = {notion_item_id(selection.external_folder_id) for selection in selections
                 if selection.kind == "folder"}
        roots.update(NOTION_CONTAINER_PREFIX + id for id in tuple(roots))
        scoped = {node.id for node in nodes if node.external_id in roots}
        while children := {node.id for node in nodes if node.parent_id in scoped} - scoped:
            scoped.update(children)
        document_ids = set(self.session.scalars(select(Document.external_file_id).where(
            Document.workspace_folder_id == workspace_folder_id)))
        pending = [node.id for node in nodes if node.external_id in document_ids or node.id in scoped]
        while pending:
            node = by_id[pending.pop()]
            if node.parent_id in by_id and node.parent_id not in scoped:
                scoped.add(node.parent_id)
                pending.append(node.parent_id)
        return {id for id in scoped if by_id[id].kind == "folder"}

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
        provider_name = provider_label(source.provider)
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
        elif root.name == LEGACY_SHARED_ROOT_NAME:
            root.name = provider_name  # ferramenta única: nome antigo da raiz da conexão por pasta compartilhada
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
