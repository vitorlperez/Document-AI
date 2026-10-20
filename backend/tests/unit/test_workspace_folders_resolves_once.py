"""C4: the Fontes listing resolves the caller's access once, not twice."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.spaces.access import SpaceAccessResolver
from app.workspaces.service import WorkspaceService
from tests.spaces_helpers import seed_world


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


@pytest.mark.parametrize("who", ["bruno", "eva"])
def test_folders_with_spaces_resolves_access_once(session, monkeypatch, who):
    world = seed_world(session)
    calls = []
    original = SpaceAccessResolver.resolve
    monkeypatch.setattr(SpaceAccessResolver, "resolve", lambda self, **kw: calls.append(1) or original(self, **kw))
    rows = WorkspaceService(session).folders_with_spaces(scope=OrganizationScope(world.organization_id), user_id=world.users[who])
    assert len(calls) == 1
    assert {folder.name for folder, _, _ in rows} == ({"politicas", "rh"} if who == "bruno" else {"politicas", "rh", "diretoria"})
