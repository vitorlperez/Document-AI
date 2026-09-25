"""Explicit, expiring platform-staff grants without tenant membership bypasses."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_usage.models import AuditLog
from app.core.scoping import OrganizationScope
from app.organizations.models import Organization, PlatformStaff, StaffAccessGrant


class StaffAccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class GrantedCompany:
    grant_id: UUID
    organization_id: UUID
    organization_name: str
    reason: str
    expires_at: datetime


@dataclass(frozen=True)
class SupportedOrganization:
    organization_id: UUID
    organization_name: str


class PlatformStaffAccessService:
    def __init__(self, session: Session):
        self.session = session

    def is_platform_staff(self, *, user_id: UUID) -> bool:
        return self.session.scalar(
            select(PlatformStaff.id).where(PlatformStaff.user_id == user_id, PlatformStaff.is_active.is_(True))
        ) is not None

    def granted_companies(self, *, user_id: UUID) -> list[GrantedCompany]:
        now = datetime.now(UTC)
        rows = self.session.execute(
            select(StaffAccessGrant, Organization)
            .join(PlatformStaff, PlatformStaff.id == StaffAccessGrant.platform_staff_id)
            .join(Organization, Organization.id == StaffAccessGrant.organization_id)
            .where(
                PlatformStaff.user_id == user_id,
                PlatformStaff.is_active.is_(True),
                StaffAccessGrant.revoked_at.is_(None),
                StaffAccessGrant.expires_at > now,
            )
            .order_by(Organization.name, StaffAccessGrant.expires_at, StaffAccessGrant.id)
        ).all()
        return [
            GrantedCompany(
                grant_id=grant.id,
                organization_id=organization.id,
                organization_name=organization.name,
                reason=grant.reason,
                expires_at=grant.expires_at,
            )
            for grant, organization in rows
        ]

    def all_organizations(self, *, user_id: UUID) -> list[SupportedOrganization]:
        if not self.is_platform_staff(user_id=user_id):
            raise StaffAccessDenied("platform support access denied")
        return [
            SupportedOrganization(organization_id=organization.id, organization_name=organization.name)
            for organization in self.session.scalars(select(Organization).order_by(Organization.name))
        ]

    def require_organization_access(self, *, user_id: UUID, organization_id: UUID) -> SupportedOrganization:
        if not self.is_platform_staff(user_id=user_id):
            raise StaffAccessDenied("platform support access denied")
        organization = self.session.get(Organization, organization_id)
        if organization is None:
            raise StaffAccessDenied("platform support access denied")
        return SupportedOrganization(organization_id=organization.id, organization_name=organization.name)

    def record_organization_access(self, *, user_id: UUID, organization: SupportedOrganization) -> None:
        self._audit(
            organization_id=organization.organization_id,
            actor_user_id=user_id,
            action="staff_access.metadata_viewed",
            target_type="organization",
            target_id=organization.organization_id,
        )

    def require_metadata_access(self, *, user_id: UUID, scope: OrganizationScope) -> GrantedCompany:
        for company in self.granted_companies(user_id=user_id):
            if company.organization_id == scope.organization_id:
                return company
        raise StaffAccessDenied("platform support access denied")

    def grant_metadata_access(
        self,
        *,
        platform_staff_id: UUID,
        organization_id: UUID,
        granted_by_user_id: UUID,
        reason: str,
        expires_at: datetime,
    ) -> StaffAccessGrant:
        if not reason.strip() or len(reason) > 240 or expires_at <= datetime.now(UTC):
            raise ValueError("invalid staff access grant")
        staff = self.session.get(PlatformStaff, platform_staff_id)
        organization = self.session.get(Organization, organization_id)
        if staff is None or not staff.is_active or organization is None:
            raise ValueError("invalid staff access grant")
        grant = StaffAccessGrant(
            platform_staff_id=platform_staff_id,
            organization_id=organization_id,
            granted_by_user_id=granted_by_user_id,
            reason=reason.strip(),
            expires_at=expires_at,
        )
        self.session.add(grant)
        self.session.flush()
        self._audit(organization_id=organization_id, actor_user_id=granted_by_user_id, action="staff_access.granted", target_id=grant.id)
        return grant

    def revoke_metadata_access(self, *, grant_id: UUID, revoked_by_user_id: UUID) -> StaffAccessGrant:
        grant = self.session.get(StaffAccessGrant, grant_id)
        if grant is None or grant.revoked_at is not None:
            raise ValueError("invalid staff access grant")
        grant.revoked_at = datetime.now(UTC)
        self._audit(
            organization_id=grant.organization_id,
            actor_user_id=revoked_by_user_id,
            action="staff_access.revoked",
            target_id=grant.id,
        )
        self.session.flush()
        return grant

    def record_metadata_access(self, *, user_id: UUID, company: GrantedCompany) -> None:
        self._audit(
            organization_id=company.organization_id,
            actor_user_id=user_id,
            action="staff_access.metadata_viewed",
            target_id=company.grant_id,
        )

    def _audit(
        self, *, organization_id: UUID, actor_user_id: UUID, action: str, target_id: UUID, target_type: str = "staff_access_grant"
    ) -> None:
        self.session.add(
            AuditLog(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
            )
        )
        self.session.flush()
