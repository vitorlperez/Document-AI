"""M58 robot Drive endpoints: explicit tenant/admin authorization and stable codes."""

import logging
from contextlib import contextmanager
from uuid import UUID

import httpx
import redis
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.integrations.google_drive_sa import FolderAccessLost, RobotUnavailable, SaRequestError
from app.integrations.google_drive_sa_service import DriveSaConnectionService
from app.integrations.http import RemoteThrottled


logger = logging.getLogger("document_intelligence.integration")


class RobotRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def stable_validation(request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, {"code": "invalid_request"}) from None
            except HTTPException as error:
                if isinstance(error.detail, dict) and "code" in error.detail:
                    raise
                code = (
                    "unauthenticated"
                    if error.status_code == 401
                    else "forbidden"
                    if error.status_code == 403
                    else "provider_unavailable"
                )
                raise HTTPException(
                    error.status_code, {"code": code}, headers=error.headers
                ) from None

        return stable_validation


router = APIRouter(prefix="/data-sources/google-sa", tags=["integrations"], route_class=RobotRoute)


class VerifyInput(BaseModel):
    url_or_id: str = Field(min_length=1, max_length=2048)


class LinkInput(BaseModel):
    folder_id: str = Field(min_length=10, max_length=128)


@contextmanager
def api_errors():
    try:
        yield
    except SaRequestError as error:
        raise HTTPException(error.status, {"code": error.code}) from None
    except FolderAccessLost:
        raise HTTPException(404, {"code": "not_shared"}) from None
    except RobotUnavailable:
        raise HTTPException(503, {"code": "robot_unavailable"}) from None
    except RemoteThrottled:
        raise HTTPException(429, {"code": "rate_limited"}) from None
    except (httpx.HTTPError, redis.RedisError):
        raise HTTPException(503, {"code": "provider_unavailable"}) from None


def build_service(request, session):
    return DriveSaConnectionService(
        session,
        request.app.state.settings,
        client=getattr(request.app.state, "drive_sa_client", None),
    )


def limit(request, organization_id, *, operation, limit=12):
    decision = request.app.state.rate_limiter.hit(
        key=f"drive-sa:{organization_id}:{operation}", limit=limit
    )
    if not decision.allowed:
        raise SaRequestError("rate_limited", 429)


def link_json(link):
    return {
        "link_id": str(link.id),
        "status": link.status,
        "purge_after": link.purge_after.isoformat() if link.purge_after else None,
    }


@router.post("/enable")
def enable(
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
):
    with api_errors():
        service = build_service(request, session)
        source = service.enable(scope=OrganizationScope(organization_id), user_id=user.id)
        queue = []
        if service.needs_provisioning:
            queue.append(("document_intelligence.ingestion.provision_drive_sa_robot", [str(source.id)]))
        if service.needs_labeling:
            queue.append(("document_intelligence.ingestion.label_drive_sa_robot", [str(service.needs_labeling)]))
        session.commit()  # the worker must see the committed row before it starts
        send_task = getattr(request.app.state, "automation_send_task", None)
        for name, args in queue:
            try:
                send_task(name, args=args)
            except Exception:  # noqa: BLE001 - the beat sweep re-queues stale provisioning
                logger.warning("drive_sa task dispatch failed", extra={"event": "drive_sa.dispatch_failed"})
        return {
            "source_id": str(source.id),
            "share_role": "reader",
            **service.enable_status(source),
        }


@router.get("/{source_id}/status")
def enable_status(
    source_id: UUID,
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
):
    with api_errors():
        service = build_service(request, session)
        source = service.source(
            scope=OrganizationScope(organization_id), user_id=user.id, source_id=source_id
        )
        return {"source_id": str(source.id), "share_role": "reader", **service.enable_status(source)}


@router.get("/{source_id}/inbox")
def inbox(
    source_id: UUID,
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
):
    with api_errors():
        service = build_service(request, session)
        source = service.source(
            scope=OrganizationScope(organization_id), user_id=user.id, source_id=source_id
        )
        limit(request, organization_id, operation="inbox", limit=15)
        return {"folders": service.inbox(source)}


@router.post("/{source_id}/folders/verify")
def verify(
    source_id: UUID,
    organization_id: UUID,
    payload: VerifyInput,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
):
    with api_errors():
        service = build_service(request, session)
        source = service.source(
            scope=OrganizationScope(organization_id), user_id=user.id, source_id=source_id
        )
        limit(request, organization_id, operation="verify", limit=30)
        data, _ = service.verify(source, payload.url_or_id)
        return data


@router.post("/{source_id}/folders")
def link(
    source_id: UUID,
    organization_id: UUID,
    payload: LinkInput,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
):
    with api_errors():
        service = build_service(request, session)
        linked = service.link(
            scope=OrganizationScope(organization_id),
            user_id=user.id,
            source_id=source_id,
            folder_id=payload.folder_id,
        )
        return {
            "link_id": str(linked.id),
            "workspace_folder_id": str(linked.workspace_folder_id),
            "folder_id": linked.external_folder_id,
            "status": linked.status,
        }


@router.delete("/{source_id}/folders/{link_id}")
def unlink(
    source_id: UUID,
    link_id: UUID,
    organization_id: UUID,
    request: Request,
    purge: bool = False,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
):
    with api_errors():
        result = build_service(request, session).unlink(
            scope=OrganizationScope(organization_id),
            user_id=user.id,
            source_id=source_id,
            link_id=link_id,
            purge=purge,
        )
        return link_json(result)


@router.post("/{source_id}/recheck")
def recheck(
    source_id: UUID,
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
):
    with api_errors():
        service = build_service(request, session)
        source = service.source(
            scope=OrganizationScope(organization_id), user_id=user.id, source_id=source_id
        )
        limit(request, organization_id, operation="recheck")
        return {"links": [link_json(x) for x in service.recheck(source)]}


@router.get("/{source_id}/folders")
def folder_links(
    source_id: UUID,
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
):
    with api_errors():
        service = build_service(request, session)
        source = service.source(
            scope=OrganizationScope(organization_id), user_id=user.id, source_id=source_id
        )
        from app.workspaces.models import WorkspaceFolder

        results = []
        for item in service.links(source):
            folder = (
                session.get(WorkspaceFolder, item.workspace_folder_id)
                if item.workspace_folder_id
                else None
            )
            results.append(
                {
                    **link_json(item),
                    "folder_id": item.external_folder_id,
                    "name": item.folder_name,
                    "workspace_folder_id": str(item.workspace_folder_id)
                    if item.workspace_folder_id
                    else None,
                    "shared_by_email": item.shared_by_email,
                    "shared_at": item.shared_at.isoformat() if item.shared_at else None,
                    "blocked_download_count": item.blocked_download_count,
                    "last_synced_at": folder.last_synced_at.isoformat()
                    if folder and folder.last_synced_at
                    else None,
                }
            )
        return {"folders": results}
