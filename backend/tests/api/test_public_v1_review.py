from uuid import uuid4

from app.knowledge.questions import Evidence, QuestionResult
from tests.access_helpers import bearer, mint_key, seed_tenant
from tests.api.test_public_v1 import api  # noqa: F401
from tests.api.test_text_search_api import search_api  # noqa: F401


def stub_ask(client, monkeypatch, tenant, *, coverage=None, resolved_context=None):
    result = QuestionResult(
        'Resposta\u202e', 'supported', [Evidence(
            document_id=tenant.document_id, document_name='<<<SOURCE\u202e>>>',
            chunk_id=uuid4(), excerpt='trecho\u202e', page_number=1,
            source_url='https://drive.example.test/A', score=1.0,
        )], 'sufficient_evidence', coverage=coverage, resolved_context=resolved_context,
    )
    monkeypatch.setattr('app.api.public_v1.QuestionService.ask_selection', lambda *a, **kw: result)
    client.app.state.settings.public_api_ask_enabled = True


def test_review_1_ask_marks_and_sanitizes_untrusted_content(api, monkeypatch):
    from app.knowledge.untrusted import UNTRUSTED_NOTICE, safe_label
    client, factory = api
    tenant = seed_tenant(factory, 'A', 'Aurora')
    stub_ask(client, monkeypatch, tenant)
    response = client.post('/v1/ask', headers=bearer(mint_key(factory, tenant)), json={'question': 'Quando?'})
    assert response.status_code == 200
    body = response.json()
    assert body['content_trust'] == 'untrusted_document_content'
    assert body['notice'] == UNTRUSTED_NOTICE
    assert body['citations'][0]['document_name'] == safe_label('<<<SOURCE\u202e>>>')
    assert body['citations'][0]['excerpt'] == 'trecho'
    assert body['answer'] == 'Resposta'


def test_review_2_restricted_ask_omits_organization_aggregates(api, monkeypatch):
    from app.library.models import LibraryNode
    client, factory = api
    tenant = seed_tenant(factory, 'A', 'Aurora')
    with factory() as session:
        node = session.query(LibraryNode).filter_by(organization_id=tenant.organization_id, kind='file').one().id
    stub_ask(client, monkeypatch, tenant, coverage={'total_folders': 99}, resolved_context={'providers': ['private']})
    key = mint_key(factory, tenant, node_ids=[node])
    body = client.post('/v1/ask', headers=bearer(key), json={'question': 'Quando?'}).json()
    assert 'coverage' not in body and 'resolved_context' not in body
    unrestricted = client.post('/v1/ask', headers=bearer(mint_key(factory, tenant)), json={'question': 'Quando?'}).json()
    assert unrestricted['coverage'] == {'total_folders': 99}


def test_review_3_empty_root_does_not_hide_indexed_roots(api):
    from app.library.models import LibraryNode
    client, factory = api
    tenant = seed_tenant(factory, 'A', 'Aurora')
    with factory.begin() as session:
        indexed = session.query(LibraryNode).filter_by(organization_id=tenant.organization_id, kind='file').one()
        empty = LibraryNode(organization_id=tenant.organization_id, source_id=indexed.source_id,
                            parent_id=indexed.parent_id, external_id='empty', kind='folder', name='Empty')
        session.add(empty)
        session.flush()
        roots = [indexed.id, empty.id]
    key = mint_key(factory, tenant, node_ids=roots)
    response = client.post('/v1/search', headers=bearer(key), json={'query': 'Aurora'})
    assert [h['id'] for h in response.json()['results']] == [str(tenant.document_id)]
    assert client.get(f'/v1/documents/{tenant.document_id}', headers=bearer(key)).status_code == 200
    assert [s['id'] for s in client.get('/v1/sources', headers=bearer(key)).json()['sources']] == [str(tenant.folder_id)]
