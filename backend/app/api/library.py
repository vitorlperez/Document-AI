"""Company Library browsing API; no live provider calls occur here."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.models import ProcessingJob
from app.ingestion.service import (
    IngestionService,
    ManagedDocumentNotFound,
    SyncAccessDenied,
    SyncAlreadyActive,
)
from app.library.manual_sync import request_run, serialize_run
from app.library.models import LibraryNode, ManualSyncRun
from app.library.service import PAGE_SIZE_MAX, IndexedDocumentProvenance, LibraryService
from app.workspaces.models import WorkspaceFolder

router = APIRouter(tags=["library"])


def _node(
    *, node: LibraryNode, documents: list[IndexedDocumentProvenance], source_provider: str | None = None
) -> dict[str, object]:
    return {
        "id": str(node.id),
        "parent_id": str(node.parent_id) if node.parent_id else None,
        "source_id": str(node.source_id),
        **({"source_provider": source_provider} if node.kind == "source" else {}),
        "kind": node.kind,
        "external_id": node.external_id,
        "name": node.name,
        "mime_type": node.mime_type,
        "source_url": node.source_url,
        "workspace_folder_ids": [str(item) for item in sorted({document.workspace_folder_id for document in documents})],
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
            _node(node=node, documents=[], source_provider=providers.get(node.source_id)) for node in roots
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
    documents = service.documents_for_nodes(scope=scope, nodes=items)
    return {"items": [_node(node=node, documents=documents.get(node.id, [])) for node in items]}


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


@router.get("/library/mention-candidates")
def library_mention_candidates(
    organization_id: UUID,
    q: str = Query(default="", max_length=500),
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    try:
        items = LibraryService(session).mention_candidates(
            scope=OrganizationScope(organization_id), user_id=user.id, query=q, limit=limit
        )
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return {"items": [{
        "node_id": str(item.node.id), "kind": item.node.kind, "name": item.node.name,
        "source_id": str(item.node.source_id), "source_provider": item.source_provider,
        "path": item.path, "query_status": item.query_status,
    } for item in items]}


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
    documents = service.documents_for_nodes(scope=scope, nodes=result.items)
    return {
        "items": [_node(node=node, documents=documents.get(node.id, [])) for node in result.items],
        "page": result.page,
        "page_size": result.page_size,
        "total": result.total,
        "pages": result.pages,
    }


def _documents_by_workspace(documents: list[IndexedDocumentProvenance]) -> dict[UUID, list[UUID]]:
    grouped: dict[UUID, list[UUID]] = {}
    for item in documents:
        grouped.setdefault(item.workspace_folder_id, []).append(item.document_id)
    return grouped


@router.post("/library/nodes/{node_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
def reprocess_library_folder(
    node_id: UUID,
    organization_id: UUID,
    request: Request,
    reprocess_all: bool = False,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    """Incremental sync of the spaces that contain a folder (or of the whole integration).

    Only new/changed files are fetched and rebuilt. ``reprocess_all`` is the explicit opt-in
    for a complete run: full discovery and a rebuild of every file below the node.
    """
    try:
        scope = OrganizationScope(organization_id)
        run, jobs = request_run(session, scope=scope, user=user, node_id=node_id,
                                full_mode=reprocess_all)
        documents = LibraryService(session).indexed_documents_under(scope=scope, user_id=user.id, node_id=node_id, allow_source=True)
        if reprocess_all:
            from app.knowledge.models import Document
            for reference in documents:
                session.get(Document, reference.document_id).content_hash = ""
        session.commit()
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except ManagedDocumentNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found") from error
    except SyncAlreadyActive as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="workspace sync already active") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    _dispatch_manual_jobs(request=request, session=session, jobs=jobs)
    return {"documents": len(documents), "run_id": str(run.id), "job_ids": [str(job.id) for job in jobs]}


@router.delete("/library/nodes/{node_id}/index")
def remove_library_folder_from_index(
    node_id: UUID,
    organization_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, int]:
    """Remove every indexed file below a folder from the local index; the source is untouched."""
    try:
        scope = OrganizationScope(organization_id)
        library = LibraryService(session)
        ingestion = IngestionService(session)
        ingestion.require_admin(scope=scope, user_id=user.id)
        node = session.scalar(select(LibraryNode).where(
            LibraryNode.id == node_id,
            LibraryNode.organization_id == organization_id,
            LibraryNode.kind == "folder",
        ))
        if node is None:
            raise SyncAccessDenied("company library node unavailable")
        # Lock sync scopes before discovering provenance, including empty folders.
        folders = list(session.scalars(select(WorkspaceFolder).where(
            WorkspaceFolder.organization_id == organization_id,
            WorkspaceFolder.source_id == node.source_id,
        ).order_by(WorkspaceFolder.id).with_for_update()))
        for folder in folders:
            ingestion._require_no_active_job(scope=scope, workspace_folder_id=folder.id)
        documents = library.indexed_documents_under(scope=scope, user_id=user.id, node_id=node_id)
        for workspace_folder_id, document_ids in _documents_by_workspace(documents).items():
            for document_id in document_ids:
                removed = ingestion.remove_indexed_document(
                    scope=scope, user_id=user.id, workspace_folder_id=workspace_folder_id, document_id=document_id
                )
                library.remove_file_if_unindexed(
                    scope=scope, source_id=removed.source_id, external_file_id=removed.external_file_id
                )
        library.remove_folder_catalog(scope=scope, node_id=node_id)
        session.commit()
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except ManagedDocumentNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found") from error
    except SyncAlreadyActive as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="workspace sync already active") from error
    return {"documents": len(documents)}


@router.get("/library/sync-history")
def synchronization_history(
    organization_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    """Combine durable manual runs and ordinary jobs without duplicate workspace tasks."""
    try:
        LibraryService(session).require_member(scope=OrganizationScope(organization_id), user_id=user.id)
    except SyncAccessDenied as error:
        raise HTTPException(status_code=403, detail="not allowed") from error
    runs = session.scalars(select(ManualSyncRun).where(
        ManualSyncRun.organization_id == organization_id,
    ).order_by(ManualSyncRun.created_at.desc(), ManualSyncRun.id.desc()).limit(100))
    items = [serialize_run(run) for run in runs]
    jobs = session.execute(select(ProcessingJob, WorkspaceFolder).join(
        WorkspaceFolder, WorkspaceFolder.id == ProcessingJob.workspace_folder_id,
    ).where(
        ProcessingJob.organization_id == organization_id,
        WorkspaceFolder.organization_id == organization_id,
        ProcessingJob.manual_run_id.is_(None),
        ~exists(select(ManualSyncRun.id).where(
            ManualSyncRun.organization_id == organization_id,
            ManualSyncRun.scope_kind == "sync",
            # SQLite stores UUIDs without hyphens; PostgreSQL casts include them.
            func.replace(ManualSyncRun.scope_external_id, "-", "") ==
            func.replace(ProcessingJob.id.cast(ManualSyncRun.scope_external_id.type), "-", ""),
        )),
    ).order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.desc()).limit(100))
    for job, folder in jobs:
        items.append({
            "id": str(job.id), "source_id": str(folder.source_id), "operation": "sync",
            "scope_kind": "workspace", "scope_name": folder.name,
            # Ordinary jobs did not persist file counters or the requesting user.
            "triggered_by": None, "triggered_by_user_id": None,
            "status": job.status.value, "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "total": None, "processed": None, "failed": None, "failures": [],
            "tasks": [{"workspace_folder_id": str(folder.id), "workspace_name": folder.name,
                       "status": job.status.value, "error_code": job.error_code}],
        })
    items.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    return {"items": items[:100]}


@router.get("/library/manual-syncs")
def manual_sync_history(organization_id: UUID, user: User = Depends(current_user),
                        session: Session = Depends(database_session)):
    scope = OrganizationScope(organization_id)
    try:
        LibraryService(session).require_member(scope=scope, user_id=user.id)
    except SyncAccessDenied as error:
        raise HTTPException(status_code=403, detail="not allowed") from error
    runs = session.scalars(select(ManualSyncRun).where(ManualSyncRun.organization_id == organization_id,
                                                     ManualSyncRun.scope_kind != "sync")
                          .order_by(ManualSyncRun.created_at.desc(), ManualSyncRun.id.desc()).limit(100))
    return {"items": [serialize_run(run) for run in runs]}


@router.post("/library/workspaces/{workspace_id}/reprocess", status_code=202)
def reprocess_library_workspace(workspace_id: UUID, organization_id: UUID, request: Request,
                                reprocess_all: bool = False,
                                user: User = Depends(current_user), session: Session = Depends(database_session)):
    try:
        run, jobs = request_run(session, scope=OrganizationScope(organization_id), user=user,
                                workspace_id=workspace_id, reprocess_all=reprocess_all)
        session.commit()
    except SyncAccessDenied as error:
        raise HTTPException(status_code=403, detail="not allowed") from error
    except SyncAlreadyActive as error:
        raise HTTPException(status_code=409, detail="workspace sync already active") from error
    _dispatch_manual_jobs(request=request, session=session, jobs=jobs)
    return {"run_id": str(run.id), "job_id": str(jobs[0].id), "status": "queued"}


def _dispatch_manual_jobs(*, request: Request, session: Session, jobs):
    queue_failed = False
    for job in jobs:
        try:
            request.app.state.ingestion_dispatcher.dispatch(job_id=job.id)
        except RuntimeError:
            IngestionService(session).fail(job_id=job.id, error_code="sync_queue_unavailable")
            queue_failed = True
    if queue_failed:
        session.commit()
        raise HTTPException(status_code=503, detail="sync queue unavailable; consult synchronization history")
