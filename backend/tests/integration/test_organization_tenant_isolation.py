from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.audit_usage.models import AuditLog
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.auth import IdentityService, VerifiedIdentity
from app.identity.models import (  # Imports register all tables used by this test.
    AuthIdentity,
    User,
    UserSession,
)
from app.integrations.google_drive import (
    CredentialCipher,
    GoogleAccessDenied,
    GoogleConnectionService,
    GoogleCredentials,
    RemoteFolder,
)
from app.integrations.models import DataSource
from app.organizations.models import MembershipRole
from app.organizations.service import MembershipAlreadyExists, OrganizationService
from app.workspaces.models import WorkspaceFolder
from app.workspaces.service import WorkspaceService

pytestmark = pytest.mark.postgres


@pytest.fixture()
def session(test_database_url: str):
    """Use only a disposable PostgreSQL database supplied by the test runner."""
    engine = create_engine(test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database_session:
        yield database_session
        database_session.rollback()
    Base.metadata.drop_all(engine)
    engine.dispose()


def create_user(session: Session, email: str) -> User:
    user = User(id=uuid4(), email=email)
    session.add(user)
    session.flush()
    return user


def test_membership_is_unique_per_organization_but_not_globally(session: Session) -> None:
    service = OrganizationService(session)
    first_org, _, _ = service.create_organization(name="First", owner_email="owner@first.test")
    second_org, _, _ = service.create_organization(name="Second", owner_email="owner@second.test")
    member = create_user(session, "member@example.test")
    session.commit()

    service.add_membership(
        scope=OrganizationScope(first_org.id), user_id=member.id, role=MembershipRole.MEMBER
    )
    session.commit()

    with pytest.raises(MembershipAlreadyExists):
        service.add_membership(
            scope=OrganizationScope(first_org.id), user_id=member.id, role=MembershipRole.ADMIN
        )

    # The service rolls back after the duplicate attempt; obtaining the same
    # user in another tenant remains a valid, independent membership.
    service.add_membership(
        scope=OrganizationScope(second_org.id), user_id=member.id, role=MembershipRole.MEMBER
    )
    session.commit()


def test_cross_organization_membership_lookup_returns_no_result(session: Session) -> None:
    service = OrganizationService(session)
    first_org, _, _ = service.create_organization(name="First", owner_email="owner@first.test")
    second_org, _, _ = service.create_organization(name="Second", owner_email="owner@second.test")
    member = create_user(session, "member@example.test")
    session.commit()
    membership = service.add_membership(
        scope=OrganizationScope(first_org.id), user_id=member.id, role=MembershipRole.MEMBER
    )
    session.commit()

    assert service.get_membership(
        scope=OrganizationScope(second_org.id), membership_id=membership.id
    ) is None
    assert service.get_membership(
        scope=OrganizationScope(first_org.id), membership_id=membership.id
    ).id == membership.id


def test_membership_creation_writes_a_scoped_audit_record(session: Session) -> None:
    service = OrganizationService(session)
    organization, owner, owner_membership = service.create_organization(
        name="Audited", owner_email="owner@audited.test"
    )
    session.commit()

    owner_audit = session.scalar(
        select(AuditLog).where(
            AuditLog.organization_id == organization.id,
            AuditLog.target_id == owner_membership.id,
        )
    )
    assert owner_audit is not None
    assert owner_audit.actor_user_id == owner.id
    assert owner_audit.action == "membership.created"
    assert owner_audit.target_type == "membership"


def test_postgres_keeps_same_email_identities_separate_by_provider_subject(session: Session) -> None:
    identity_service = IdentityService(session)
    first_user = identity_service.establish_identity(
        VerifiedIdentity(provider="workos", subject="subject-one", email="same@example.test")
    )
    second_user = identity_service.establish_identity(
        VerifiedIdentity(provider="workos", subject="subject-two", email="same@example.test")
    )
    identity_service.create_session(user_id=first_user.id, ttl_hours=1)
    identity_service.create_session(user_id=second_user.id, ttl_hours=1)
    session.commit()

    assert first_user.id != second_user.id
    assert session.query(User).filter(User.email == "same@example.test").count() == 2
    assert session.query(AuthIdentity).count() == 2
    assert session.query(UserSession).count() == 2

    organization, returned_owner, membership = OrganizationService(session).create_organization(
        name="Subject owned", owner_email="same@example.test", owner_user_id=first_user.id
    )
    session.commit()
    assert returned_owner.id == first_user.id
    assert membership.user_id == first_user.id
    assert membership.organization_id == organization.id


class PostgreSQLGooglePort:
    def authorization_url(self, *, state: str, scope: str) -> str:
        return "https://google.example.test/oauth"

    def exchange_code(self, *, code: str) -> GoogleCredentials:
        return GoogleCredentials("access", "refresh", None)

    def list_folders(self, *, credentials: GoogleCredentials) -> list[RemoteFolder]:
        return [RemoteFolder("folder-1", "Client A")]


def test_postgres_source_and_workspace_folder_are_tenant_scoped_and_idempotent(session: Session) -> None:
    organizations = OrganizationService(session)
    organization_a, owner_a, _ = organizations.create_organization(name="A", owner_email="owner-a@test")
    organization_b, owner_b, _ = organizations.create_organization(name="B", owner_email="owner-b@test")
    cipher = CredentialCipher(Fernet.generate_key().decode())
    source = DataSource(
        organization_id=organization_a.id,
        provider="google_drive",
        encrypted_credentials=cipher.encrypt(GoogleCredentials("access", "refresh", None)),
        status="connected",
        connected_by_user_id=owner_a.id,
    )
    session.add(source)
    session.commit()

    workspace_service = WorkspaceService(session)
    first = workspace_service.select_folder(
        scope=OrganizationScope(organization_a.id),
        user_id=owner_a.id,
        source_id=source.id,
        external_folder_id="folder-1",
        name="Client A",
        uniform_access_confirmed=True,
        available_folder_ids={"folder-1"},
    )
    second = workspace_service.select_folder(
        scope=OrganizationScope(organization_a.id),
        user_id=owner_a.id,
        source_id=source.id,
        external_folder_id="folder-1",
        name="Renamed remotely",
        uniform_access_confirmed=True,
        available_folder_ids={"folder-1"},
    )
    session.commit()

    assert first.id == second.id
    assert session.query(WorkspaceFolder).count() == 1
    assert GoogleConnectionService(session, cipher).folders(
        scope=OrganizationScope(organization_a.id),
        user_id=owner_a.id,
        source_id=source.id,
        port=PostgreSQLGooglePort(),
    ) == [RemoteFolder("folder-1", "Client A")]
    with pytest.raises(GoogleAccessDenied):
        workspace_service.select_folder(
            scope=OrganizationScope(organization_b.id),
            user_id=owner_b.id,
            source_id=source.id,
            external_folder_id="folder-1",
            name="Cross tenant",
            uniform_access_confirmed=True,
            available_folder_ids={"folder-1"},
        )
