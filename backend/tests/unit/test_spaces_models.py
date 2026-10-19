import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.identity.models import User
from app.organizations.models import Organization
from app.spaces.models import Space, SpaceFolderGrant, SpaceMember  # noqa: F401


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def _org(session):
    org, user = Organization(name="Acme"), User(email="a@example.test")
    session.add_all([org, user])
    session.flush()
    return org, user


def test_active_space_names_are_unique_case_insensitively(session):
    org, _ = _org(session)
    session.add(Space(organization_id=org.id, name="RH", name_key="rh"))
    session.flush()
    session.add(Space(organization_id=org.id, name="rh", name_key="rh"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_only_one_active_default_space_per_organization(session):
    org, _ = _org(session)
    session.add(Space(organization_id=org.id, name="Geral", name_key="geral", is_default=True))
    session.flush()
    session.add(Space(organization_id=org.id, name="Outro", name_key="outro", is_default=True))
    with pytest.raises(IntegrityError):
        session.flush()


def test_member_is_unique_while_active_and_role_is_checked(session):
    org, user = _org(session)
    space = Space(organization_id=org.id, name="RH", name_key="rh")
    session.add(space)
    session.flush()
    session.add(SpaceMember(organization_id=org.id, space_id=space.id, user_id=user.id, role="member"))
    session.flush()
    session.add(SpaceMember(organization_id=org.id, space_id=space.id, user_id=user.id, role="member"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    session.add(SpaceMember(organization_id=org.id, space_id=space.id, user_id=user.id, role="owner"))
    with pytest.raises(IntegrityError):
        session.flush()
