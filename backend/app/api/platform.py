"""Platform-staff support endpoints, deliberately separate from tenant APIs."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.entitlements.comps import (
    CompDenied,
    CompInvalid,
    CompService,
    require_platform_admin,
    serialize_comp,
)
from app.entitlements.resolver import current_subscription, entitlements_for
from app.entitlements.summary import plan_state
from app.identity.models import User
from app.ingestion.service import IngestionService
from app.organizations.models import Organization, OrganizationComp, PlatformStaff
from app.organizations.staff_access import PlatformStaffAccessService, StaffAccessDenied
from app.workspaces.service import WorkspaceService

router = APIRouter(prefix="/platform", tags=["platform-support"])


@router.get("/companies")
def supported_companies(
    user: User = Depends(current_user), session: Session = Depends(database_session)
) -> list[dict[str, str]]:
    service = PlatformStaffAccessService(session)
    if not service.is_platform_staff(user_id=user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
    return [
        {
            "organization_id": str(company.organization_id),
            "name": company.organization_name,
        }
        for company in service.all_organizations(user_id=user.id)
    ]


@router.get("/companies/{organization_id}/overview")
def supported_company_overview(
    organization_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    scope = OrganizationScope(organization_id)
    service = PlatformStaffAccessService(session)
    try:
        company = service.require_organization_access(user_id=user.id, organization_id=organization_id)
    except StaffAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    service.record_organization_access(user_id=user.id, organization=company)
    folders = WorkspaceService(session).support_metadata(scope=scope)
    failure_summary = IngestionService(session).support_failure_summary(scope=scope)
    return {
        "organization_id": str(company.organization_id),
        "name": company.organization_name,
        "folders": [
            {
                "id": str(folder.id),
                "name": folder.name,
                "status": folder.status,
                "last_synced_at": folder.last_synced_at.isoformat() if folder.last_synced_at else None,
                "failure_summary": [
                    {"error_code": error_code, "count": count}
                    for error_code, count in failure_summary.get(folder.id, [])
                ],
            }
            for folder in folders
        ],
    }


class CompInput(BaseModel):
    plan_key: str
    reason: str = Field(min_length=1, max_length=240)
    expires_at: datetime | None = None
    permanent: bool = False
    limits_override: dict | None = None


class CompExtendInput(BaseModel):
    expires_at: datetime


def _admin(session: Session, user: User) -> None:
    try:
        require_platform_admin(session, user.id)
    except CompDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error


def _staff(session: Session, user: User) -> str:
    """Read-only plan views: any active platform staff (``support`` included). Mutations keep ``_admin``. Returns the role."""
    staff = session.scalar(select(PlatformStaff).where(PlatformStaff.user_id == user.id, PlatformStaff.is_active.is_(True)))
    if staff is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
    return staff.role


@router.get("/organizations/{organization_id}/entitlement")
def organization_entitlement(
    organization_id: UUID, request: Request, user: User = Depends(current_user), session: Session = Depends(database_session)
) -> dict[str, object]:
    staff_role = _staff(session, user)
    org = session.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "organization not found")
    ent = entitlements_for(session, organization_id)
    sub = current_subscription(session, organization_id)
    return plan_state(ent) | {
        "name": org.name, "staff_role": staff_role, "effective": ent.full(), "projection": {"plan_key": org.plan_key, "source": org.entitlement_source},
        "trial_started_at": org.trial_started_at.isoformat() if org.trial_started_at else None,
        "subscription": None if sub is None else {"status": sub.status, "plan_key": sub.plan_key, "seats": sub.seats,
                                                  "provider": sub.provider},
        "comps": [serialize_comp(comp) for comp in CompService(session, request.app.state.settings).list_for(organization_id)],
    }


@router.post("/organizations/{organization_id}/comps", status_code=status.HTTP_201_CREATED)
def grant_comp(
    organization_id: UUID, payload: CompInput, request: Request, user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    _admin(session, user)
    try:
        comp, has_subscription = CompService(session, request.app.state.settings).grant(
            organization_id=organization_id, actor_user_id=user.id, plan_key=payload.plan_key, reason=payload.reason,
            expires_at=payload.expires_at, limits_override=payload.limits_override, permanent=payload.permanent)
    except CompInvalid as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return serialize_comp(comp) | {"warning": "active_subscription" if has_subscription else None}


@router.patch("/organizations/{organization_id}/comps/{comp_id}")
def extend_comp(
    organization_id: UUID, comp_id: UUID, payload: CompExtendInput, request: Request,
    user: User = Depends(current_user), session: Session = Depends(database_session),
) -> dict[str, object]:
    _admin(session, user)
    try:
        comp = CompService(session, request.app.state.settings).extend(
            organization_id=organization_id, comp_id=comp_id, actor_user_id=user.id, expires_at=payload.expires_at)
    except CompInvalid as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return serialize_comp(comp)


@router.delete("/organizations/{organization_id}/comps/{comp_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_comp(
    organization_id: UUID, comp_id: UUID, request: Request, user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> None:
    _admin(session, user)
    try:
        CompService(session, request.app.state.settings).revoke(
            organization_id=organization_id, comp_id=comp_id, actor_user_id=user.id)
    except CompInvalid as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "comp not found") from error


@router.get("/comps")
def list_comps(
    expiring_within: int | None = None, user: User = Depends(current_user), session: Session = Depends(database_session)
) -> list[dict[str, object]]:
    """Live comps; ``expiring_within`` (days) keeps permanent ones and those ending inside the window."""
    from datetime import UTC, timedelta

    _staff(session, user)
    now = datetime.now(UTC)
    rows = session.scalars(select(OrganizationComp).where(OrganizationComp.revoked_at.is_(None)))
    result = []
    for comp in rows:
        expires = comp.expires_at.replace(tzinfo=UTC) if comp.expires_at and comp.expires_at.tzinfo is None else comp.expires_at
        if expires is not None and expires <= now:
            continue
        if expiring_within is not None and expires is not None and expires > now + timedelta(days=expiring_within):
            continue
        result.append(serialize_comp(comp) | {"organization_id": str(comp.organization_id)})
    return result
