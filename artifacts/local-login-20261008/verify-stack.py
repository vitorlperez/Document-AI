import json,subprocess,pathlib,datetime
base=pathlib.Path('artifacts/local-login-20261008')
before=json.loads((base/'before.json').read_text())
services={}
for svc in before['services']:
    cid=subprocess.check_output(['docker','compose','ps','-q',svc],text=True).strip()
    obj=json.loads(subprocess.check_output(['docker','inspect',cid]))[0]
    services[svc]={'id':obj['Id'],'image':obj['Image'],'startedAt':obj['State']['StartedAt'],'status':obj['State']['Status'],'health':obj['State'].get('Health',{}).get('Status'),'mounts':[{'type':m['Type'],'name':m.get('Name'),'destination':m['Destination']} for m in obj['Mounts']]}
unchanged={s:services[s]['id']==before['services'][s]['id'] for s in ['postgres','redis','worker','beat']}
assert all(unchanged.values()),unchanged
assert all(services[s]['startedAt']==before['services'][s]['startedAt'] for s in ['postgres','redis','worker','beat'])
assert all(services[s]['mounts']==before['services'][s]['mounts'] for s in ['postgres','redis'])
assert all(services[s]['id']!=before['services'][s]['id'] for s in ['api','frontend'])
cfg=json.loads(subprocess.check_output(['docker','compose','config','--format','json']))
raw=json.loads(subprocess.check_output(['docker','inspect',services['api']['id']]))[0]
env=dict(x.split('=',1) for x in raw['Config']['Env'])
desired=cfg['services']['api']['environment']
assert all(env.get(k)==str(v or '') for k,v in desired.items())
checks={'untouchedServiceContainerIDsAndStartTimes':unchanged,'postgresVolumeUnchanged':True,'redisVolumeUnchanged':True,'apiAndFrontendRecreated':True,'apiEnvMatchesCompose':True,'workosAPIKeyPresent':bool(env.get('WORKOS_API_KEY')),'workosClientIDPresent':bool(env.get('WORKOS_CLIENT_ID')),'workosEnvironment':'Staging' if env.get('WORKOS_API_KEY','').startswith('sk_test_') else 'unidentified'}
revision=subprocess.check_output(['docker','compose','exec','-T','postgres','psql','-U','document_intelligence','-d','document_intelligence','-Atc','SELECT version_num FROM alembic_version;'],text=True).strip()
counts=subprocess.check_output(['docker','compose','exec','-T','postgres','psql','-U','document_intelligence','-d','document_intelligence','-Atc',"SELECT 'users=' || count(*) FROM users UNION ALL SELECT 'documents=' || count(*) FROM documents UNION ALL SELECT 'organizations=' || count(*) FROM organizations;"],text=True).strip().splitlines()
assert revision==before['databaseRevision']
assert counts==before['databaseCounts']
checks['databaseRevisionAndCountsUnchanged']=True
evidence={'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'services':services,'databaseRevision':revision,'databaseCounts':counts,'checks':checks,'safeLocalConfig':{k:env.get(k) for k in ['ENVIRONMENT','PUBLIC_APP_URL','WORKOS_REDIRECT_URI']}}
(base/'after.json').write_text(json.dumps(evidence,indent=2)+'\n')
print(json.dumps({'checks':checks,'revision':revision,'counts':counts},indent=2))
