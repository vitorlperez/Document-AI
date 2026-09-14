from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.integrations.google_drive import (
    CredentialCipher,
    GoogleAccessDenied,
    GoogleConnectionService,
    GoogleOAuthInvalid,
    GoogleOAuthUnavailable,
)
from app.workspaces.service import WorkspaceScope, WorkspaceService

router = APIRouter(tags=["integrations"])
class StartInput(BaseModel): organization_id: UUID
class FolderInput(BaseModel): source_id: UUID; external_folder_id: str = Field(min_length=1,max_length=255); name: str = Field(min_length=1,max_length=512); uniform_access_confirmed: bool
class ScopeInput(BaseModel):
    source_id: UUID
    mode: Literal["selected", "all_accessible"]
    folder_ids: list[str] = Field(default_factory=list, max_length=100)
    include_root_files: bool = False
    name: str | None = Field(default=None, min_length=1, max_length=512)
    uniform_access_confirmed: bool
def service(request: Request, session: Session) -> GoogleConnectionService:
    key = request.app.state.settings.google_token_encryption_key
    return GoogleConnectionService(session, CredentialCipher(key.get_secret_value() if key else None))
def _start_google_oauth(
    *, organization_id: UUID, request: Request, user: User, session: Session, reauth_source_id: UUID | None = None
) -> RedirectResponse:
    secret = request.cookies.get(request.app.state.settings.auth_session_cookie_name)
    if not secret: raise HTTPException(401,"authentication required")
    try: url = service(request,session).begin(scope=OrganizationScope(organization_id),user_id=user.id,session_secret=secret,port=request.app.state.google_drive_port,reauth_source_id=reauth_source_id)
    except GoogleAccessDenied as e: raise HTTPException(403,"not allowed") from e
    except GoogleOAuthUnavailable as e: raise HTTPException(503,"integration unavailable") from e
    return RedirectResponse(url,status_code=302)


@router.post("/data-sources/google/oauth/start")
def start(
    payload: StartInput, request: Request, user: User = Depends(current_user), session: Session = Depends(database_session)
) -> RedirectResponse:
    return _start_google_oauth(organization_id=payload.organization_id, request=request, user=user, session=session)


@router.get("/data-sources/google/oauth/start")
def start_from_browser_navigation(
    organization_id: UUID, request: Request, source_id: UUID | None = None, user: User = Depends(current_user), session: Session = Depends(database_session)
) -> RedirectResponse:
    """Top-level browser navigation avoids attempting to follow OAuth through fetch."""
    return _start_google_oauth(organization_id=organization_id, request=request, user=user, session=session, reauth_source_id=source_id)
