"""Cookie-authenticated, tenant-scoped setup and product tour progress."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.identity.models import User
from app.organizations.onboarding import (
    OnboardingNotAllowed,
    OnboardingPending,
    OnboardingService,
    OnboardingStep,
)

router = APIRouter(prefix="/organizations/{organization_id}/onboarding", tags=["onboarding"])


class OnboardingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: OnboardingStep


@router.get("")
def onboarding_state(organization_id: UUID, user: User = Depends(current_user),
                     session: Session = Depends(database_session)):
    try:
        return OnboardingService(session).state(organization_id=organization_id, user_id=user.id)
    except OnboardingNotAllowed as error:
        raise HTTPException(403, "not allowed") from error


@router.patch("")
def advance_onboarding(organization_id: UUID, payload: OnboardingInput,
                       user: User = Depends(current_user), session: Session = Depends(database_session)):
    try:
        progress = OnboardingService(session).advance(
            organization_id=organization_id, user_id=user.id, step=payload.step,
        )
        session.commit()
        return progress
    except OnboardingNotAllowed as error:
        raise HTTPException(403, "not allowed") from error


@router.post("/tour/complete")
def complete_tour(organization_id: UUID, user: User = Depends(current_user),
                  session: Session = Depends(database_session)):
    try:
        progress = OnboardingService(session).complete_tour(organization_id=organization_id, user_id=user.id)
        session.commit()
        return progress
    except OnboardingNotAllowed as error:
        raise HTTPException(403, "not allowed") from error
    except OnboardingPending as error:
        raise HTTPException(409, "complete organization setup first") from error
