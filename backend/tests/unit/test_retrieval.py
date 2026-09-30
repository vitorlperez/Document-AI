import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.access.principal import Principal
from app.access.scope import ScopedAccess
from app.core.models import Base
from app.knowledge.retrieval import MAX_FETCH_CHARS, RetrievalService
from tests.access_helpers import seed_tenant


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _ctx(session, tenant):
    principal = Principal(tenant.organization_id, tenant.user_id, "api_key", frozenset())
    return principal, ScopedAccess(session, principal).selection(None)


def test_search_returns_only_the_callers_organization(factory):
    a, b = seed_tenant(factory, "A", "Projeto Aurora entrega em setembro"), seed_tenant(factory, "B", "Projeto Zenite sigiloso")
    with factory() as session:
        principal, selection = _ctx(session, a)
        service = RetrievalService(session)
        hits = service.search(scope=principal.scope, user_id=a.user_id, query="Aurora setembro", selection=selection)
        assert [h.document_id for h in hits] == [a.document_id] and hits[0].url.endswith("/A")
        assert service.search(scope=principal.scope, user_id=a.user_id, query="Zenite", selection=selection) == []


def test_fetch_of_a_foreign_document_is_indistinguishable_from_missing(factory):
    a, b = seed_tenant(factory, "A", "a"), seed_tenant(factory, "B", "b")
    with factory() as session:
        principal, selection = _ctx(session, a)
        service = RetrievalService(session)
        assert service.fetch(scope=principal.scope, user_id=a.user_id, document_id=b.document_id, selection=selection) is None


def test_fetch_joins_chunks_and_flags_truncation(factory):
    a = seed_tenant(factory, "A", "x" * (MAX_FETCH_CHARS + 50))
    with factory() as session:
        principal, selection = _ctx(session, a)
        doc = RetrievalService(session).fetch(scope=principal.scope, user_id=a.user_id, document_id=a.document_id, selection=selection)
    assert doc.truncated and len(doc.text) == MAX_FETCH_CHARS and doc.title == "A plano.pdf"


def test_query_without_meaningful_terms_returns_nothing(factory):
    a = seed_tenant(factory, "A", "texto")
    with factory() as session:
        principal, selection = _ctx(session, a)
        assert RetrievalService(session).search(scope=principal.scope, user_id=a.user_id, query="de a o", selection=selection) == []
