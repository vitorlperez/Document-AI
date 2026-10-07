from uuid import uuid4

from app.knowledge.models import ConversationMessage
from tests.api.test_multiscope_questions_api import ask, corpus  # noqa: F401
from tests.api.test_text_search_api import login, search_api  # noqa: F401


def transcript(client, organization_id, conversation_id):
    return client.get(f'/organizations/{organization_id}/conversations/{conversation_id}').json()['messages']


def test_feedback_replaces_vote_preserves_response_and_exports_calibration(corpus):  # noqa: F811 - imported pytest fixture
    from app.core.scoping import OrganizationScope
    from app.identity.models import User
    from app.knowledge.agent_eval import feedback_calibration

    client, factory, _, org, _, _ = corpus
    response = ask(client, org, scope='organization').json()
    conv = response['conversation_id']
    msg = transcript(client, org, conv)[-1]
    url = f'/organizations/{org}/conversations/{conv}/messages/{msg["id"]}/feedback'
    assert client.put(url, json={'vote': 'up'}).status_code == 200
    assert client.put(url, json={'vote': 'down'}).status_code == 200
    updated = transcript(client, org, conv)[-1]
    assert updated['response'] == msg['response']
    assert updated['context']['feedback']['vote'] == 'down'
    with factory() as session:
        user = session.query(User).one()
        export = feedback_calibration(session, scope=OrganizationScope(org), user_id=user.id)
        assert export[0]['feedback']['vote'] == 'down'
        assert set(export[0]) == {'message_id', 'feedback', 'assessment'}


def test_feedback_rejects_invalid_vote_user_message_foreign_tenant_and_missing_id(corpus):  # noqa: F811 - imported pytest fixture
    client, _, _, org, _, _ = corpus
    conv = ask(client, org, scope='organization').json()['conversation_id']
    messages = transcript(client, org, conv)
    def url(org_id=org, msg=messages[-1]['id']):
        return f'/organizations/{org_id}/conversations/{conv}/messages/{msg}/feedback'
    assert client.put(url(), json={'vote': 'maybe'}).status_code == 422
    assert client.put(url(msg=messages[0]['id']), json={'vote': 'up'}).status_code == 404
    assert client.put(url(msg=uuid4()), json={'vote': 'up'}).status_code == 404
    assert client.put(url(org_id=uuid4()), json={'vote': 'up'}).status_code == 404


def test_feedback_denies_other_user_even_when_member(corpus):  # noqa: F811 - imported pytest fixture
    from app.identity.models import User
    from app.organizations.models import Membership, MembershipRole

    client, factory, gateway, org, _, _ = corpus
    conv = ask(client, org, scope='organization').json()['conversation_id']
    msg = transcript(client, org, conv)[-1]['id']
    login(client, gateway, code='other', email='other@example.test', subject='other')
    with factory.begin() as session:
        other = session.query(User).filter_by(email='other@example.test').one()
        session.add(Membership(organization_id=org, user_id=other.id, role=MembershipRole.MEMBER))
    assert client.put(f'/organizations/{org}/conversations/{conv}/messages/{msg}/feedback',
                      json={'vote': 'up'}).status_code == 404
    with factory() as session:
        assert all(not (item.context or {}).get('feedback') for item in session.query(ConversationMessage))
