"""Exercise the real generated tsvector column, OR ranking and tenant boundaries."""
import pytest
from sqlalchemy.orm import sessionmaker

from app.access.principal import Principal
from app.access.models import ALL_SCOPES
from app.access.scope import ScopedAccess
from app.knowledge.retrieval import RetrievalService
from tests.access_helpers import seed_tenant
from tests.integration.test_pgvector_search import engine  # noqa: F401

pytestmark = pytest.mark.postgres


def test_fts_search_ranks_and_confines_real_postgres(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    a = seed_tenant(factory, "A", "Aurora setembro setembro setembro")
    b = seed_tenant(factory, "B", "Aurora segredo")
    with factory() as session:
        principal = Principal(a.organization_id, a.user_id, "api_key", ALL_SCOPES)
        selection = ScopedAccess(session, principal).selection(None)
        service = RetrievalService(session)
        hits = service.search(scope=principal.scope, user_id=a.user_id,
                              query="Aurora setembro", selection=selection)
        assert [hit.document_id for hit in hits] == [a.document_id]
        assert hits[0].score > 0 and b.document_id not in {hit.document_id for hit in hits}
        assert service.search(scope=principal.scope, user_id=a.user_id,
                              query="'; drop table x; -- & | :*", selection=selection) == []