@router.get("/data-sources/google/oauth/callback", response_model=None)
def callback(code: str, state: str, request: Request, session: Session = Depends(database_session)) -> dict[str, str] | RedirectResponse:
    secret=request.cookies.get(request.app.state.settings.auth_session_cookie_name)
    if not secret: raise HTTPException(401,"authentication failed")
    try: source=service(request,session).complete(raw_state=state,code=code,session_secret=secret,port=request.app.state.google_drive_port)
    except (GoogleOAuthInvalid,GoogleAccessDenied): raise HTTPException(401,"authentication failed")
    except GoogleOAuthUnavailable: raise HTTPException(503,"integration unavailable")
    if "text/html" in request.headers.get("accept", "").lower():
        app_url = request.app.state.settings.public_app_url.rstrip("/")
        return RedirectResponse(
            f"{app_url}/companies/{source.organization_id}/integrations?connected=google_drive",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return {"id":str(source.id),"status":source.status}
@router.get("/data-sources")
def sources(organization_id: UUID, request: Request, user: User = Depends(current_user), session: Session = Depends(database_session)) -> list[dict[str, str | None]]:
    try: rows=service(request,session).sources(scope=OrganizationScope(organization_id),user_id=user.id)
    except GoogleAccessDenied as e: raise HTTPException(403,"not allowed") from e
    return [{"id":str(x.id),"provider":x.provider,"status":x.status,"account_email":x.account_email} for x in rows]


@router.delete("/data-sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_source(
    source_id: UUID,
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> None:
    try:
        service(request, session).disconnect(
            scope=OrganizationScope(organization_id), user_id=user.id, source_id=source_id
        )
    except GoogleAccessDenied as error:
        raise HTTPException(403, "not allowed") from error
@router.get("/data-sources/{source_id}/folders")
def folders(source_id: UUID, organization_id: UUID, request: Request, user: User = Depends(current_user), session: Session = Depends(database_session)) -> list[dict[str,str]]:
    try: rows=service(request,session).folders(scope=OrganizationScope(organization_id),user_id=user.id,source_id=source_id,port=request.app.state.google_drive_port)
    except GoogleAccessDenied as e: raise HTTPException(403,"not allowed") from e
    except GoogleOAuthInvalid as e:
        session.commit()
        raise HTTPException(409,"reauthentication required") from e
    return [{"id":x.id,"name":x.name} for x in rows]


@router.get("/data-sources/{source_id}/scope-catalog")
def scope_catalog(source_id: UUID, organization_id: UUID, request: Request, user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str, object]:
    """Return remote metadata only for a connected source in the caller's Company."""
    try:
        rows = service(request, session).folders(
            scope=OrganizationScope(organization_id), user_id=user.id, source_id=source_id, port=request.app.state.google_drive_port
        )
    except GoogleAccessDenied as error:
        raise HTTPException(403, "not allowed") from error
    except GoogleOAuthInvalid as error:
        session.commit()
        raise HTTPException(409, "reauthentication required") from error
    return {
        "folders": [{"id": item.id, "name": item.name} for item in rows],
        "root_files": {"available": True, "label": "Arquivos avulsos da raiz"},
        "all_accessible": {"available": True, "label": "Todo o Drive acessível"},
    }
@router.post("/workspace-folders",status_code=status.HTTP_201_CREATED)
def select(payload: FolderInput, organization_id: UUID, request: Request, user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str,str]:
    try:
        scoped=OrganizationScope(organization_id)
        remote=service(request,session).folders(scope=scoped,user_id=user.id,source_id=payload.source_id,port=request.app.state.google_drive_port)
        folder=WorkspaceService(session).select_folder(scope=scoped,user_id=user.id,**payload.model_dump(),available_folder_ids={x.id for x in remote})
    except GoogleAccessDenied as e: raise HTTPException(403,"not allowed") from e
    except GoogleOAuthInvalid as e:
        session.commit()
        raise HTTPException(409,"reauthentication required") from e
    except ValueError as e: raise HTTPException(422, str(e)) from e
    return {"id":str(folder.id),"status":folder.status}


@router.post("/workspace-folders/selections", status_code=status.HTTP_201_CREATED)
def select_scope(payload: ScopeInput, organization_id: UUID, request: Request, user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str, str]:
    try:
        scoped = OrganizationScope(organization_id)
        remote = service(request, session).folders(
            scope=scoped, user_id=user.id, source_id=payload.source_id, port=request.app.state.google_drive_port
        )
        folder = WorkspaceService(session).select_scope(
            scope=scoped,
            user_id=user.id,
            source_id=payload.source_id,
            requested=WorkspaceScope(
                mode=payload.mode,
                folder_ids=tuple(payload.folder_ids),
                include_root_files=payload.include_root_files,
            ),
            uniform_access_confirmed=payload.uniform_access_confirmed,
            available_folder_names={item.id: item.name for item in remote},
            name=payload.name,
        )
    except GoogleAccessDenied as error:
        raise HTTPException(403, "not allowed") from error
    except GoogleOAuthInvalid as error:
        session.commit()
        raise HTTPException(409, "reauthentication required") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"id": str(folder.id), "status": folder.status}

@router.get("/workspace-folders")
def workspace_folders(organization_id: UUID, user: User = Depends(current_user), session: Session = Depends(database_session)) -> list[dict[str, str | None]]:
    try:
        rows = WorkspaceService(session).folders(scope=OrganizationScope(organization_id), user_id=user.id)
    except GoogleAccessDenied as error:
        raise HTTPException(status_code=403, detail="not allowed") from error
    return [
        {"id": str(folder.id), "name": folder.name, "status": folder.status, "last_synced_at": folder.last_synced_at.isoformat() if folder.last_synced_at else None}
        for folder in rows
    ]
