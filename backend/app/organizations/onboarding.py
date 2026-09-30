"""Tenant setup is shared; the conversation introduction belongs to one member."""
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.organizations.models import Membership, MembershipRole, Organization

OnboardingStep = Literal["welcome", "integrations", "complete"]


class OnboardingNotAllowed(PermissionError):
    pass


class OnboardingPending(ValueError):
    pass


class OnboardingService:
    def __init__(self, session: Session):
        self.session = session

    def state(self, *, organization_id: UUID, user_id: UUID) -> dict[str, str | bool]:
        organization, membership = self._rows(organization_id, user_id)
        required = (
            organization.onboarding_completed_at is None
            and membership.role != MembershipRole.MEMBER
        )
        return {
            "step": "complete" if organization.onboarding_completed_at else organization.onboarding_step,
            "required": required,
            "tour_required": not required and membership.tour_completed_at is None,
        }

    def advance(self, *, organization_id: UUID, user_id: UUID, step: OnboardingStep):
        organization, membership = self._rows(organization_id, user_id, lock=True)
        if membership.role == MembershipRole.MEMBER:
            raise OnboardingNotAllowed("only owners and admins configure onboarding")
        if organization.onboarding_completed_at is None:
            organization.onboarding_step = step
            if step == "complete":
                organization.onboarding_completed_at = datetime.now(UTC)
        self.session.flush()
        return self.state(organization_id=organization_id, user_id=user_id)

    def complete_tour(self, *, organization_id: UUID, user_id: UUID):
        organization, membership = self._rows(organization_id, user_id, lock=True)
        if organization.onboarding_completed_at is None and membership.role != MembershipRole.MEMBER:
            raise OnboardingPending("complete organization setup first")
        if membership.tour_completed_at is None:
            membership.tour_completed_at = datetime.now(UTC)
        self.session.flush()
        return self.state(organization_id=organization_id, user_id=user_id)

    def _rows(self, organization_id: UUID, user_id: UUID, *, lock: bool = False):
        membership_query = select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id == user_id,
            Membership.is_active.is_(True),
        ).execution_options(populate_existing=True)
        if lock:
            membership_query = membership_query.with_for_update()
        membership = self.session.scalar(membership_query)
        if membership is None:
            raise OnboardingNotAllowed("active membership required")
        query = select(Organization).where(Organization.id == organization_id)
        if lock:
            query = query.with_for_update()
        organization = self.session.scalar(query)
        if organization is None:
            raise OnboardingNotAllowed("organization unavailable")
        return organization, membership
