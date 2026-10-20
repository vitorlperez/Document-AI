import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.spaces.models import SpaceFolderGrant, SpaceMember
from tests.spaces_helpers import seed_world


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def test_world_matches_the_acme_example(session):
    world = seed_world(session)
    names = {v: k for k, v in world.spaces.items()}
    spaces_of = {
        who: {names[s] for s in session.scalars(select(SpaceMember.space_id).where(SpaceMember.user_id == uid))}
        for who, uid in world.users.items()
    }
    assert spaces_of == {
        "eva": {"geral"}, "ana": {"geral", "rh"}, "bruno": {"geral", "rh"},
        "carla": {"geral", "rh", "diretoria"}, "daniel": {"geral", "diretoria"},
    }
    folder_names = {v: k for k, v in world.folders.items()}
    grants = {folder_names[g.workspace_folder_id]: names[g.space_id] for g in session.scalars(select(SpaceFolderGrant))}
    assert grants == {"politicas": "geral", "rh": "rh", "diretoria": "diretoria"}
    assert set(world.documents) == set(world.folders) == {"politicas", "rh", "diretoria"}
