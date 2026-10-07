"""Prova pontual descartável do rollout fc0b64b; não é ferramenta reutilizável."""
import json,secrets,os
from datetime import UTC,datetime,timedelta
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.main import app
from app.identity.models import User,UserSession
from app.identity.auth import hash_secret
from app.organizations.models import Organization,Membership,MembershipRole
from app.knowledge.answer_assessment import JevAnswerAssessor
from app.knowledge.models import ConversationMessage

assert os.environ['AGENT_ASSESSMENT_MODE']=='off'
assert os.environ['AGENT_ASSESSMENT_EXTERNAL_ENABLED']=='false'
assert os.environ['RAILWAY_GIT_COMMIT_SHA'].startswith('fc0b64b')
conn=app.state.engine.connect()
outer=conn.begin()
def session_factory():
    return Session(bind=conn,join_transaction_mode='create_savepoint',expire_on_commit=False)
app.state.session_factory=session_factory
calls=[]
def forbidden(*args,**kwargs):
    calls.append(True)
    raise AssertionError('assessment external call forbidden')
JevAnswerAssessor._post=forbidden
secret=secrets.token_urlsafe(32)
try:
    with session_factory() as s:
        u=User(email='assessment-smoke-'+secrets.token_hex(6)+'@example.test')
        o=Organization(name='Synthetic assessment rollout smoke')
        s.add_all([u,o]);s.flush()
        s.add_all([Membership(organization_id=o.id,user_id=u.id,role=MembershipRole.OWNER),UserSession(user_id=u.id,secret_hash=hash_secret(secret),expires_at=datetime.now(UTC)+timedelta(minutes=5))]);s.commit()
        oid=str(o.id)
    client=TestClient(app)
    client.cookies.set(app.state.settings.auth_session_cookie_name,secret)
    client.headers['Origin']=app.state.settings.public_app_url
    response=client.post(f'/organizations/{oid}/questions',json={'question':'Olá!','scope':'selection','mentions':[],'providers':['google_drive']})
    assert response.status_code==200, 'question HTTP '+str(response.status_code)
    result=response.json(); assessment=result['resolved_context']['assessment']
    assert assessment['reason']=='disabled' and assessment['external_enabled'] is False
    cid=result['conversation_id']
    transcript=client.get(f'/organizations/{oid}/conversations/{cid}').json()
    msg=transcript['messages'][-1]
    url=f'/organizations/{oid}/conversations/{cid}/messages/{msg["id"]}/feedback'
    codes=[]
    for vote in ['up','down']:
        r=client.put(url,json={'vote':vote});codes.append(r.status_code)
        assert r.status_code==200
        with session_factory() as s:
            saved=s.get(ConversationMessage,msg['id'])
            assert saved.context['feedback']['vote']==vote
            assert saved.response==msg['response']
        updated=client.get(f'/organizations/{oid}/conversations/{cid}').json()['messages'][-1]
        assert updated['context']['feedback']['vote']==vote
        assert updated['response']==msg['response']
        assert updated['context']['resolved_context']['assessment']['reason']=='disabled'
        assert updated['context']['resolved_context']['assessment']['external_enabled'] is False
    assert not calls
    print('SMOKE_RESULT '+json.dumps({'question_http':200,'reason':assessment['reason'],'external_enabled':assessment['external_enabled'],'assessment_http_calls':len(calls),'feedback_http':codes,'votes_reread_postgresql':['up','down'],'response_preserved':True,'auth':'real session cookie, synthetic tenant','transport':'deployed ASGI in API container','cleanup':'outer PostgreSQL transaction rollback'}))
finally:
    outer.rollback();conn.close()
with app.state.engine.connect() as check_conn:
    check_session=Session(bind=check_conn)
    assert check_session.get(Organization,o.id) is None
    assert check_session.get(User,u.id) is None
    check_session.close()
print('SMOKE_CLEANUP rollback verified: synthetic user and tenant absent')
