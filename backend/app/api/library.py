"""Company Library browsing API; no live provider calls occur here."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import SyncAccessDenied
from app.library.models import LibraryNode
from app.library.service import PAGE_SIZE_MAX, LibraryService

router = APIRouter(tags=["library"])


def _node(
    *, node: LibraryNode, service: LibraryService, scope: OrganizationScope, source_provider: str | None = None
) -> dict[str, object]:
    documents = service.document_provenance(scope=scope, node=node)
    return {
        "id": str(node.id),
        "parent_id": str(node.parent_id) if node.parent_id else None,
        "source_id": str(node.source_id),
        **({"source_provider": source_provider} if node.kind == "source" else {}),
        "kind": node.kind,
        "name": node.name,
        "mime_type": node.mime_type,
        "source_url": node.source_url,
        "workspace_folder_ids": [str(item) for item in service.workspace_provenance(scope=scope, node=node)],
        "workspace_documents": [
            {"workspace_folder_id": str(item.workspace_folder_id), "document_id": str(item.document_id)}
            for item in documents
        ],
    }


@router.get("/library")
def library_roots(
    organization_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    try:
        scope = OrganizationScope(organization_id)
        service = LibraryService(session)
        roots = service.roots(scope=scope, user_id=user.id)
        providers = service.source_providers(scope=scope, user_id=user.id)
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    return {
        "items": [
            _node(node=node, service=service, scope=scope, source_provider=providers.get(node.source_id)) for node in roots
        ]
    }


@router.get("/library/search")
def library_search(
    organization_id: UUID,
    query: str = Query(min_length=1, max_length=500),
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    try:
        scope = OrganizationScope(organization_id)
        service = LibraryService(session)
        items = service.search_names(scope=scope, user_id=user.id, query=query)
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return {"items": [_node(node=node, service=service, scope=scope) for node in items]}


@router.get("/library/question-contexts")
def library_question_contexts(
    organization_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    try:
        contexts = LibraryService(session).question_contexts(
            scope=OrganizationScope(organization_id), user_id=user.id
        )
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    return {
        "items": [
            {
                "id": str(item.id),
                "name": item.name,
                "status": item.status,
                "source_id": str(item.source_id),
                "source_provider": item.source_provider,
                "query_status": item.query_status,
            }
            for item in contexts
        ]
    }


@router.get("/library/syncs")
def library_syncs(
    organization_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    try:
        syncs = LibraryService(session).recent_syncs(scope=OrganizationScope(organization_id), user_id=user.id)
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    return {
        "items": [
            {
                "id": str(item.id), "source_id": str(item.source_id), "workspace_folder_id": str(item.workspace_folder_id),
                "workspace_name": item.workspace_name, "status": item.status,
                "created_at": item.created_at.isoformat(), "started_at": item.started_at.isoformat() if item.started_at else None,
                "completed_at": item.completed_at.isoformat() if item.completed_at else None, "error_code": item.error_code,
            }
            for item in syncs
        ]
    }


@router.get("/library/nodes/{node_id}/children")
def library_children(
    node_id: UUID,
    organization_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=PAGE_SIZE_MAX),
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    try:
        scope = OrganizationScope(organization_id)
        service = LibraryService(session)
        result = service.children(
            scope=scope,
            user_id=user.id,
            parent_id=node_id,
            page=page,
            page_size=page_size,
        )
    except SyncAccessDenied as error:
        # A foreign UUID is intentionally indistinguishable from an absent node.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="library node not found") from error
    return {
        "items": [_node(node=node, service=service, scope=scope) for node in result.items],
        "page": result.page,
        "page_size": result.page_size,
        "total": result.total,
        "pages": result.pages,
    }
