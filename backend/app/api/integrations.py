from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select as sql_select
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
from app.integrations.models import DataSource
from app.integrations.notion import (
    NotionAccessDenied,
    NotionConnectionService,
    NotionOAuthClient,
    NotionOAuthInvalid,
    NotionOAuthUnavailable,
)
from app.integrations.onedrive import (
    MicrosoftGraphClient,
    OneDriveAccessDenied,
    OneDriveAccountMismatch,
    OneDriveCipher,
    OneDriveConnectionService,
    OneDriveOAuthInvalid,
    OneDriveOAuthUnavailable,
    OneDriveReauthRequired,
)
from app.integrations.registry import IntegrationRegistry
from app.workspaces.service import WorkspaceScope, WorkspaceService

router = APIRouter(tags=["integrations"])


class StartInput(BaseModel):
    organization_id: UUID


class FolderInput(BaseModel):
    source_id: UUID
    external_folder_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=512)
    uniform_access_confirmed: bool


class ScopeInput(BaseModel):
    source_id: UUID
    mode: Literal["selected", "all_accessible"]
    folder_ids: list[str] = Field(default_factory=list, max_length=100)
    include_root_files: bool = False
    name: str | None = Field(default=None, min_length=1, max_length=512)
    uniform_access_confirmed: bool


def service(request: Request, session: Session) -> GoogleConnectionService:
    key = request.app.state.settings.google_token_encryption_key
    return GoogleConnectionService(
        session, CredentialCipher(key.get_secret_value() if key else None)
    )


def notion_service(request: Request, session: Session) -> NotionConnectionService:
    key = (
        request.app.state.settings.notion_token_encryption_key
        or request.app.state.settings.google_token_encryption_key
    )
    return NotionConnectionService(
        session,
        CredentialCipher(key.get_secret_value() if key else None),
        NotionOAuthClient(
            client_id=request.app.state.settings.notion_oauth_client_id,
            client_secret=request.app.state.settings.notion_oauth_client_secret.get_secret_value()
            if request.app.state.settings.notion_oauth_client_secret
            else None,
            redirect_uri=request.app.state.settings.notion_oauth_redirect_uri,
        ),
    )


def onedrive_service(request: Request, session: Session) -> OneDriveConnectionService:
    settings = request.app.state.settings
    key = settings.microsoft_token_encryption_key
    return OneDriveConnectionService(
        session,
        OneDriveCipher(key.get_secret_value() if key else None),
        MicrosoftGraphClient(
            client_id=settings.microsoft_oauth_client_id,
            client_secret=settings.microsoft_oauth_client_secret.get_secret_value()
            if settings.microsoft_oauth_client_secret
            else None,
            redirect_uri=settings.microsoft_oauth_redirect_uri,
        ),
    )


@router.get("/data-sources/onedrive/oauth/start")
def start_onedrive(
    organization_id: UUID,
    request: Request,
    source_id: UUID | None = None,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> RedirectResponse:
    secret = request.cookies.get(request.app.state.settings.auth_session_cookie_name)
    if not secret:
        raise HTTPException(401, "authentication required")
    try:
        url = onedrive_service(request, session).begin(
            scope=OrganizationScope(organization_id),
            user_id=user.id,
            session_secret=secret,
            source_id=source_id,
        )
    except OneDriveOAuthUnavailable as error:
        raise HTTPException(503, "integration unavailable") from error
    except OneDriveAccessDenied as error:
        raise HTTPException(403, "not allowed") from error
    return RedirectResponse(url, status_code=302)


@router.get("/data-sources/onedrive/oauth/callback", response_model=None)
def onedrive_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: Session = Depends(database_session),
) -> dict[str, str] | RedirectResponse:
    secret = request.cookies.get(request.app.state.settings.auth_session_cookie_name)
    if not secret or not state:
        raise HTTPException(401, "Microsoft authorization failed")
    if error or not code:
        try:
            organization_id = onedrive_service(request, session).cancel(
                raw_state=state, session_secret=secret,
            )
        except OneDriveOAuthInvalid as exception:
            raise HTTPException(401, "Microsoft authorization failed") from exception
        except OneDriveAccessDenied as exception:
            raise HTTPException(403, "not allowed") from exception
        if "text/html" in request.headers.get("accept", "").lower():
            app_url = request.app.state.settings.public_app_url.rstrip("/")
            return RedirectResponse(
                f"{app_url}/companies/{organization_id}/integrations?error=onedrive", status_code=303,
            )
        raise HTTPException(400, "Microsoft authorization was canceled")
    try:
        source = onedrive_service(request, session).complete(
            raw_state=state, code=code, session_secret=secret
        )
    except OneDriveAccountMismatch as exception:
        session.commit()
        if "text/html" in request.headers.get("accept", "").lower():
            app_url = request.app.state.settings.public_app_url.rstrip("/")
            return RedirectResponse(
                f"{app_url}/companies/{exception.organization_id}/integrations?error=onedrive_account_mismatch",
                status_code=303,
            )
        raise HTTPException(409, "OneDrive account does not match the existing source") from exception
    except OneDriveOAuthInvalid as exception:
        raise HTTPException(401, "Microsoft authorization failed") from exception
    except OneDriveAccessDenied as exception:
        raise HTTPException(403, "not allowed") from exception
    except OneDriveOAuthUnavailable as exception:
        raise HTTPException(503, "integration unavailable") from exception
    if "text/html" in request.headers.get("accept", "").lower():
        app_url = request.app.state.settings.public_app_url.rstrip("/")
        return RedirectResponse(
            f"{app_url}/companies/{source.organization_id}/integrations?connected=onedrive",
            status_code=303,
        )
    return {"id": str(source.id), "status": source.status}


