import io

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.identity.models import User
from app.organizations.models import Membership, MembershipRole
from app.spaces.models import SpaceFolderGrant, SpaceMember
from app.spaces.rollout import run
from tests.spaces_helpers import seed_world


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def _cli(session, *argv):
    out = io.StringIO()
    code = run(list(argv), session, out)
    return code, out.getvalue()


def test_report_is_clean_for_a_covered_organization(session):
    world = seed_world(session)
    session.commit()
    code, text = _cli(session, "report", "--organization", str(world.organization_id))
    assert code == 0 and "folders_without_space=0 people_without_space=0 clean=true" in text


def test_report_flags_a_folder_without_space(session):
    world = seed_world(session)
    session.execute(delete(SpaceFolderGrant).where(SpaceFolderGrant.workspace_folder_id == world.folders["rh"]))
    session.commit()
    code, text = _cli(session, "report")
    assert code == 2 and "folders_without_space=1" in text and "clean=false" in text


def test_report_flags_an_active_person_in_no_space(session):
    world = seed_world(session)
    outsider = User(email="solo@example.test")
    session.add(outsider)
    session.flush()
    session.add(Membership(organization_id=world.organization_id, user_id=outsider.id, role=MembershipRole.MEMBER,
                           is_active=True))
    session.commit()
    code, text = _cli(session, "report")
    assert code == 2 and "people_without_space=1" in text
    session.execute(delete(SpaceMember))
    session.commit()
    assert "people_without_space=6" in _cli(session, "report")[1]


def test_removed_commands_and_unknown_organization_are_usage_errors(session):
    seed_world(session)
    session.commit()
    for argv in (("shadow",), ("enforce", "--all-clean"), ("status",)):
        assert _cli(session, *argv)[0] == 1
    from uuid import uuid4
    assert _cli(session, "report", "--organization", str(uuid4()))[0] == 1
