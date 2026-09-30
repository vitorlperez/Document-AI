from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.access.models import SCOPE_SEARCH
from app.access.principal import ApiKeyAuthenticator, InsufficientScope, InvalidCredential
from app.core.models import Base
from app.organizations.models import Membership
from tests.access_helpers import mint_key, seed_tenant


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def _auth(factory, raw):
    with factory() as session:
        return ApiKeyAuthenticator(session).authenticate(raw)


def test_valid_key_yields_a_scoped_principal(factory):
    tenant = seed_tenant(factory, "A", "texto")
    principal = _auth(factory, mint_key(factory, tenant, scopes={SCOPE_SEARCH}))
    assert principal.organization_id == tenant.organization_id and principal.user_id == tenant.user_id
    assert principal.channel == "api_key" and principal.scopes == {SCOPE_SEARCH}
    with pytest.raises(InsufficientScope):
        principal.require("ask:run")


@pytest.mark.parametrize("case", ["unknown", "wrong_secret", "revoked", "expired", "api_disabled", "member_deactivated"])
def test_every_failure_is_the_same_invalid_credential(factory, case):
    tenant = seed_tenant(factory, "A", "texto", api_enabled=case != "api_disabled")
    raw = mint_key(factory, tenant, revoked=case == "revoked",
                   expires_in=timedelta(seconds=-1) if case == "expired" else None)
    if case == "unknown":
        raw = "arq_deadbeef_" + "a" * 43
    if case == "wrong_secret":
        raw = raw[:-3] + "xyz"
    if case == "member_deactivated":
        with factory.begin() as session:
            session.query(Membership).filter_by(user_id=tenant.user_id).update({"is_active": False})
    with pytest.raises(InvalidCredential):
        _auth(factory, raw)


def test_review_6_demoted_creator_invalidates_existing_keys(factory):
    from app.organizations.models import MembershipRole
    tenant = seed_tenant(factory, 'A', 'texto')
    raw = mint_key(factory, tenant)
    with factory.begin() as session:
        session.query(Membership).filter_by(user_id=tenant.user_id).update({'role': MembershipRole.MEMBER})
    with pytest.raises(InvalidCredential):
        _auth(factory, raw)
