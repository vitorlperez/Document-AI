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
