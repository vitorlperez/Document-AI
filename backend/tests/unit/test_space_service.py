import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.audit_usage.models import AuditLog
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.integrations.models import DataSource
from app.organizations.models import Membership, MembershipRole, Organization
from app.spaces.models import SpaceMember
from app.spaces.service import SpaceConflict, SpaceDenied, SpaceNotFound, SpaceService
from app.workspaces.models import WorkspaceFolder


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


class World:
    pass


def _org(session, name="Acme", roles=None):
    world = World()
    org = Organization(name=name)
    session.add(org)
    session.flush()
    world.org, world.scope = org, OrganizationScope(org.id)
    world.users = {}
    for who, role, active in roles or (
        ("eva", MembershipRole.OWNER, True), ("ana", MembershipRole.MEMBER, True),
        ("bruno", MembershipRole.MEMBER, True), ("gone", MembershipRole.MEMBER, False),
    ):
        user = User(email=f"{who}-{name}@example.test")
        session.add(user)
        session.flush()
        session.add(Membership(organization_id=org.id, user_id=user.id, role=role, is_active=active))
        world.users[who] = user.id
    source = DataSource(organization_id=org.id, provider="google_drive", encrypted_credentials="x",
                        status="connected", connected_by_user_id=world.users["eva"])
    session.add(source)
    session.flush()
    folder = WorkspaceFolder(organization_id=org.id, source_id=source.id, external_folder_id="f", name="f",
                             uniform_access_confirmed=True, status="ready")
    session.add(folder)
    session.flush()
    world.folder = folder.id
    session.flush()
    return world


def _audits(session, action):
    return session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == action))


def test_only_admins_create_spaces(session):
    w = _org(session)
    service = SpaceService(session)
    with pytest.raises(SpaceDenied):
        service.create_space(w.scope, w.users["ana"], "RH")
    space = service.create_space(w.scope, w.users["eva"], "  RH ")
    assert (space.name, space.name_key) == ("RH", "rh")


def test_duplicate_active_name_conflicts(session):
    w = _org(session)
    service = SpaceService(session)
    first = service.create_space(w.scope, w.users["eva"], "RH")
    with pytest.raises(SpaceConflict):
        service.create_space(w.scope, w.users["eva"], "rh")
    service.archive_space(w.scope, w.users["eva"], first.id)
    assert service.create_space(w.scope, w.users["eva"], "RH").id != first.id


def test_manager_manages_only_own_space(session):
    w = _org(session)
    service = SpaceService(session)
    rh = service.create_space(w.scope, w.users["eva"], "RH")
    diretoria = service.create_space(w.scope, w.users["eva"], "Diretoria")
    service.add_member(w.scope, w.users["eva"], rh.id, w.users["ana"], role="manager")
    service.add_member(w.scope, w.users["ana"], rh.id, w.users["bruno"])  # manager adds to own Space
    with pytest.raises(SpaceNotFound):  # ana cannot even see Diretoria
        service.add_member(w.scope, w.users["ana"], diretoria.id, w.users["bruno"])
    with pytest.raises(SpaceDenied):  # plain member cannot manage
        service.remove_member(w.scope, w.users["bruno"], rh.id, w.users["ana"])
    with pytest.raises(SpaceDenied):  # managers do not assign folders
        service.grant_folder(w.scope, w.users["ana"], rh.id, w.folder, {"text_version": "v1"})


def test_cannot_add_user_without_active_membership(session):
    w = _org(session)
    other = _org(session, "Other", roles=(("eva", MembershipRole.OWNER, True),))
    service = SpaceService(session)
    rh = service.create_space(w.scope, w.users["eva"], "RH")
    with pytest.raises(SpaceDenied):
        service.add_member(w.scope, w.users["eva"], rh.id, w.users["gone"])  # inactive membership
    with pytest.raises(SpaceDenied):
        service.add_member(w.scope, w.users["eva"], rh.id, other.users["eva"])  # user of another org


def test_add_member_is_idempotent_and_remove_is_logical(session):
    w = _org(session)
    service = SpaceService(session)
    rh = service.create_space(w.scope, w.users["eva"], "RH")
    first = service.add_member(w.scope, w.users["eva"], rh.id, w.users["bruno"])
    assert service.add_member(w.scope, w.users["eva"], rh.id, w.users["bruno"]).id == first.id
    removed = service.remove_member(w.scope, w.users["eva"], rh.id, w.users["bruno"])
    assert removed.removed_at is not None and removed.removed_by_user_id == w.users["eva"]
    again = service.add_member(w.scope, w.users["eva"], rh.id, w.users["bruno"])
    assert again.id != first.id and again.removed_at is None
    rows = session.scalars(select(SpaceMember).where(SpaceMember.user_id == w.users["bruno"])).all()
    assert len(rows) == 2  # history kept


