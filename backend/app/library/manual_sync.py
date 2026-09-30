"""Durable synchronization snapshots; manual runs additionally force full reprocessing."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.models import ProcessingJob
from app.ingestion.service import DiscoveredDocument, IngestionService, SyncAccessDenied
from app.knowledge.models import Document
from app.library.models import LibraryNode, ManualSyncRun
from app.workspaces.models import WorkspaceFolder


def record_sync(
    session: Session, job: ProcessingJob, folder: WorkspaceFolder, user_id: UUID | None
) -> None:
    """Snapshot an ordinary job without assigning the manual reprocessing flag."""
    user = session.get(User, user_id) if user_id else None
    session.add(ManualSyncRun(
        organization_id=job.organization_id, source_id=folder.source_id,
        created_at=job.created_at,
        scope_kind="sync", scope_external_id=str(job.id), scope_name=folder.name,
        triggered_by_user_id=user_id, triggered_by=user.email if user else "Agendamento automático",
        status="queued", progress={str(job.id): {
            "workspace_name": folder.name, "workspace_folder_id": str(folder.id),
            "status": "queued", "total": 0, "processed": 0, "outcomes": [], "error_code": None,
        }},
    ))
    session.flush()


def request_run(
    session: Session,
    *,
    scope: OrganizationScope,
    user: User,
    node_id: UUID | None = None,
    workspace_id: UUID | None = None,
):
    ingestion = IngestionService(session)
    ingestion.require_admin(scope=scope, user_id=user.id)
    if workspace_id:
        folder = ingestion.require_folder(scope=scope, workspace_folder_id=workspace_id, lock=True)
        source_id, kind, external_id, name = folder.source_id, "workspace", None, folder.name
        folders = [folder]
    else:
        node = session.scalar(
            select(LibraryNode).where(
                LibraryNode.id == node_id,
                LibraryNode.organization_id == scope.organization_id,
                LibraryNode.kind.in_(["source", "folder"]),
            )
        )
        if node is None:
            raise SyncAccessDenied("company library node unavailable")
        source_id, kind, external_id, name = node.source_id, node.kind, node.external_id, node.name
        # Discover every authorized workspace of this integration. This also
        # finds new/failed files absent from local indexed-document provenance.
        folders = list(
            session.scalars(
                select(WorkspaceFolder)
                .where(
                    WorkspaceFolder.organization_id == scope.organization_id,
                    WorkspaceFolder.source_id == source_id,
                )
                .order_by(WorkspaceFolder.id)
            )
        )
    if not folders:
        raise ValueError("Nenhum espaço sincronizado nesta ferramenta. Selecione um espaço na integração antes de ressincronizar.")
    for folder in folders:
        ingestion.require_folder(scope=scope, workspace_folder_id=folder.id, lock=True)
        ingestion._require_no_active_job(scope=scope, workspace_folder_id=folder.id)
    run = ManualSyncRun(
        organization_id=scope.organization_id,
        source_id=source_id,
        scope_kind=kind,
        scope_external_id=external_id,
        scope_name=name,
        triggered_by_user_id=user.id,
        triggered_by=user.email,
        status="queued",
        completed_at=None,
        progress={},
        created_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    jobs = []
    for folder in folders:
        job = ingestion.enqueue(scope=scope, user_id=user.id, workspace_folder_id=folder.id,
                                record_history=False)
        job.manual_run_id = run.id
        jobs.append(job)
    run.progress = {
        str(job.id): {
            "workspace_name": folder.name,
            "workspace_folder_id": str(folder.id),
            "status": "queued",
            "total": 0,
            "processed": 0,
            "outcomes": [],
            "error_code": None,
        }
        for job, folder in zip(jobs, folders)
    }
    session.flush()
    nodes = {
        node.external_id: node
        for node in session.scalars(select(LibraryNode).where(LibraryNode.source_id == source_id))
    }
    nodes_by_id = {node.id: node for node in nodes.values()}
    progress = dict(run.progress)
    for job in jobs:
        known = []
        for document in session.scalars(
            select(Document).where(
                Document.organization_id == scope.organization_id,
                Document.workspace_folder_id == job.workspace_folder_id,
                Document.index_status.in_(["indexed", "failed"]),
            )
        ):
            node = nodes.get(document.external_file_id)
            parent = nodes_by_id.get(node.parent_id) if node else None
            known.append(
                DiscoveredDocument(
                    document.external_file_id,
                    document.name,
                    document.mime_type,
                    document.source_url,
                    parent_ids=(parent.external_id,) if parent else (),
                )
            )
        known = scoped_documents(session, job, known)
        progress[str(job.id)] = {
            **progress[str(job.id)],
            "total": len(known),
            "outcomes": [
                {
                    "external_id": item.external_file_id,
                    "name": item.name,
                    "processed": False,
                    "error_code": None,
                }
                for item in known
            ],
        }
    run.progress = progress
    session.flush()
    return run, jobs


def scoped_documents(session: Session, job: ProcessingJob, documents, folders=()):
    if not job.manual_run_id:
        return documents
    run = session.get(ManualSyncRun, job.manual_run_id)
    if run.scope_kind != "folder":
        return documents
    descendants = {run.scope_external_id}
    nodes = {
        node.id: node
        for node in session.scalars(
            select(LibraryNode).where(LibraryNode.source_id == run.source_id)
        )
    }
    parents = {
        node.external_id: (nodes[node.parent_id].external_id,) if node.parent_id in nodes else ()
        for node in nodes.values()
        if node.kind == "folder"
    }
    parents.update({folder.id: folder.parent_ids for folder in folders})
    while True:
        found = {key for key, values in parents.items() if set(values) & descendants}
        if found <= descendants:
            break
        descendants.update(found)
    return [
        item
        for item in documents
        if item.external_file_id in descendants or set(item.parent_ids) & descendants
    ]


def update_progress(session: Session, job: ProcessingJob, **values):
    condition = (
        ManualSyncRun.id == job.manual_run_id
        if job.manual_run_id else
        (ManualSyncRun.organization_id == job.organization_id)
        & (ManualSyncRun.scope_kind == "sync")
        & (ManualSyncRun.scope_external_id == str(job.id))
    )
    # Serialize sibling workspace workers updating the same aggregate snapshot.
    run = session.scalar(
        select(ManualSyncRun)
        .where(condition)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None:
        # Jobs created before history snapshots were introduced remain readable
        # through the legacy ProcessingJob fallback in synchronization_history.
        return
    progress = dict(run.progress)
    current = dict(progress[str(job.id)])
    current.update(values, status=job.status.value, error_code=job.error_code)
    if run.scope_kind != "sync" and current["status"] in {"ready", "partial_failure"}:
        current["status"] = (
            "partial_failure"
            if any(item["error_code"] for item in current["outcomes"])
            else "ready"
        )
    progress[str(job.id)] = current
    run.progress = progress
    statuses = [item["status"] for item in progress.values()]
    if job.started_at and not run.started_at:
        run.started_at = job.started_at
    active = any(status in {"queued", "syncing"} for status in statuses)
    if active:
        run.status = "syncing" if run.started_at else "queued"
        run.completed_at = None
    else:
        run.status = (
            "failed"
            if all(status == "failed" for status in statuses)
            else "partial_failure"
            if any(status in {"failed", "partial_failure"} for status in statuses)
            else "ready"
        )
        run.completed_at = datetime.now(UTC)
    session.flush()


def serialize_run(run: ManualSyncRun):
    # Deduplicate overlapping workspace copies when reporting integration files.
    outcomes = {}
    for task in run.progress.values():
        for item in task["outcomes"]:
            previous = outcomes.get(item["external_id"])
            outcomes[item["external_id"]] = {
                **item,
                "processed": bool(item.get("processed")) or bool((previous or {}).get("processed")),
                "error_code": item["error_code"] or (previous or {}).get("error_code"),
            }
    failures = [item for item in outcomes.values() if item["error_code"]]
    return {
        "id": run.scope_external_id if run.scope_kind == "sync" else str(run.id),
        "operation": "sync" if run.scope_kind == "sync" else "resync",
        "source_id": str(run.source_id),
        "scope_kind": run.scope_kind,
        "scope_name": run.scope_name,
        "triggered_by": run.triggered_by,
        "triggered_by_user_id": str(run.triggered_by_user_id) if run.triggered_by_user_id else None,
        "status": run.status,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "total": len(outcomes)
        + sum(task["total"] for task in run.progress.values() if not task["outcomes"]),
        "processed": sum(bool(item.get("processed")) for item in outcomes.values()),
        "failed": len(failures),
        "failures": failures,
        "tasks": list(run.progress.values()),
    }
