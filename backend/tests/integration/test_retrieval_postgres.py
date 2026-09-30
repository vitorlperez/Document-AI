"""Exercise the real generated tsvector column, OR ranking and tenant boundaries."""
import pytest
from sqlalchemy.orm import sessionmaker

from app.access.models import ALL_SCOPES
from app.access.principal import Principal
from app.access.scope import ScopedAccess
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL
from app.knowledge.retrieval import RetrievalService
from tests.access_helpers import seed_tenant
from tests.integration.test_pgvector_search import engine  # noqa: F401

pytestmark = pytest.mark.postgres


def test_fts_search_ranks_and_confines_real_postgres(engine):  # noqa: F811
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    a = seed_tenant(factory, "A", "Aurora setembro setembro setembro")
    b = seed_tenant(factory, "B", "Aurora segredo")
    with factory.begin() as session:
        other = Document(organization_id=a.organization_id, workspace_folder_id=a.folder_id,
                         external_file_id="weaker", name="A0 lexical.pdf", mime_type="application/pdf",
                         source_url="https://drive.example.test/weaker", content_hash="b" * 64,
                         processing_version="v1", index_status="indexed")
        session.add(other)
        session.flush()
        session.add(DocumentChunk(organization_id=a.organization_id, workspace_folder_id=a.folder_id,
                                  document_id=other.id, position=0, text="Aurora", search_text="aurora",
                                  embedding=[1.0, 0.0], embedding_model=EMBEDDING_MODEL))
        weaker_id = other.id
    with factory() as session:
        principal = Principal(a.organization_id, a.user_id, "api_key", ALL_SCOPES)
        selection = ScopedAccess(session, principal).selection(None)
        service = RetrievalService(session)
        hits = service.search(scope=principal.scope, user_id=a.user_id,
                              query="Aurora setembro", selection=selection)
        assert [hit.document_id for hit in hits] == [a.document_id, weaker_id]
        assert hits[0].score > hits[1].score > 0 and b.document_id not in {hit.document_id for hit in hits}
        assert service.search(scope=principal.scope, user_id=a.user_id,
                              query="'; drop table x; -- & | :*", selection=selection) == []