def test_grant_requires_disclosure_and_same_org_folder(session):
    w = _org(session)
    other = _org(session, "Other", roles=(("eva", MembershipRole.OWNER, True),))
    service = SpaceService(session)
    rh = service.create_space(w.scope, w.users["eva"], "RH")
    with pytest.raises(ValueError):
        service.grant_folder(w.scope, w.users["eva"], rh.id, w.folder, {})
    with pytest.raises(SpaceDenied):
        service.grant_folder(w.scope, w.users["eva"], rh.id, other.folder, {"text_version": "v1"})
    grant = service.grant_folder(w.scope, w.users["eva"], rh.id, w.folder, {"text_version": "v1"})
    assert service.grant_folder(w.scope, w.users["eva"], rh.id, w.folder, {"text_version": "v1"}).id == grant.id
    service.revoke_folder(w.scope, w.users["eva"], rh.id, w.folder)
    session.refresh(grant)
    assert grant.revoked_at is not None


def test_every_mutation_writes_an_audit_log(session):
    w = _org(session)
    service = SpaceService(session)
    rh = service.create_space(w.scope, w.users["eva"], "RH")
    service.rename_space(w.scope, w.users["eva"], rh.id, "People", None)
    service.add_member(w.scope, w.users["eva"], rh.id, w.users["ana"])
    service.set_member_role(w.scope, w.users["eva"], rh.id, w.users["ana"], "manager")
    service.add_member(w.scope, w.users["eva"], rh.id, w.users["bruno"], role="manager")  # a Space keeps a manager
    service.grant_folder(w.scope, w.users["eva"], rh.id, w.folder, {"text_version": "v1"})
    service.revoke_folder(w.scope, w.users["eva"], rh.id, w.folder)
    service.remove_member(w.scope, w.users["eva"], rh.id, w.users["ana"])
    service.archive_space(w.scope, w.users["eva"], rh.id)
    for action in ("created", "renamed", "member_added", "member_role_changed", "folder_granted",
                   "folder_revoked", "member_removed", "archived"):
        assert _audits(session, f"space.{action}") >= 1, action


def test_foreign_org_space_is_not_found(session):
    w = _org(session)
    other = _org(session, "Other", roles=(("eva", MembershipRole.OWNER, True),))
    service = SpaceService(session)
    theirs = service.create_space(other.scope, other.users["eva"], "RH")
    with pytest.raises(SpaceNotFound):
        service.rename_space(w.scope, w.users["eva"], theirs.id, "X", None)
    with pytest.raises(SpaceNotFound):
        service.members(w.scope, w.users["eva"], theirs.id)


def test_listing_shows_admins_everything_and_members_only_their_spaces(session):
    w = _org(session)
    service = SpaceService(session)
    rh = service.create_space(w.scope, w.users["eva"], "RH")
    service.create_space(w.scope, w.users["eva"], "Diretoria")
    service.add_member(w.scope, w.users["eva"], rh.id, w.users["bruno"])
    assert [v.name for v in service.list_spaces_for_actor(w.scope, w.users["bruno"])] == ["RH"]
    assert [v.name for v in service.list_spaces_for_actor(w.scope, w.users["eva"])] == ["Diretoria", "RH"]
    view = service.list_spaces_for_actor(w.scope, w.users["bruno"])[0]
    assert (view.member_count, view.my_role) == (1, "member")


def test_default_space_cannot_be_archived_and_default_moves(session):
    w = _org(session)
    service = SpaceService(session)
    geral = service.create_space(w.scope, w.users["eva"], "Geral", is_default=True)
    rh = service.create_space(w.scope, w.users["eva"], "RH")
    assert SpaceService.default_space_id(session, w.org.id) == geral.id
    with pytest.raises(SpaceConflict):
        service.archive_space(w.scope, w.users["eva"], geral.id)
    service.set_default(w.scope, w.users["eva"], rh.id)
    assert SpaceService.default_space_id(session, w.org.id) == rh.id
