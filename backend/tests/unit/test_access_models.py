import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.access.models import ALL_SCOPES, ApiKey, OrganizationAccessSettings
from app.core.models import Base
from app.identity.models import User
from app.organizations.models import Organization


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_prefix_is_unique_and_scopes_round_trip():
    with _session() as session:
        org, user = Organization(name="A"), User(email="a@example.test")
        session.add_all([org, user])
        session.flush()
        common = dict(organization_id=org.id, created_by_user_id=user.id, secret_hash="0" * 64,
                      scopes=["search:read"], name="k")
        session.add(ApiKey(prefix="arq_deadbeef", **common))
        session.flush()
        assert session.query(ApiKey).one().scopes == ["search:read"]
        session.add(ApiKey(prefix="arq_deadbeef", **common))
        with pytest.raises(IntegrityError):
            session.flush()


def test_access_is_disabled_by_default():
    with _session() as session:
        org = Organization(name="A")
        session.add(org)
        session.flush()
        session.add(OrganizationAccessSettings(organization_id=org.id))
        session.flush()
        row = session.get(OrganizationAccessSettings, org.id)
        assert row.public_api_enabled is False and row.mcp_enabled is False


def test_scope_catalogue_is_closed():
    assert ALL_SCOPES == {"search:read", "documents:read", "ask:run"}
