from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.integrations.models import DataSource
from app.organizations.models import Membership, MembershipRole, Organization
from app.organizations.service import OrganizationService
from app.spaces.models import Space, SpaceFolderGrant, SpaceMember
from app.spaces.service import SpaceService
from app.workspaces.service import WorkspaceScope, WorkspaceService


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def _org(session):
    service = OrganizationService(session)
    org, owner, _ = service.create_organization(name="Acme", owner_email="eva@example.test")
    return service, OrganizationScope(org.id), org, owner


def _source(session, org, owner):
    source = DataSource(organization_id=org.id, provider="google_drive", encrypted_credentials="x",
                        status="connected", connected_by_user_id=owner.id)
    session.add(source)
    session.flush()
    return source


def _select(session, scope, owner, source, key, **kwargs):
    return WorkspaceService(session).select_scope(
        scope=scope, user_id=owner.id, source_id=source.id,
        requested=WorkspaceScope(mode="selected", folder_ids=(key,)), uniform_access_confirmed=True,
        available_folder_names={key: key}, **kwargs)


def _active_members(session, space_id):
    return session.scalars(select(SpaceMember).where(
        SpaceMember.space_id == space_id, SpaceMember.removed_at.is_(None))).all()


def _grants(session):
    return session.scalar(select(func.count()).select_from(SpaceFolderGrant))


def test_new_org_gets_geral_with_owner_manager_and_configured_mode(session, monkeypatch):
    monkeypatch.setenv("SPACES_NEW_ORG_MODE", "enforce")
    _, _, org, owner = _org(session)
    space = session.scalar(select(Space).where(Space.organization_id == org.id))
    assert (space.name, space.is_default) == ("Geral", True)
    [member] = _active_members(session, space.id)
    assert (member.user_id, member.role) == (owner.id, "manager")
    assert session.get(Organization, org.id).spaces_resolver_mode == "enforce"


def test_new_org_defaults_to_shadow_mode(session, monkeypatch):
    monkeypatch.delenv("SPACES_NEW_ORG_MODE", raising=False)
    _, _, org, _ = _org(session)
    assert session.get(Organization, org.id).spaces_resolver_mode == "shadow"


def test_add_membership_joins_default_space(session):
    service, scope, org, owner = _org(session)
    newcomer = User(email="n@example.test")
    session.add(newcomer)
    session.flush()
    service.add_membership(scope=scope, user_id=newcomer.id, role=MembershipRole.MEMBER, actor_user_id=owner.id)
    geral = SpaceService.default_space_id(session, org.id)
    assert newcomer.id in {m.user_id for m in _active_members(session, geral)}


def test_accept_invitation_joins_default_space(session):
    service, scope, org, owner = _org(session)
    _, token = service.create_invitation(scope=scope, actor_user_id=owner.id, email="n@example.test",
                                         role=MembershipRole.MEMBER)
    user = User(email="n@example.test")
    session.add(user)
    session.flush()
    service.accept_invitation(raw_token=token, user=user)
    geral = SpaceService.default_space_id(session, org.id)
    assert user.id in {m.user_id for m in _active_members(session, geral)}


def test_accept_invitation_with_space_ids_joins_only_those(session):
    service, scope, org, owner = _org(session)
    rh = SpaceService(session).create_space(scope, owner.id, "RH")
    _, token = service.create_invitation(scope=scope, actor_user_id=owner.id, email="n@example.test",
                                         role=MembershipRole.MEMBER, space_ids=[rh.id, uuid4()])
    user = User(email="n@example.test")
    session.add(user)
    session.flush()
    service.accept_invitation(raw_token=token, user=user)
    geral = SpaceService.default_space_id(session, org.id)
    assert user.id in {m.user_id for m in _active_members(session, rh.id)}
    assert user.id not in {m.user_id for m in _active_members(session, geral)}  # unknown id ignored, no Geral


def test_select_scope_without_space_ids_grants_default_space(session):
    _, scope, org, owner = _org(session)
    source = _source(session, org, owner)
    folder = _select(session, scope, owner, source, "a")
    grant = session.scalar(select(SpaceFolderGrant).where(SpaceFolderGrant.workspace_folder_id == folder.id))
    assert grant.space_id == SpaceService.default_space_id(session, org.id)
    assert grant.disclosure["text_version"] == "v1"


def test_select_scope_with_space_ids_grants_each_and_records_disclosure(session):
    _, scope, org, owner = _org(session)
    spaces = SpaceService(session)
    rh, dir_ = spaces.create_space(scope, owner.id, "RH"), spaces.create_space(scope, owner.id, "Diretoria")
    source = _source(session, org, owner)
    folder = _select(session, scope, owner, source, "a", space_ids=[rh.id, dir_.id])
    granted = session.scalars(select(SpaceFolderGrant.space_id).where(
        SpaceFolderGrant.workspace_folder_id == folder.id)).all()
    assert set(granted) == {rh.id, dir_.id}  # explicit list: not the default Space
    with pytest.raises(ValueError):
        _select(session, scope, owner, source, "b", space_ids=[uuid4()])


def test_select_scope_second_call_does_not_duplicate_grant(session):
    _, scope, org, owner = _org(session)
    source = _source(session, org, owner)
    first = _select(session, scope, owner, source, "a")
    before = _grants(session)
    second = _select(session, scope, owner, source, "a")
    assert second.id == first.id and _grants(session) == before


def test_deactivate_membership_marks_space_membership_removed(session):
    service, scope, org, owner = _org(session)
    newcomer = User(email="n@example.test")
    session.add(newcomer)
    session.flush()
    membership = service.add_membership(scope=scope, user_id=newcomer.id, role=MembershipRole.MEMBER,
                                        actor_user_id=owner.id)
    service.deactivate_membership(scope=scope, actor_user_id=owner.id, membership_id=membership.id)
    geral = SpaceService.default_space_id(session, org.id)
    assert newcomer.id not in {m.user_id for m in _active_members(session, geral)}
    assert session.scalar(select(func.count()).select_from(SpaceMember).where(
        SpaceMember.user_id == newcomer.id, SpaceMember.removed_at.is_not(None))) == 1


def test_org_without_spaces_keeps_legacy_flows_working(session):
    """Organizations that predate the backfill have no default Space: nothing to enrol, nothing to break."""
    org = Organization(name="Legacy")
    owner = User(email="l@example.test")
    session.add_all([org, owner])
    session.flush()
    session.add(Membership(organization_id=org.id, user_id=owner.id, role=MembershipRole.OWNER, is_active=True))
    source = _source(session, org, owner)
    folder = _select(session, OrganizationScope(org.id), owner, source, "a")
    assert folder.id is not None and _grants(session) == 0