@router.get("/data-sources/notion/oauth/start")
def start_notion(
    organization_id: UUID,
    request: Request,
    source_id: UUID | None = None,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> RedirectResponse:
    secret = request.cookies.get(request.app.state.settings.auth_session_cookie_name)
    if not secret:
        raise HTTPException(401, "authentication required")
    try:
        url = notion_service(request, session).begin(
            scope=OrganizationScope(organization_id),
            user_id=user.id,
            session_secret=secret,
            source_id=source_id,
        )
    except NotionOAuthUnavailable as error:
        raise HTTPException(503, "integration unavailable") from error
    except NotionAccessDenied as error:
        raise HTTPException(403, "not allowed") from error
    except NotionOAuthInvalid as error:
        raise HTTPException(403, "not allowed") from error
    return RedirectResponse(url, status_code=302)


@router.get("/data-sources/notion/oauth/callback", response_model=None)
def notion_callback(
    code: str, state: str, request: Request, session: Session = Depends(database_session)
) -> dict[str, str] | RedirectResponse:
    secret = request.cookies.get(request.app.state.settings.auth_session_cookie_name)
    if not secret:
        raise HTTPException(401, "authentication failed")
    try:
        source = notion_service(request, session).complete(
            raw_state=state, code=code, session_secret=secret
        )
    except NotionOAuthInvalid as error:
        raise HTTPException(401, "authentication failed") from error
    except NotionAccessDenied as error:
        raise HTTPException(403, "not allowed") from error
    except NotionOAuthUnavailable as error:
        raise HTTPException(503, "integration unavailable") from error
    if "text/html" in request.headers.get("accept", "").lower():
        app_url = request.app.state.settings.public_app_url.rstrip("/")
        return RedirectResponse(
            f"{app_url}/companies/{source.organization_id}/integrations?connected=notion",
            status_code=303,
        )
    return {"id": str(source.id), "status": source.status}


def _start_google_oauth(
    *,
    organization_id: UUID,
    request: Request,
    user: User,
    session: Session,
    reauth_source_id: UUID | None = None,
) -> RedirectResponse:
    secret = request.cookies.get(request.app.state.settings.auth_session_cookie_name)
    if not secret:
        raise HTTPException(401, "authentication required")
    try:
        url = service(request, session).begin(
            scope=OrganizationScope(organization_id),
            user_id=user.id,
            session_secret=secret,
            port=request.app.state.google_drive_port,
            reauth_source_id=reauth_source_id,
        )
    except GoogleAccessDenied as e:
        raise HTTPException(403, "not allowed") from e
    except GoogleOAuthUnavailable as e:
        raise HTTPException(503, "integration unavailable") from e
    return RedirectResponse(url, status_code=302)


@router.post("/data-sources/google/oauth/start")
def start(
    payload: StartInput,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> RedirectResponse:
    return _start_google_oauth(
        organization_id=payload.organization_id, request=request, user=user, session=session
    )


@router.get("/data-sources/google/oauth/start")
def start_from_browser_navigation(
    organization_id: UUID,
    request: Request,
    source_id: UUID | None = None,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> RedirectResponse:
    """Top-level browser navigation avoids attempting to follow OAuth through fetch."""
    return _start_google_oauth(
        organization_id=organization_id,
        request=request,
        user=user,
        session=session,
        reauth_source_id=source_id,
    )


@router.get("/data-sources/google/oauth/callback", response_model=None)
def callback(
    code: str, state: str, request: Request, session: Session = Depends(database_session)
) -> dict[str, str] | RedirectResponse:
    secret = request.cookies.get(request.app.state.settings.auth_session_cookie_name)
    if not secret:
        raise HTTPException(401, "authentication failed")
    try:
        source = service(request, session).complete(
            raw_state=state,
            code=code,
            session_secret=secret,
            port=request.app.state.google_drive_port,
        )
    except (GoogleOAuthInvalid, GoogleAccessDenied):
        raise HTTPException(401, "authentication failed")
    except GoogleOAuthUnavailable:
        raise HTTPException(503, "integration unavailable")
    if "text/html" in request.headers.get("accept", "").lower():
        app_url = request.app.state.settings.public_app_url.rstrip("/")
        return RedirectResponse(
            f"{app_url}/companies/{source.organization_id}/integrations?connected=google_drive",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return {"id": str(source.id), "status": source.status}


@router.get("/data-sources")
def sources(
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> list[dict[str, str | None]]:
    try:
        rows = service(request, session).sources(
            scope=OrganizationScope(organization_id), user_id=user.id
        )
    except GoogleAccessDenied as e:
        raise HTTPException(403, "not allowed") from e
    connector_emails = dict(
        session.execute(
            sql_select(User.id, User.email).where(
                User.id.in_([source.connected_by_user_id for source in rows])
            )
        ).all()
    )
    return [
        {
            "id": str(x.id),
            "provider": x.provider,
            "status": x.status,
            "account_email": x.account_email,
            "connected_by_email": connector_emails.get(x.connected_by_user_id),
        }
        for x in rows
    ]


@router.delete("/data-sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_source(
    source_id: UUID,
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> None:
    source = session.scalar(
        sql_select(DataSource).where(
            DataSource.id == source_id,
            DataSource.organization_id == organization_id,
        )
    )
    if source is not None and source.provider == "onedrive":
        try:
            onedrive_service(request, session).disconnect(
                scope=OrganizationScope(organization_id),
                user_id=user.id,
                source_id=source_id,
            )
        except OneDriveOAuthInvalid as error:
            raise HTTPException(403, "not allowed") from error
        except OneDriveAccessDenied as error:
            raise HTTPException(403, "not allowed") from error
        return
    try:
        service(request, session).disconnect(
            scope=OrganizationScope(organization_id), user_id=user.id, source_id=source_id
        )
    except GoogleAccessDenied as error:
        raise HTTPException(403, "not allowed") from error


@router.get("/data-sources/{source_id}/folders")
def folders(
    source_id: UUID,
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> list[dict[str, str]]:
    source = session.scalar(
        sql_select(DataSource).where(
            DataSource.id == source_id,
            DataSource.organization_id == organization_id,
        )
    )
    if source is not None and source.provider == "onedrive":
        try:
            rows = onedrive_service(request, session).folders(
                scope=OrganizationScope(organization_id),
                user_id=user.id,
                source_id=source_id,
            )
            session.commit()
            return [{"id": item.id, "name": item.name} for item in rows]
        except OneDriveOAuthInvalid as error:
            session.commit()
            raise HTTPException(409, "reauthentication required") from error
        except OneDriveAccessDenied as error:
            raise HTTPException(403, "not allowed") from error
        except OneDriveOAuthUnavailable as error:
            raise HTTPException(503, "integration unavailable") from error
    try:
        rows = service(request, session).folders(
            scope=OrganizationScope(organization_id),
            user_id=user.id,
            source_id=source_id,
            port=request.app.state.google_drive_port,
        )
    except GoogleAccessDenied as e:
        raise HTTPException(403, "not allowed") from e
    except GoogleOAuthInvalid as e:
        session.commit()
        raise HTTPException(409, "reauthentication required") from e
    return [{"id": x.id, "name": x.name} for x in rows]


@router.get("/data-sources/{source_id}/scope-catalog")
def scope_catalog(
    source_id: UUID,
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    """Return remote metadata only for a connected source in the caller's Company."""
    source = session.scalar(
        sql_select(DataSource).where(
            DataSource.id == source_id,
            DataSource.organization_id == organization_id,
            DataSource.status == "connected",
        )
    )
    if source is not None and source.provider == "notion":
        try:
            notion_service(request, session).require_admin(
                scope=OrganizationScope(organization_id), user_id=user.id
            )
            rows = (
                IntegrationRegistry(request.app.state.settings)
                .get("notion")
                .folders(encrypted_credentials=source.encrypted_credentials)
            )
        except NotionAccessDenied as error:
            raise HTTPException(status_code=403, detail="not allowed") from error
        except (NotionOAuthInvalid, NotionOAuthUnavailable) as error:
            raise HTTPException(status_code=403, detail="not allowed") from error
        return {
            "folders": [{"id": item.id, "name": item.name} for item in rows],
            "root_files": {"available": False, "label": "Páginas acessíveis"},
            "all_accessible": {"available": True, "label": "Todas as páginas acessíveis"},
        }
    if source is not None and source.provider == "onedrive":
        try:
            rows = onedrive_service(request, session).folders(
                scope=OrganizationScope(organization_id),
                user_id=user.id,
                source_id=source_id,
            )
            session.commit()
        except OneDriveOAuthInvalid as error:
            session.commit()
            raise HTTPException(409, "reauthentication required") from error
        except OneDriveAccessDenied as error:
            raise HTTPException(403, "not allowed") from error
        except OneDriveOAuthUnavailable as error:
            raise HTTPException(503, "integration unavailable") from error
        return {
            "folders": [{"id": item.id, "name": item.name} for item in rows],
            "root_files": {"available": True, "label": "Arquivos avulsos da raiz"},
            "all_accessible": {"available": True, "label": "Todo o OneDrive acessível"},
        }
    try:
        rows = service(request, session).folders(
            scope=OrganizationScope(organization_id),
            user_id=user.id,
            source_id=source_id,
            port=request.app.state.google_drive_port,
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


@router.post("/workspace-folders", status_code=status.HTTP_201_CREATED)
def select(
    payload: FolderInput,
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, str]:
    try:
        scoped = OrganizationScope(organization_id)
        remote = service(request, session).folders(
            scope=scoped,
            user_id=user.id,
            source_id=payload.source_id,
            port=request.app.state.google_drive_port,
        )
        folder = WorkspaceService(session).select_folder(
            scope=scoped,
            user_id=user.id,
            **payload.model_dump(),
            available_folder_ids={x.id for x in remote},
        )
    except GoogleAccessDenied as e:
        raise HTTPException(403, "not allowed") from e
    except GoogleOAuthInvalid as e:
        session.commit()
        raise HTTPException(409, "reauthentication required") from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"id": str(folder.id), "status": folder.status}


@router.post("/workspace-folders/selections", status_code=status.HTTP_201_CREATED)
def select_scope(
    payload: ScopeInput,
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, str]:
    try:
        scoped = OrganizationScope(organization_id)
        selected_source = session.scalar(
            sql_select(DataSource).where(
                DataSource.id == payload.source_id,
                DataSource.organization_id == organization_id,
                DataSource.status == "connected",
            )
        )
        if selected_source is None:
            raise GoogleAccessDenied("source access denied")
        if selected_source.provider == "notion":
            notion_service(request, session).require_admin(scope=scoped, user_id=user.id)
            remote = (
                IntegrationRegistry(request.app.state.settings)
                .get("notion")
                .folders(encrypted_credentials=selected_source.encrypted_credentials)
            )
        elif selected_source.provider == "onedrive":
            remote = onedrive_service(request, session).folders(
                scope=scoped,
                user_id=user.id,
                source_id=payload.source_id,
            )
        else:
            remote = service(request, session).folders(
                scope=scoped,
                user_id=user.id,
                source_id=payload.source_id,
                port=request.app.state.google_drive_port,
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
    except OneDriveAccessDenied as error:
        raise HTTPException(403, "not allowed") from error
    except OneDriveReauthRequired as error:
        session.commit()
        raise HTTPException(409, "reauthentication required") from error
    except NotionAccessDenied as error:
        raise HTTPException(403, "not allowed") from error
    except GoogleOAuthInvalid as error:
        session.commit()
        raise HTTPException(409, "reauthentication required") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"id": str(folder.id), "status": folder.status}


@router.get("/workspace-folders")
def workspace_folders(
    organization_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> list[dict[str, object]]:
    try:
        workspace_service = WorkspaceService(session)
        rows = workspace_service.folders(scope=OrganizationScope(organization_id), user_id=user.id)
    except GoogleAccessDenied as error:
        raise HTTPException(status_code=403, detail="not allowed") from error
    return [
        {
            "id": str(folder.id),
            "name": folder.name,
            "status": folder.status,
            "last_synced_at": folder.last_synced_at.isoformat() if folder.last_synced_at else None,
            "source_id": str(folder.source_id),
            "external_folder_id": folder.external_folder_id,
            "selection_kind": next(
                (
                    item.kind
                    for item in workspace_service.selections(
                        scope=OrganizationScope(organization_id), workspace_folder_id=folder.id
                    )
                    if item.kind == "all_accessible"
                ),
                "selected",
            ),
            "selection_folder_ids": [
                item.external_folder_id
                for item in workspace_service.selections(
                    scope=OrganizationScope(organization_id), workspace_folder_id=folder.id
                )
                if item.kind == "folder"
            ],
        }
        for folder in rows
    ]
