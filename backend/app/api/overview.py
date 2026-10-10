"""Scope overview card for the empty chat state."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import SyncAccessDenied
from app.knowledge.overview import folder_overview

router = APIRouter(tags=['overview'])


@router.get('/organizations/{organization_id}/library/overview')
def library_overview(organization_id: UUID, providers: list[str] = Query(default_factory=list, max_length=10),
                     user: User = Depends(current_user),
                     session: Session = Depends(database_session)) -> dict[str, object]:
    try:
        return folder_overview(session, scope=OrganizationScope(organization_id), user_id=user.id,
                               providers=[p[:40] for p in providers])
    except SyncAccessDenied as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'not allowed') from error
