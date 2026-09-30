import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.access.principal import Principal
from app.access.scope import ScopedAccess
from app.core.models import Base
from app.ingestion.service import SyncAccessDenied
from app.library.models import LibraryNode
from tests.access_helpers import seed_tenant


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _principal(tenant, node_ids=None):
    return Principal(tenant.organization_id, tenant.user_id, "api_key", frozenset({"search:read"}),
                     tuple(node_ids) if node_ids else None)


def _file_node(factory, tenant):
    with factory() as session:
        return session.query(LibraryNode).filter_by(organization_id=tenant.organization_id, kind="file").one().id


def test_unrestricted_credential_selects_the_whole_organization(factory):
    tenant = seed_tenant(factory, "A", "texto")
    with factory() as session:
        selection = ScopedAccess(session, _principal(tenant)).selection(None)
    assert selection.folder_ids == [tenant.folder_id] and selection.document_ids is None


def test_restricted_credential_is_confined_to_its_nodes(factory):
    tenant = seed_tenant(factory, "A", "texto")
    node = _file_node(factory, tenant)
    with factory() as session:
        selection = ScopedAccess(session, _principal(tenant, [node])).selection(None)
    assert selection.document_ids == {tenant.document_id}


def test_a_node_of_another_organization_is_denied_not_ignored(factory):
    a, b = seed_tenant(factory, "A", "a"), seed_tenant(factory, "B", "b")
    foreign = _file_node(factory, b)
    with factory() as session, pytest.raises(SyncAccessDenied):
        ScopedAccess(session, _principal(a)).selection([foreign])


def test_restricted_credential_cannot_widen_beyond_its_roots(factory):
    a = seed_tenant(factory, "A", "a")
    with factory() as session:
        source_root = session.query(LibraryNode).filter_by(organization_id=a.organization_id, kind="source").one().id
    node = _file_node(factory, a)
    with factory() as session, pytest.raises(SyncAccessDenied):
        ScopedAccess(session, _principal(a, [node])).selection([source_root])
