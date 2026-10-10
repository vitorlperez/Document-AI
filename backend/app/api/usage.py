"""Owner/admin usage and quota panel."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.audit_usage.service import usage_summary
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.organizations.models import Membership, MembershipRole

router = APIRouter(tags=["usage"])


def require_org_admin(session: Session, organization_id: UUID, user_id: UUID) -> None:
    member = session.scalar(select(Membership).where(
        Membership.organization_id == organization_id, Membership.user_id == user_id,
        Membership.is_active.is_(True), Membership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN]),
    ))
    if member is None:
        raise HTTPException(403, "owner or admin required")


@router.get("/organizations/{organization_id}/usage")
def organization_usage(organization_id: UUID, user: User = Depends(current_user),
                       session: Session = Depends(database_session)) -> dict[str, object]:
    require_org_admin(session, organization_id, user.id)
    return usage_summary(session, scope=OrganizationScope(organization_id))
