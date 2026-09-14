from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.audit_usage.models import AuditLog
from app.core.scoping import OrganizationScope, TenantScopeRequired
from app.identity.models import User
from app.organizations.models import MembershipRole
from app.organizations.service import MembershipAlreadyExists, OrganizationService


class FakeSession:
    """Small session double for domain-service behavior that needs no database."""

    def __init__(self, scalar_result: object | None = None, flush_error: Exception | None = None) -> None:
        self.scalar_result = scalar_result
        self.flush_error = flush_error
        self.added: list[object] = []
        self.flush_count = 0
        self.rollback_count = 0
        self.last_statement: object | None = None

    def scalar(self, statement: object) -> object | None:
        self.last_statement = statement
        return self.scalar_result

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        self.flush_count += 1
        if self.flush_error is not None:
            raise self.flush_error

    def rollback(self) -> None:
        self.rollback_count += 1


def test_create_organization_creates_active_owner_membership() -> None:
    session = FakeSession()

    organization, user, membership = OrganizationService(session).create_organization(
        name="Acme", owner_email="owner@acme.test"
    )

    assert organization.name == "Acme"
    assert user.email == "owner@acme.test"
    assert membership.organization_id == organization.id
    assert membership.user_id == user.id
    assert membership.role is MembershipRole.OWNER
    assert membership.is_active is True
    audit_log = session.added[-1]
    assert session.added[:-1] == [user, organization, membership]
    assert isinstance(audit_log, AuditLog)
    assert audit_log.organization_id == organization.id
    assert audit_log.actor_user_id == user.id
    assert audit_log.action == "membership.created"
    assert audit_log.target_type == "membership"
    assert audit_log.target_id == membership.id


def test_create_organization_reuses_existing_user() -> None:
    existing_user = User(id=uuid4(), email="owner@acme.test")
    session = FakeSession(scalar_result=existing_user)

    organization, user, membership = OrganizationService(session).create_organization(
        name="Acme", owner_email="owner@acme.test"
    )

    assert user is existing_user
    assert membership.user_id == existing_user.id
    assert session.added[:-1] == [organization, membership]
    assert isinstance(session.added[-1], AuditLog)


def test_add_membership_requires_an_organization_scope() -> None:
    with pytest.raises(TenantScopeRequired):
        OrganizationScope(organization_id=None)  # type: ignore[arg-type]


def test_add_membership_assigns_scope_tenant_and_active_role() -> None:
    session = FakeSession()
    organization_id, user_id = uuid4(), uuid4()

    membership = OrganizationService(session).add_membership(
        scope=OrganizationScope(organization_id), user_id=user_id, role=MembershipRole.MEMBER
    )

    assert membership.organization_id == organization_id
    assert membership.user_id == user_id
    assert membership.role is MembershipRole.MEMBER
    assert membership.is_active is True
    audit_log = session.added[-1]
    assert session.added[:-1] == [membership]
    assert isinstance(audit_log, AuditLog)
    assert audit_log.organization_id == organization_id
    assert audit_log.actor_user_id == user_id
    assert audit_log.target_id == membership.id


def test_add_membership_records_actor_in_audit_log() -> None:
    session = FakeSession()
    organization_id, user_id, actor_user_id = uuid4(), uuid4(), uuid4()

    membership = OrganizationService(session).add_membership(
        scope=OrganizationScope(organization_id),
        user_id=user_id,
        role=MembershipRole.ADMIN,
        actor_user_id=actor_user_id,
    )

    audit_log = session.added[-1]
    assert isinstance(audit_log, AuditLog)
    assert audit_log.organization_id == organization_id
    assert audit_log.actor_user_id == actor_user_id
    assert audit_log.action == "membership.created"
    assert audit_log.target_type == "membership"
    assert audit_log.target_id == membership.id


def test_add_membership_translates_uniqueness_error_to_domain_conflict() -> None:
    session = FakeSession(flush_error=IntegrityError("INSERT", {}, Exception("duplicate")))

    with pytest.raises(MembershipAlreadyExists):
        OrganizationService(session).add_membership(
            scope=OrganizationScope(uuid4()), user_id=uuid4(), role=MembershipRole.ADMIN
        )

    assert session.rollback_count == 1


def test_get_membership_query_is_always_scoped_to_organization() -> None:
    session = FakeSession(scalar_result=None)
    organization_id, membership_id = uuid4(), uuid4()

    result = OrganizationService(session).get_membership(
        scope=OrganizationScope(organization_id), membership_id=membership_id
    )

    assert result is None
    assert session.last_statement is not None
    compiled_sql = str(session.last_statement.compile(compile_kwargs={"literal_binds": True}))
    assert "memberships.organization_id" in compiled_sql
    # SQLAlchemy renders UUID literals without hyphens for this dialect.
    assert organization_id.hex in compiled_sql
    assert membership_id.hex in compiled_sql
