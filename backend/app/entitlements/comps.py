"""Courtesy plans ("comps") managed by platform admins. Every change is audited; the detail lives on the comp row."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_usage.models import AuditLog
from app.core.config import Settings
from app.entitlements.catalog import TRIAL_PLAN, account_type_of
from app.entitlements.resolver import (
    _aware,
    current_subscription,
    invalidate,
    project,
    validate_limits_override,
)
from app.organizations.models import Organization, OrganizationComp, PlatformStaff


class CompDenied(PermissionError):
    pass


class CompInvalid(ValueError):
    pass


COMPABLE_PLANS = {"personal_basic", "personal_pro", "business_team", "business_scale", *TRIAL_PLAN.values()}


def require_platform_admin(session: Session, user_id: UUID) -> PlatformStaff:
    staff = session.scalar(select(PlatformStaff).where(
        PlatformStaff.user_id == user_id, PlatformStaff.is_active.is_(True)))
    if staff is None or staff.role != "admin":
        raise CompDenied("platform admin required")
    return staff


class CompService:
    def __init__(self, session: Session, settings: Settings):
        self.session, self.settings = session, settings

    def _audit(self, org_id: UUID, actor: UUID, action: str, comp: OrganizationComp) -> None:
        self.session.add(AuditLog(organization_id=org_id, actor_user_id=actor, action=action,
                                  target_type="organization_comp", target_id=comp.id))
        self.session.flush()

    def grant(
        self, *, organization_id: UUID, actor_user_id: UUID, plan_key: str, reason: str, expires_at: datetime | None,
        limits_override: dict | None = None, permanent: bool = False,
    ) -> tuple[OrganizationComp, bool]:
        """Returns the comp and whether the organization still has a paid subscription (warning for the operator)."""
        org = self.session.scalar(select(Organization).where(Organization.id == organization_id).with_for_update())
        reason = (reason or "").strip()
        if org is None:
            raise CompInvalid("organization not found")
        if not reason or len(reason) > 240:
            raise CompInvalid("a reason of up to 240 characters is required")
        if plan_key not in COMPABLE_PLANS or account_type_of(plan_key) != org.account_type:
            raise CompInvalid("plan does not match the account type")
        if expires_at is None and not permanent:
            raise CompInvalid("expires_at is required unless the comp is explicitly permanent")
        if expires_at is not None and _aware(expires_at) <= datetime.now(UTC):
            raise CompInvalid("expires_at must be in the future")
        clean = validate_limits_override(limits_override)
        previous = self.session.scalar(select(OrganizationComp).where(
            OrganizationComp.organization_id == organization_id, OrganizationComp.revoked_at.is_(None)))
        if previous is not None:
            previous.revoked_at, previous.revoked_by_user_id = datetime.now(UTC), actor_user_id
            self.session.flush()  # keeps the one-active-comp unique index valid
        comp = OrganizationComp(
            organization_id=organization_id, plan_key=plan_key, limits_override=clean or None,
            expires_at=_aware(expires_at), reason=reason, granted_by_user_id=actor_user_id)
        self.session.add(comp)
        self.session.flush()
        self._audit(organization_id, actor_user_id, "comp.granted", comp)
        project(self.session, org, self.settings)
        sub = current_subscription(self.session, organization_id)
        return comp, sub is not None and sub.status in {"active", "trialing", "past_due"}

    def extend(self, *, organization_id: UUID, comp_id: UUID, actor_user_id: UUID, expires_at: datetime) -> OrganizationComp:
        comp = self._live(organization_id, comp_id)
        if _aware(expires_at) <= datetime.now(UTC):
            raise CompInvalid("expires_at must be in the future")
        comp.expires_at = _aware(expires_at)
        self.session.flush()
        self._audit(organization_id, actor_user_id, "comp.extended", comp)
        self._refresh(organization_id)
        return comp

    def revoke(self, *, organization_id: UUID, comp_id: UUID, actor_user_id: UUID) -> OrganizationComp:
        comp = self._live(organization_id, comp_id)
        comp.revoked_at, comp.revoked_by_user_id = datetime.now(UTC), actor_user_id
        self.session.flush()
        self._audit(organization_id, actor_user_id, "comp.revoked", comp)
        self._refresh(organization_id)
        return comp

    def list_for(self, organization_id: UUID) -> list[OrganizationComp]:
        return list(self.session.scalars(select(OrganizationComp).where(
            OrganizationComp.organization_id == organization_id).order_by(OrganizationComp.created_at.desc())))

    def _live(self, organization_id: UUID, comp_id: UUID) -> OrganizationComp:
        comp = self.session.get(OrganizationComp, comp_id)
        if comp is None or comp.organization_id != organization_id or comp.revoked_at is not None:
            raise CompInvalid("comp not found")
        return comp

    def _refresh(self, organization_id: UUID) -> None:
        org = self.session.get(Organization, organization_id)
        invalidate(self.session, organization_id)
        if org is not None:
            project(self.session, org, self.settings)


def serialize_comp(comp: OrganizationComp) -> dict[str, object]:
    return {
        "id": str(comp.id), "plan_key": comp.plan_key, "limits_override": comp.limits_override, "reason": comp.reason,
        "expires_at": _aware(comp.expires_at).isoformat() if comp.expires_at else None,
        "revoked_at": _aware(comp.revoked_at).isoformat() if comp.revoked_at else None,
        "granted_by_user_id": str(comp.granted_by_user_id),
    }
