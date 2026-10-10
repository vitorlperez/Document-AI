from uuid import uuid4

from app.knowledge.models import Conversation
from tests.api.test_multiscope_questions_api import ask, corpus  # noqa: F401
from tests.api.test_text_search_api import login, search_api  # noqa: F401


def test_list_rename_delete_own_conversations(corpus):  # noqa: F811 - imported pytest fixture
    client, _, _, org, _, _ = corpus
    first = ask(client, org, scope='organization').json()['conversation_id']
    second = ask(client, org, scope='organization').json()['conversation_id']
    listing = client.get(f'/organizations/{org}/conversations').json()
    assert listing['total'] == 2
    assert [item['id'] for item in listing['items']] == [second, first]
    assert listing['items'][0]['title'] == 'When does the campaign launch?'
    page = client.get(f'/organizations/{org}/conversations', params={'page': 2, 'page_size': 1}).json()
    assert [item['id'] for item in page['items']] == [first]
    renamed = client.patch(f'/organizations/{org}/conversations/{first}', json={'title': '  Lançamento   Q3 '})
    assert renamed.status_code == 200 and renamed.json()['title'] == 'Lançamento Q3'
    assert client.patch(f'/organizations/{org}/conversations/{first}', json={'title': '   '}).status_code == 422
    assert client.delete(f'/organizations/{org}/conversations/{first}').status_code == 204
    assert client.get(f'/organizations/{org}/conversations/{first}').status_code == 404
    assert client.delete(f'/organizations/{org}/conversations/{first}').status_code == 404
    assert client.get(f'/organizations/{org}/conversations').json()['total'] == 1


def test_other_member_cannot_see_rename_or_delete(corpus):  # noqa: F811 - imported pytest fixture
    from app.identity.models import User
    from app.organizations.models import Membership, MembershipRole

    client, factory, gateway, org, _, _ = corpus
    conv = ask(client, org, scope='organization').json()['conversation_id']
    login(client, gateway, code='other', email='other@example.test', subject='other')
    with factory.begin() as session:
        other = session.query(User).filter_by(email='other@example.test').one()
        session.add(Membership(organization_id=org, user_id=other.id, role=MembershipRole.MEMBER))
    assert client.get(f'/organizations/{org}/conversations').json()['total'] == 0
    assert client.patch(f'/organizations/{org}/conversations/{conv}', json={'title': 'x'}).status_code == 404
    assert client.delete(f'/organizations/{org}/conversations/{conv}').status_code == 404
    with factory() as session:
        assert session.query(Conversation).count() == 1


def test_foreign_organization_is_not_found(corpus):  # noqa: F811 - imported pytest fixture
    client = corpus[0]
    assert client.get(f'/organizations/{uuid4()}/conversations').status_code == 404


def test_library_overview_scoped_by_provider_and_member_only(corpus):  # noqa: F811 - imported pytest fixture
    client, _, _, org, _, _ = corpus
    both = client.get(f'/organizations/{org}/library/overview').json()
    assert both['document_count'] == 2
    assert 'campaign' in both['themes']
    assert 1 <= len(both['suggested_questions']) <= 5
    notion = client.get(f'/organizations/{org}/library/overview', params={'providers': ['notion']}).json()
    assert notion['document_count'] == 1
    assert client.get(f'/organizations/{org}/library/overview', params={'providers': ['clickup']}).json()[
        'suggested_questions'] == []
    assert client.get(f'/organizations/{uuid4()}/library/overview').status_code in {403, 404}
