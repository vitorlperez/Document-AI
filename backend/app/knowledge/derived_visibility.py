"""Read-time hiding of stored derivatives that cite content the person can no longer read (ADR-0021 §8).

Everything gravado (answers in history, notifications, automation results, followed-query baselines) carries a
*provenance*: the documents, folders and library nodes it came from. It is checked against the person's CURRENT
access on every read; nothing here writes. A derivative is visible only if EVERY source is still readable:
a mixed answer cannot be partially rewritten without inventing text, so the whole item is hidden.

Only the ``enforce`` rollout mode hides. ``off``/``shadow`` keep today's behaviour (the legacy answer is "everything").
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.sqlids import ids_clause
from app.knowledge.models import Document
from app.library.models import LibraryNode
from app.organizations.models import Organization
from app.spaces.access import SpaceAccess
from app.workspaces.models import WorkspaceFolder

HIDDEN_NOTICE = "Conteúdo ocultado por mudança de acesso."
HIDDEN_REASON = "access_changed"
_LEGACY_MODES = {"off", "shadow"}


@dataclass(frozen=True)
class Provenance:
    document_ids: frozenset[UUID] = frozenset()
    folder_ids: frozenset[UUID] = frozenset()
    node_ids: frozenset[UUID] = frozenset()

    def __bool__(self) -> bool:
        return bool(self.document_ids or self.folder_ids or self.node_ids)

    def to_data(self) -> dict[str, list[str]]:
        return {"document_ids": sorted(str(item) for item in self.document_ids),
                "workspace_folder_ids": sorted(str(item) for item in self.folder_ids)}


def _uuids(values: object) -> frozenset[UUID]:
    found: set[UUID] = set()
    for value in values if isinstance(values, (list, tuple, set, frozenset)) else ():
        try:
            found.add(UUID(str(value)))
        except (ValueError, AttributeError):
            continue
    return frozenset(found)


def provenance_from_data(data: object) -> Provenance:
    """Read ``{"document_ids": [...], "workspace_folder_ids": [...]}`` as written by ``Provenance.to_data``."""
    if not isinstance(data, dict):
        return Provenance()
    return Provenance(document_ids=_uuids(data.get("document_ids")), folder_ids=_uuids(data.get("workspace_folder_ids")))


def provenance_from_citations(citations: object) -> Provenance:
    """Documents named by a stored ``citations`` list (answer response, notification data, automation result)."""
    documents = [item.get("document_id") for item in citations if isinstance(item, dict)] \
        if isinstance(citations, list) else []
    return Provenance(document_ids=_uuids(documents))


def answer_provenance(response: object, context: object) -> Provenance:
    """Documents cited and file nodes listed by one stored assistant answer."""
    citations = response.get("citations") if isinstance(response, dict) else None
    references = context.get("references") if isinstance(context, dict) else None
    nodes = [item.get("id") for item in references
             if isinstance(item, dict) and item.get("kind") == "file"] if isinstance(references, list) else []
    return Provenance(provenance_from_citations(citations).document_ids, frozenset(), _uuids(nodes))


def is_enforcing(session: Session, organization_id: UUID) -> bool:
    mode = session.scalar(select(Organization.spaces_resolver_mode).where(Organization.id == organization_id))
    return (mode or "off") not in _LEGACY_MODES


@dataclass
class VisibilityIndex:
    """Answers ``visible(provenance)`` for many items from a handful of queries (never one per item)."""

    enforcing: bool
    access: SpaceAccess
    documents: frozenset[UUID] = frozenset()
    nodes: frozenset[UUID] = frozenset()

    def visible(self, provenance: Provenance) -> bool:
        if not self.enforcing or not provenance:
            return True
        return (provenance.document_ids <= self.documents
                and provenance.folder_ids <= self.access.folder_ids
                and provenance.node_ids <= self.nodes)


def build_index(session: Session, access: SpaceAccess, provenances: Iterable[Provenance]) -> VisibilityIndex:
    items = list(provenances)
    if not is_enforcing(session, access.organization_id):
        return VisibilityIndex(False, access)
    documents = frozenset().union(*(item.document_ids for item in items)) if items else frozenset()
    nodes = frozenset().union(*(item.node_ids for item in items)) if items else frozenset()
    return VisibilityIndex(
        True, access,
        documents=_readable_documents(session, access, documents),
        nodes=_readable_nodes(session, access, nodes),
    )


def _copies(session: Session, access: SpaceAccess, files: Collection[tuple[UUID, str]]) -> dict[tuple[UUID, str], set[UUID]]:
    """Folders (any status but removed) holding each logical file (source, external id)."""
    if not files:
        return {}
    rows = session.execute(
        select(WorkspaceFolder.source_id, Document.external_file_id, Document.workspace_folder_id)
        .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
        .where(Document.organization_id == access.organization_id, Document.index_status != "removed",
               ids_clause(session, Document.external_file_id, {external for _, external in files}))
    ).all()
    wanted = set(files)
    found: dict[tuple[UUID, str], set[UUID]] = {}
    for source_id, external_id, folder_id in rows:
        if (source_id, external_id) in wanted:
            found.setdefault((source_id, external_id), set()).add(folder_id)
    return found


def _readable_documents(session: Session, access: SpaceAccess, document_ids: Collection[UUID]) -> frozenset[UUID]:
    """Documents that still exist and whose file sits in some folder the person can read."""
    ids = list(document_ids)
    if not ids:
        return frozenset()
    own = session.execute(
        select(Document.id, Document.workspace_folder_id, Document.external_file_id, WorkspaceFolder.source_id)
        .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
        .where(Document.organization_id == access.organization_id, Document.index_status != "removed",
               ids_clause(session, Document.id, ids))
    ).all()
    readable = {row.id for row in own if row.workspace_folder_id in access.folder_ids}
    other = [row for row in own if row.id not in readable]
    copies = _copies(session, access, {(row.source_id, row.external_file_id) for row in other})
    for row in other:  # the same file reachable through another folder of the person is still readable
        if copies.get((row.source_id, row.external_file_id), set()) & access.folder_ids:
            readable.add(row.id)
    return frozenset(readable)


def _readable_nodes(session: Session, access: SpaceAccess, node_ids: Collection[UUID]) -> frozenset[UUID]:
    """File nodes whose indexed copies the person can read. A node with no document at all names no content."""
    ids = list(node_ids)
    if not ids:
        return frozenset()
    nodes = session.execute(
        select(LibraryNode.id, LibraryNode.source_id, LibraryNode.external_id)
        .where(LibraryNode.organization_id == access.organization_id, ids_clause(session, LibraryNode.id, ids))
    ).all()
    copies = _copies(session, access, {(row.source_id, row.external_id) for row in nodes})
    readable = set()
    for row in nodes:
        folders = copies.get((row.source_id, row.external_id))
        if not folders or folders & access.folder_ids:
            readable.add(row.id)
    return frozenset(readable)


def hidden_response() -> dict[str, object]:
    return {"hidden": True, "reason": HIDDEN_REASON}


def message_visibility(session: Session, access: SpaceAccess, messages: Iterable) -> dict[UUID, bool]:
    """``message.id -> visible`` for assistant messages (user messages are never hidden). Constant query count."""
    assistants = [message for message in messages if message.role == "assistant"]
    provenance = {message.id: answer_provenance(message.response, message.context) for message in assistants}
    index = build_index(session, access, provenance.values())
    return {message.id: index.visible(provenance[message.id]) for message in assistants}
