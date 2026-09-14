from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.audit_usage.service import SavedQueryService
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.integrations.google_drive import GoogleAccessDenied

router = APIRouter(tags=["saved-queries"])


class SavedQueryFilters(BaseModel):
    """Only reusable search constraints belong in a saved query, never output."""

    model_config = ConfigDict(extra="forbid")

    type: str | None = Field(default=None, min_length=1, max_length=80)


class SavedQueryInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    query: str = Field(min_length=1, max_length=1000)
    filters: SavedQueryFilters = Field(default_factory=SavedQueryFilters)


class SavedQueryRenameInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)


@router.get("/workspace-folders/{workspace_folder_id}/saved-queries")
def list_saved_queries(workspace_folder_id: UUID, organization_id: UUID, user: User = Depends(current_user), session: Session = Depends(database_session)) -> list[dict[str, object]]:
    try: rows = SavedQueryService(session).list(scope=OrganizationScope(organization_id), user_id=user.id, workspace_folder_id=workspace_folder_id)
    except GoogleAccessDenied as error: raise HTTPException(status_code=403, detail="not allowed") from error
    return [_serialize(row) for row in rows]


@router.post("/workspace-folders/{workspace_folder_id}/saved-queries", status_code=status.HTTP_201_CREATED)
def create_saved_query(workspace_folder_id: UUID, organization_id: UUID, payload: SavedQueryInput, user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str, object]:
    try:
        saved = SavedQueryService(session).create(
            scope=OrganizationScope(organization_id),
            user_id=user.id,
            workspace_folder_id=workspace_folder_id,
            name=payload.name,
            query=payload.query,
            filters=payload.filters.model_dump(exclude_none=True),
        )
    except GoogleAccessDenied as error: raise HTTPException(status_code=403, detail="not allowed") from error
    return _serialize(saved)


@router.patch("/saved-queries/{saved_query_id}")
def rename_saved_query(saved_query_id: UUID, organization_id: UUID, payload: SavedQueryRenameInput, user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str, object]:
    try: saved = SavedQueryService(session).update(scope=OrganizationScope(organization_id), user_id=user.id, saved_query_id=saved_query_id, name=payload.name)
    except GoogleAccessDenied as error: raise HTTPException(status_code=403, detail="not allowed") from error
    return _serialize(saved)


@router.delete("/saved-queries/{saved_query_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_query(saved_query_id: UUID, organization_id: UUID, user: User = Depends(current_user), session: Session = Depends(database_session)) -> None:
    try: SavedQueryService(session).delete(scope=OrganizationScope(organization_id), user_id=user.id, saved_query_id=saved_query_id)
    except GoogleAccessDenied as error: raise HTTPException(status_code=403, detail="not allowed") from error


def _serialize(saved) -> dict[str, object]:
    return {"id": str(saved.id), "workspace_folder_id": str(saved.workspace_folder_id), "name": saved.name, "query": saved.query, "filters": saved.filters}
