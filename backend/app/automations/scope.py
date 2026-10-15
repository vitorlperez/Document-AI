"""Automation scope: library folders at any depth (``node_ids``, the chat's @mention mechanism).

Automations created before node scopes keep ``workspace_folder_ids`` (whole connected folders) and still run.
"""
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.ingestion.service import SyncAccessDenied
from app.library.service import LibraryService, QuestionSelection
from app.library.tool_groups import tool_group, tool_groups

MAX_SCOPE_NODES = 20


def _ids(scope: dict[str, object] | None, key: str) -> list[UUID]:
    return [UUID(str(item)) for item in (scope or {}).get(key) or []]


def scope_node_ids(scope: dict[str, object] | None) -> list[UUID]:
    return _ids(scope, "node_ids")


def legacy_folder_ids(scope: dict[str, object] | None) -> list[UUID]:
    return _ids(scope, "workspace_folder_ids")


def resolve_nodes(session: Session, org: OrganizationScope, user_id: UUID, node_ids: list[UUID]) -> QuestionSelection:
    """The user's question selection for the folders; raises ``SyncAccessDenied`` (not a member) or ``ValueError``
    (a folder is unavailable: removed, outside the library, or without indexed documents)."""
    library = LibraryService(session)
    providers = sorted(tool_groups(library.source_providers(scope=org, user_id=user_id).values()))
    return library.resolve_question_selection(
        scope=org, user_id=user_id, providers=providers, mentions=[("folder", item) for item in node_ids])


def node_access(session: Session, org: OrganizationScope, user_id: UUID, node_ids: list[UUID]) -> str:
    """``ok``, ``not_member`` or ``no_folder_access`` for querying every folder as this user."""
    try:
        resolve_nodes(session, org, user_id, node_ids)
    except SyncAccessDenied:
        return "not_member"
    except ValueError:
        return "no_folder_access"
    return "ok"


def node_paths(session: Session, org: OrganizationScope, node_ids: list[UUID]) -> dict[UUID, str]:
    return LibraryService(session).node_paths(scope=org, node_ids=node_ids)


def changed_document_ids(session: Session, org: OrganizationScope, user_id: UUID, node_ids: list[UUID],
                         workspace_folder_id: UUID) -> list[UUID] | None:
    """Indexed documents under the folders when a sync of ``workspace_folder_id`` touched them; else ``None``."""
    library = LibraryService(session)
    provenance = []
    try:
        for node_id in node_ids:
            provenance.extend(library.indexed_documents_under(scope=org, user_id=user_id, node_id=node_id))
    except SyncAccessDenied:
        return None
    if not any(item.workspace_folder_id == workspace_folder_id for item in provenance):
        return None
    return list(dict.fromkeys(item.document_id for item in provenance))
