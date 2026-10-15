"""Synthetic HTTP parity only. Reuses the reviewed fixtures and client checks."""
import pathlib,os,json,time,urllib.request,urllib.error,subprocess
from http.cookiejar import CookieJar
ROOT=pathlib.Path(__file__).resolve().parent
runtime=pathlib.Path(os.environ['NINE_CI_RUNTIME']);BASE='http://127.0.0.1:20129'
mock=json.loads(subprocess.check_output(['docker','inspect','9router-parity-mock']))[0]
network=json.loads(subprocess.check_output(['docker','network','inspect','9router-parity-net']))[0]
router=json.loads(subprocess.check_output(['docker','inspect','9router-parity-router']))[0]
assert network['Internal'] and list(router['NetworkSettings']['Networks'])==['9router-parity-net']
assert list(mock['NetworkSettings']['Networks'])==['9router-parity-net']
assert router['HostConfig']['PortBindings']=={'20128/tcp':[{'HostIp':'127.0.0.1','HostPort':'20129'}]}
assert all(c['Config']['User']=='1000:1000' and c['HostConfig']['ReadonlyRootfs'] and not c['HostConfig']['Privileged'] and c['HostConfig']['CapDrop']==['ALL'] and 'no-new-privileges:true' in c['HostConfig']['SecurityOpt'] for c in [router,mock])
assert router['HostConfig']['Memory']==768*1048576 and router['HostConfig']['MemorySwap']==768*1048576
assert mock['HostConfig']['Memory']==96*1048576 and mock['HostConfig']['MemorySwap']==96*1048576
MOCK='http://'+mock['NetworkSettings']['Networks']['9router-parity-net']['IPAddress']+':18080'
password=(runtime/'dashboard-password').read_text().strip();key=None;keyid=None
observations=[];rows=[];requests=0;upstream=0;start=time.monotonic();stage='startup'
result={'tests':{},'isolationPass':True,'keyRevoked':False,'sourceCommit':'a99cf57239ff778b61e434c2786009d5ed1c412c'}
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):return None
def http(origin,path,body=None,headers=None,method=None,admin=False):
 global requests
 assert origin in [BASE,MOCK] and path.startswith('/') and time.monotonic()-start<180
 if origin==BASE:requests+=1;assert requests<=32
 req=urllib.request.Request(origin+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json',**(headers or {})},method=method)
 try:
  response=(client if admin else plain).open(req,timeout=15)
 except urllib.error.HTTPError as error:
  body=error.read(4096);category='unexpected-http-status'
  for marker,label in [(b'Missing API key','missing-api-key'),(b'Invalid API key','invalid-api-key'),(b'API key required','api-key-required'),(b'Operation not permitted','sandbox-permission'),(b'EPERM','sandbox-permission'),(b'unable to open database file','sqlite-open-failed'),(b'no such table','sqlite-missing-table'),(b'Unauthorized','unauthorized')]:
   if marker in body:category=label;break
  observations.append({'stage':stage,'method':req.get_method(),'route':path,'status':error.code,'contentType':error.headers.get('Content-Type','').split(';')[0],'errorCategory':category})
  raise
 observations.append({'stage':stage,'method':req.get_method(),'route':path,'status':response.status,'contentType':response.headers.get('Content-Type','').split(';')[0],'errorCategory':None})
 return response
def admin(path,body,method='POST'):
 with http(BASE,path,body,method=method,admin=True) as r:return json.load(r)
def negative(headers,path='/v1/chat/completions'):
 try:
  body={'model':'gb-a/ok',**({'messages':[{'role':'user','content':'synthetic'}]} if path=='/v1/chat/completions' else {'input':'synthetic'})}
  with http(BASE,path,body,headers):raise AssertionError('authentication-not-enforced')
 except urllib.error.HTTPError as e:assert e.code==401
def analyse_chat_sse(events,expected):
 parsed=[];parse_errors=0
 for event in events:
  if event==b'[DONE]':continue
  try:
   item=json.loads(event)
   if not isinstance(item,dict):raise ValueError()
   parsed.append(item)
  except (ValueError,TypeError):parse_errors+=1
 choices=[c for item in parsed for c in item.get('choices',[]) if isinstance(c,dict)]
 text=''.join(c.get('delta',{}).get('content') or '' for c in choices)
 finishes=[c['finish_reason'] for c in choices if c.get('finish_reason') is not None]
 known=['stop','tool_calls','length','content_filter','error']
 kinds=['chat.completion.chunk' if 'choices' in item else item.get('type') if item.get('type') in ['response.completed','response.failed','response.output_text.delta'] else 'error' if 'error' in item else 'unknown' for item in parsed]
 return {'dataEventCount':len(events),'jsonParseErrors':parse_errors,'eventKinds':list(dict.fromkeys(kinds)),
  'doneCount':events.count(b'[DONE]'),'finishReasons':[v if v in known else 'unknown' for v in finishes],
  'contentMatches':text==expected,'assembledContentLength':len(text),'expectedContentLength':len(expected),
  'errorEventCount':sum('error' in item for item in parsed)}

client=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPCookieProcessor(CookieJar()))
plain=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
try:
 with http(BASE,'/api/health') as response:assert response.status==200
 result['startupPass']=True
 # Dashboard login is used only for supported settings/fixture/key provisioning.
 admin('/api/auth/login',{'password':password})
 admin('/api/settings',{'requireApiKey':True,'requireLogin':True},'PATCH')
 with http(BASE,'/api/settings',admin=True) as r:effective=json.load(r)
 for name in ['requireApiKey','requireLogin']:assert effective.get(name) is True
 for name in ['rtkEnabled','cavemanEnabled','headroomEnabled','ponytailEnabled','pxpipeEnabled','pxpipeAutoInstall','enableObservability','cloudEnabled','tunnelEnabled','tailscaleEnabled']:assert effective.get(name) is False
 connections=[]
 for lane in ['a','b']:
  node=admin('/api/provider-nodes',{'name':'Local synthetic '+lane,'prefix':'gb-'+lane,'type':'openai-compatible','apiType':'chat','baseUrl':MOCK+'/'+lane+'/v1'})['node']
  assert node['baseUrl']==MOCK+'/'+lane+'/v1'
  connection=admin('/api/providers',{'provider':node['id'],'apiKey':'gate-b-fake-provider-key','name':'Local fake '+lane,'priority':1,'testStatus':'active'})['connection'];connections.append(connection['id'])
 combos={'GB-FALLBACK-429':['gb-a/rate-limit','gb-b/ok'],'GB-FALLBACK-503':['gb-a/unavailable','gb-b/ok']}
 for name,models in combos.items():admin('/api/combos',{'name':name,'models':models})
 admin('/api/settings',{'comboStrategy':'fallback','comboStrategies':{n:{'strategy':'fallback','autoSwitch':False} for n in combos}},'PATCH')
 created=admin('/api/keys',{'name':'ci-synthetic-only'});key=created['key'];keyid=created['id']
 spec=json.loads((ROOT/'fixtures.json').read_text());auth={'Authorization':'Bearer '+key}
 stage='authentication'
 for h in [{},{'Authorization':'Bearer invalid-synthetic-key'}]:negative(h)
 result['tests']['authentication']='PASS'
 stage='synthetic-key-positive'
 with http(BASE,'/v1/chat/completions',{'model':'gb-a/ok','stream':False,'messages':[{'role':'user','content':'synthetic'}]},auth) as r:assert r.status==200 and 'application/json' in r.headers.get('Content-Type','') and json.load(r)['choices'][0]['message']['content']=='MOCK_A_OK'
 result['tests']['json-probe']='PASS'
 schema={'type':'object','properties':{'nested':{'type':'object','properties':{'value':{'type':'integer'}},'required':['value']},'label':{'type':'string'}},'required':['nested','label'],'additionalProperties':False}
 for case in [c for c in spec['cases'] if c['id'] in ['chat-sse','chat-tools','fallback-429','fallback-503']]:
  stage=case['id']
  for cid in connections:admin('/api/providers/'+cid,{'testStatus':'active'},'PUT')
  with http(MOCK,'/__reset',{}, {'X-Gate-B-Control':'gate-b-fake-control-key'}) as r:r.read(1024)
  body={'model':case['model'],'stream':case.get('stream',False),'messages':[{'role':'user','content':'synthetic'}]}
  if case.get('tools'):body['tools']=[{'type':'function','function':{'name':'gate_b_echo','parameters':schema}}]
  with http(BASE,'/v1/chat/completions',body,auth) as r:
   assert r.status==200
   if case.get('stream'):
    assert 'text/event-stream' in r.headers.get('Content-Type','');events=[];size=0;t=time.monotonic()
    while True:
     line=r.readline(65537);size+=len(line);assert size<=2097152 and len(line)<=65536 and time.monotonic()-t<20
     if not line:break
     if line.startswith(b'data:'):events.append(line[5:].strip())
    diagnostic=analyse_chat_sse(events,case['expectedText']);diagnostic['receivedBytes']=size
    result['sseDiagnostic']=diagnostic
    with http(MOCK,'/__trace',headers={'X-Gate-B-Control':'gate-b-fake-control-key'}) as audit:mock_trace=json.load(audit)
    result['sseMockTrace']=mock_trace;upstream=mock_trace['total']
    assert diagnostic['doneCount']==1 and diagnostic['finishReasons']==['stop'] and diagnostic['contentMatches'] and diagnostic['jsonParseErrors']==0 and diagnostic['errorEventCount']==0
   else:
    data=json.load(r);message=data['choices'][0]['message']
    if case.get('tools'):
     calls=message['tool_calls'];result['toolDiagnostic']={'callCount':len(calls)};assert len(calls)==1;call=calls[0];result['toolDiagnostic'].update(idMatches=call['id']=='call_gate_b',nameMatches=call['function']['name']=='gate_b_echo',argumentsMatch=json.loads(call['function']['arguments'])=={'nested':{'value':7},'label':'synthetic-é'});assert call['id']=='call_gate_b' and call['function']['name']=='gate_b_echo'
     assert json.loads(call['function']['arguments'])=={'nested':{'value':7},'label':'synthetic-é'}
     follow={**body,'messages':body['messages']+[{'role':'assistant','content':None,'tool_calls':calls},{'role':'tool','tool_call_id':call['id'],'content':'{"ok":true}'}]}
     with http(BASE,'/v1/chat/completions',follow,auth) as f:assert json.load(f)['choices'][0]['message']['content']=='TOOL_ROUNDTRIP_OK'
    else:
     result.setdefault('fallbackDiagnostic',{})[case['id']]={'contentMatches':message['content']==case['expectedText']}
     assert message['content']==case['expectedText']
  with http(MOCK,'/__trace',headers={'X-Gate-B-Control':'gate-b-fake-control-key'}) as r:trace=json.load(r)
  assert trace['total']<=128;upstream=trace['total']
  if 'lanes' in case:
   result['fallbackDiagnostic'][case['id']]['lanes']=list(dict.fromkeys(c['lane'] for c in trace['trace']))
   assert result['fallbackDiagnostic'][case['id']]['lanes']==case['lanes']
  rows.append({'testId':case['id'],'pass':True,'upstreamAttempts':len(trace['trace'])})
  result['tests'][case['id']]='PASS'

 stage='key-revocation';admin('/api/keys/'+keyid,{'isActive':False},'PUT');negative(auth);result['keyRevoked']=True
except Exception as error:
 result['failure']={'stage':stage,'category':getattr(error,'code',type(error).__name__)}
finally:
 if keyid and not result['keyRevoked']:
  try:admin('/api/keys/'+keyid,{'isActive':False},'PUT');negative({'Authorization':'Bearer '+key});result['keyRevoked']=True
  except Exception:pass
 result.update(httpObservations=observations,rows=rows,routerRequests=requests,mockUpstreamRequests=upstream,elapsedSeconds=round(time.monotonic()-start,3))
 result['pass']=all(result['tests'].get(n)=='PASS' for n in ['authentication','json-probe','chat-sse','chat-tools','fallback-429','fallback-503']) and result['keyRevoked']
 (runtime/'client-result.json').write_text(json.dumps(result)+'\n')
 print(json.dumps({'httpParityPass':result['pass'],'tests':result['tests'],'keyRevoked':result['keyRevoked'],'failure':result.get('failure')}))
if not result['pass']:raise SystemExit(1)
