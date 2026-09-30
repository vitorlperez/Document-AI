from uuid import uuid4

import pytest

from app.access.ratelimit import InMemoryRateLimiter
from app.knowledge.questions import Evidence, QuestionResult
from tests.access_helpers import bearer, mint_key, seed_tenant
from tests.api.test_text_search_api import search_api  # noqa: F401


@pytest.fixture()
def api(search_api):  # noqa: F811 -- imported fixture dependency
    client, factory, _gateway = search_api
    client.app.state.rate_limiter = InMemoryRateLimiter(clock=lambda: 120.0)
    return client, factory


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


def test_review_5_invalid_credentials_are_limited_before_authentication(api, monkeypatch):
    from app.access.principal import InvalidCredential
    client, _factory = api
    monkeypatch.setattr('app.api.public_v1.IP_RATE_LIMIT', 2, raising=False)
    calls = []
    def reject(*args):
        calls.append(1)
        raise InvalidCredential
    monkeypatch.setattr('app.api.public_v1.ApiKeyAuthenticator.authenticate', reject)
    replies = [client.get('/v1/whoami', headers=bearer('bad')) for _ in range(4)]
    assert [r.status_code for r in replies] == [401, 401, 429, 429]
    assert len(calls) == 2
    assert replies[-1].headers['Retry-After']


def test_review_5_denial_audit_is_bounded_per_credential_and_minute(api):
    from app.access.models import SCOPE_SEARCH, ApiAuditEvent
    client, factory = api
    tenant = seed_tenant(factory, 'A', 'Aurora')
    key = mint_key(factory, tenant, scopes={SCOPE_SEARCH}, rate=1)
    for _ in range(4):
        assert client.get(f'/v1/documents/{tenant.document_id}', headers=bearer(key)).status_code == 403
    assert client.post('/v1/search', headers=bearer(key), json={'query': 'Aurora'}).status_code == 200
    for _ in range(4):
        assert client.post('/v1/search', headers=bearer(key), json={'query': 'Aurora'}).status_code == 429
    with factory() as session:
        statuses = [row.http_status for row in session.query(ApiAuditEvent)]
    assert sorted(statuses) == [200, 403, 429]


def test_review_7_invalid_document_id_uses_a_bounded_route_action(api):
    from app.access.models import ApiAuditEvent
    client, factory = api
    tenant = seed_tenant(factory, 'A', 'Aurora')
    response = client.get('/v1/documents/' + 'attacker' * 30, headers=bearer(mint_key(factory, tenant)))
    assert response.status_code == 422
    with factory() as session:
        row = session.query(ApiAuditEvent).one()
        assert row.action == 'document' and len(row.action) <= 40


def test_review_8_audit_action_is_consistent_on_denied_sources_and_fetch(api):
    from app.access.models import SCOPE_ASK, SCOPE_SEARCH, ApiAuditEvent
    client, factory = api
    tenant = seed_tenant(factory, 'A', 'Aurora')
    assert client.get('/v1/sources', headers=bearer(mint_key(factory, tenant, scopes={SCOPE_ASK}))).status_code == 403
    assert client.get(f'/v1/documents/{tenant.document_id}', headers=bearer(mint_key(factory, tenant, scopes={SCOPE_SEARCH}))).status_code == 403
    with factory() as session:
        assert {r.action for r in session.query(ApiAuditEvent)} == {'list_sources', 'fetch'}


def test_review_11_whoami_accepts_every_valid_scope(api):
    from app.access.models import ALL_SCOPES
    client, factory = api
    tenant = seed_tenant(factory, 'A', 'Aurora')
    for scope in ALL_SCOPES:
        response = client.get('/v1/whoami', headers=bearer(mint_key(factory, tenant, scopes={scope})))
        assert response.status_code == 200
        assert response.json()['scopes'] == [scope]


def test_review_12_search_does_not_consume_ask_bucket_and_ask_cap_is_org_wide(api, monkeypatch):
    client, factory = api
    tenant = seed_tenant(factory, 'A', 'Aurora')
    stub_ask(client, monkeypatch, tenant)
    client.app.state.settings.api_ask_rate_limit_per_minute = 1
    key = mint_key(factory, tenant)
    assert client.post('/v1/search', headers=bearer(key), json={'query': 'Aurora'}).status_code == 200
    assert client.post('/v1/ask', headers=bearer(key), json={'question': 'Quando?'}).status_code == 200
    assert client.post('/v1/ask', headers=bearer(mint_key(factory, tenant)), json={'question': 'Quando?'}).status_code == 429


def test_review_16_ask_does_not_expose_internal_validation_text(api, monkeypatch):
    client, factory = api
    tenant = seed_tenant(factory, 'A', 'Aurora')
    client.app.state.settings.public_api_ask_enabled = True
    def fail(*args, **kwargs):
        raise ValueError('private internal diagnostic')
    monkeypatch.setattr('app.api.public_v1.QuestionService.ask_selection', fail)
    response = client.post('/v1/ask', headers=bearer(mint_key(factory, tenant)), json={'question': 'Quando?'})
    assert response.status_code == 422
    assert response.json()['detail'] == 'question selection unavailable'
