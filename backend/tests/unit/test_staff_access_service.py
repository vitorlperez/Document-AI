from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.audit_usage.models import AuditLog
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.integrations.models import DataSource  # noqa: F401
from app.organizations.models import Organization, PlatformStaff, StaffAccessGrant
from app.organizations.staff_access import PlatformStaffAccessService, StaffAccessDenied
from app.workspaces.models import WorkspaceFolder  # noqa: F401


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_staff_grant_is_explicit_expiring_and_audited(session: Session) -> None:
    organization = Organization(name="Acme")
    staff_user = User(email="support@example.test")
    issuer = User(email="operator@example.test")
    session.add_all([organization, staff_user, issuer])
    session.flush()
    staff = PlatformStaff(user_id=staff_user.id)
    session.add(staff)
    session.flush()
    service = PlatformStaffAccessService(session)

    grant = service.grant_metadata_access(
        platform_staff_id=staff.id,
        organization_id=organization.id,
        granted_by_user_id=issuer.id,
        reason="Investigate synchronization health",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    company = service.require_metadata_access(user_id=staff_user.id, scope=OrganizationScope(organization.id))
    service.record_metadata_access(user_id=staff_user.id, company=company)

    assert service.is_platform_staff(user_id=staff_user.id)
    assert company.grant_id == grant.id
    assert {audit.action for audit in session.scalars(select(AuditLog))} == {
        "staff_access.granted",
        "staff_access.metadata_viewed",
    }

    service.revoke_metadata_access(grant_id=grant.id, revoked_by_user_id=issuer.id)
    with pytest.raises(StaffAccessDenied):
        service.require_metadata_access(user_id=staff_user.id, scope=OrganizationScope(organization.id))


def test_staff_cannot_access_an_ungranted_or_expired_company(session: Session) -> None:
    organization = Organization(name="A")
    other_organization = Organization(name="B")
    staff_user = User(email="support@example.test")
    issuer = User(email="operator@example.test")
    session.add_all([organization, other_organization, staff_user, issuer])
    session.flush()
    staff = PlatformStaff(user_id=staff_user.id)
    session.add(staff)
    session.flush()
    service = PlatformStaffAccessService(session)
    session.add(
        StaffAccessGrant(
            platform_staff_id=staff.id,
            organization_id=organization.id,
            granted_by_user_id=issuer.id,
            reason="Expired support request",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    session.flush()

    with pytest.raises(StaffAccessDenied):
        service.require_metadata_access(user_id=staff_user.id, scope=OrganizationScope(organization.id))
    with pytest.raises(StaffAccessDenied):
        service.require_metadata_access(user_id=staff_user.id, scope=OrganizationScope(other_organization.id))
    assert not service.is_platform_staff(user_id=uuid4())
