"""C7: invitation fallback, the last manager, and concurrent duplicate inserts are handled, not 500s."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.spaces import enrollment
from app.spaces.models import SpaceFolderGrant, SpaceMember
from app.spaces.service import SpaceConflict, SpaceService
from tests.unit.test_space_service import _org

pytestmark = pytest.mark.no_auto_spaces


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def make(session):
    world = _org(session)
    service = SpaceService(session)
    space = service.create_space(world.scope, world.users["eva"], "RH")
    return world, service, space


def test_invitation_with_only_invalid_spaces_falls_back_to_the_default_space(session):
    world = _org(session)
    service = SpaceService(session)
    default = service.create_space(world.scope, world.users["eva"], "Geral", is_default=True)
    joined = enrollment.enroll_member(session, world.org.id, world.users["ana"], [uuid4(), uuid4()])
    assert joined == [default.id]
    # a partly valid list keeps exactly the valid ones
    other = service.create_space(world.scope, world.users["eva"], "RH")
    assert enrollment.enroll_member(session, world.org.id, world.users["bruno"], [other.id, uuid4()]) == [other.id]


def test_the_last_manager_cannot_be_removed_or_demoted(session):
    world, service, space = make(session)
    service.add_member(world.scope, world.users["eva"], space.id, world.users["ana"], role="manager")
    with pytest.raises(SpaceConflict):
        service.remove_member(world.scope, world.users["eva"], space.id, world.users["ana"])
    with pytest.raises(SpaceConflict):
        service.set_member_role(world.scope, world.users["eva"], space.id, world.users["ana"], "member")
    service.add_member(world.scope, world.users["eva"], space.id, world.users["bruno"], role="manager")
    service.set_member_role(world.scope, world.users["eva"], space.id, world.users["ana"], "member")  # two managers: ok
    with pytest.raises(SpaceConflict):
        service.remove_member(world.scope, world.users["eva"], space.id, world.users["bruno"])
    # members are always removable
    service.remove_member(world.scope, world.users["eva"], space.id, world.users["ana"])


def _blind_first_lookup(session, monkeypatch, table):
    """Make the first existence check miss, as if the row were inserted by a concurrent request right after."""
    original = session.scalar
    state = {"hit": False}

    def scalar(statement, *args, **kwargs):
        if not state["hit"] and table in str(statement):
            state["hit"] = True
            return None
        return original(statement, *args, **kwargs)

    monkeypatch.setattr(session, "scalar", scalar)


def test_concurrent_duplicate_member_is_reported_as_already_there(session, monkeypatch):
    world, service, space = make(session)
    existing = service.add_member(world.scope, world.users["eva"], space.id, world.users["ana"])
    _blind_first_lookup(session, monkeypatch, "space_members.added_by_user_id")
    again = service.add_member(world.scope, world.users["eva"], space.id, world.users["ana"])
    assert again.id == existing.id
    assert len(session.scalars(select(SpaceMember).where(SpaceMember.user_id == world.users["ana"])).all()) == 1


def test_concurrent_duplicate_grant_is_reported_as_already_there(session, monkeypatch):
    world, service, space = make(session)
    disclosure = {"text_version": "v1"}
    first = service.grant_folder(world.scope, world.users["eva"], space.id, world.folder, disclosure)
    _blind_first_lookup(session, monkeypatch, "space_folder_grants.disclosure")
    again = service.grant_folder(world.scope, world.users["eva"], space.id, world.folder, disclosure)
    assert again.id == first.id
    assert len(session.scalars(select(SpaceFolderGrant)).all()) == 1
