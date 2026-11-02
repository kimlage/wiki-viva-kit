import hashlib
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml
from tests.test_context_flow import repo, git
from tests.test_web_server import _Server
from tests.test_admin_sessions import _code
from wiki_core.config import load_config
from wiki_core.coordination import coordination_index, context_packet
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.repository_reader import RepositoryReader
from wiki_core.web.admin.sessions import ADMIN_SESSION_HEADER
from wiki_core.web.server import CockpitServer

BASE=Path(__file__).resolve().parents[1]

class BoundServer:
    def __init__(self,server,token): self.server=server; self.token=token
    def __iter__(self): return iter((self.server,self.token))
    def __repr__(self): return '<BoundServer token redacted>'

@pytest.fixture
def bound_server(repo, monkeypatch):
    monkeypatch.delenv('WIKI_COCKPIT_CORS_ORIGINS',raising=False)
    monkeypatch.delenv('WIKI_COORDINATION_ALLOWED_CONTEXTS',raising=False)
    monkeypatch.delenv('WIKI_COORDINATION_TRUSTED_REF',raising=False)
    srv=_Server.__new__(_Server); lines=[]
    srv.server=CockpitServer(('127.0.0.1',0),repo,load_config(repo),admin_announce=lines.append,start_jobs=False,coordination_binding=CoordinationBinding(('costs',),'refs/remotes/origin/main'))
    srv.port=srv.server.server_address[1]; srv.thread=threading.Thread(target=srv.server.serve_forever,daemon=True); srv.thread.start()
    challenge=srv.server.admin_sessions.issue_challenge(); token=srv.server.admin_sessions.unlock(code=_code(lines),challenge=challenge['challenge'])['token']
    try: yield BoundServer(srv,token)
    finally: srv.close()


def payload(repo):
    base=git(repo,'rev-parse','HEAD'); src='finance/costs/result.md'; sha=hashlib.sha256((repo/src).read_bytes()).hexdigest()
    return {'context_id':'costs','approved_revision':base,'content_revision':base,'task':{'task_id':'task-1','goal':'Review costs','output':src,'integrator':'reviewer','max_bytes':20000,'evidence':[{'ref':src,'producer':'costs','reason':'authorized task','use':'interpretation','classification':'context','expected_document_sha256':sha}]}}


def test_cli_api_packet_result_preflight_without_global_catalogue(repo,bound_server,monkeypatch,tmp_path):
    srv,token=bound_server; data=payload(repo); headers={ADMIN_SESSION_HEADER:token}
    monkeypatch.setattr(RepositoryReader,'catalogue',lambda *a,**kw: (_ for _ in ()).throw(AssertionError('global catalogue must not run')))
    status,cap=srv.get('/api/coordination/protected-capability',headers=headers)
    assert status==200 and cap['available'] and cap['contexts']==['costs'] and cap['policy_revision']==data['approved_revision']
    status,out=srv.post('/api/coordination/protected/packet',data,headers=headers)
    assert status==200 and out['mode']=='approved' and out['packet']['schema_version']=='wiki.task-context/v1'
    packet=out['packet']; assert packet['inputs'][-1]['text']=='Independent cost assessment\n'
    task=tmp_path/'selection.json'; task.write_text(json.dumps(data['task']))
    cmd=[sys.executable,str(BASE/'scripts/wiki_coordination.py'),'--root',str(repo),'--context-id','costs','--approved-revision',data['approved_revision'],'--revision',data['content_revision'],'--packet-request',str(task)]
    assert json.loads(subprocess.check_output(cmd))['packet']==packet
    git(repo,'checkout','-qb','wiki/costs-http'); (repo/'finance/costs/result.md').write_text('Approved branch proposal\n'); git(repo,'add','finance/costs/result.md'); git(repo,'commit','-qm','proposal'); head=git(repo,'rev-parse','HEAD')
    result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':'task-1','context_id':'costs','packet_digest':packet['packet_digest'],'changes':[{'path':'finance/costs/result.md','action':'modified'}],'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':[]},'blockers':[]}
    request={'context_id':'costs','approved_revision':data['approved_revision'],'base':data['approved_revision'],'head':head,'branch':'wiki/costs-http','packet':packet,'result':result}
    status,checked=srv.post('/api/coordination/protected/preflight',request,headers=headers)
    assert status==200 and checked['preflight']['state']=='independent_review_required' and checked['preflight']['merge']=='not_performed'
    untrusted_packet={**packet,'capability_evidence':{'verification':'verified','capabilities':['network'],'scope':['remote'],'limitation':'none'}}
    status,blocked=srv.post('/api/coordination/protected/preflight',{**request,'packet':untrusted_packet},headers=headers)
    assert status==409 and blocked['error_code']=='coordination_preflight_unavailable'
    request['result']={**result,'task_id':'other'}
    status,blocked=srv.post('/api/coordination/protected/preflight',request,headers=headers)
    assert status==409 and blocked['blocker']['status']=='pending' and 'finance/' not in json.dumps(blocked)


def test_no_binding_session_scoping_and_no_attempt_cache(repo,bound_server):
    srv,token=bound_server; data=payload(repo); headers={ADMIN_SESSION_HEADER:token}; key='same-attempt-1234'
    status,body=srv.post('/api/coordination/protected/packet',data,headers={},attempt_key=key)
    assert status==403 and body['error_code']=='coordination_session_required'
    assert body['blocker']['interface']=='Local operator / current cockpit session'
    assert not srv.get('/api/coordination/protected-capability')[1]['available']
    saved=srv.server.coordination_binding; srv.server.coordination_binding=None
    assert not srv.get('/api/coordination/protected-capability',headers=headers)[1]['available']
    status,unavailable=srv.post('/api/coordination/protected/packet',data,headers=headers)
    assert status==409 and unavailable['error_code']=='coordination_not_available'
    assert unavailable['blocker']['interface']=='Local operator host startup configuration'
    srv.server.coordination_binding=saved
    denied={**data,'context_id':'tax'}
    status,body=srv.post('/api/coordination/protected/packet',denied,headers=headers)
    assert status==403 and body['blocker']['status']=='denied' and 'finance/' not in json.dumps(body)
    status,first=srv.post('/api/coordination/protected/packet',data,headers=headers,attempt_key=key)
    assert status==200
    assert key not in srv.server._attempt_receipts
    srv.server.admin_sessions.lock(token)
    status,body=srv.post('/api/coordination/protected/packet',data,headers=headers,attempt_key=key)
    assert status==403 and 'packet' not in body


def test_current_ref_revocation_and_payload_cannot_choose_binding(repo,bound_server):
    srv,token=bound_server; data=payload(repo); headers={ADMIN_SESSION_HEADER:token}; key='revocation-123'
    assert srv.post('/api/coordination/protected/packet',data,headers=headers,attempt_key=key)[0]==200
    for extra in ({'trusted_ref':'refs/heads/main'},{'manifest':'other/context.yaml'},{'adapter_report':{'verification':'verified'}}):
        status,body=srv.post('/api/coordination/protected/packet',{**data,**extra},headers=headers)
        assert status==409 and body['error_code']=='coordination_invalid_request'
    mismatched=json.loads(json.dumps(data));mismatched['task']['evidence'][0]['expected_document_sha256']='0'*64
    assert srv.post('/api/coordination/protected/packet',mismatched,headers=headers)[0]==409
    context_path=repo/'finance/costs/context.yaml'; d=yaml.safe_load(context_path.read_text());d['policy']['read']=[];context_path.write_text(yaml.safe_dump(d));git(repo,'add','.');git(repo,'commit','-qm','revoke');git(repo,'update-ref','refs/remotes/origin/main','HEAD')
    status,body=srv.post('/api/coordination/protected/packet',data,headers=headers,attempt_key=key)
    assert status==409 and body['error_code']=='coordination_policy_unavailable' and 'packet' not in body
    new=payload(repo);status,body=srv.post('/api/coordination/protected/packet',new,headers=headers)
    assert status==409 and body['blocker']['status']=='pending' and 'finance/' not in json.dumps(body)


def test_binding_disabled_default_and_startup_validation(monkeypatch):
    for key in ('WIKI_COORDINATION_ALLOWED_CONTEXTS','WIKI_COORDINATION_TRUSTED_REF'): monkeypatch.delenv(key,raising=False)
    assert CoordinationBinding.from_environment() is None
    monkeypatch.setenv('WIKI_COORDINATION_ALLOWED_CONTEXTS','costs')
    assert CoordinationBinding.from_environment().trusted_ref=='refs/remotes/origin/main'
    monkeypatch.setenv('WIKI_COORDINATION_TRUSTED_REF','HEAD')
    with pytest.raises(ValueError): CoordinationBinding.from_environment()
    monkeypatch.setenv('WIKI_COORDINATION_TRUSTED_REF','refs/remotes/origin/main')
    monkeypatch.setenv('WIKI_COORDINATION_MANIFEST','other/context.yaml')
    with pytest.raises(ValueError): CoordinationBinding.from_environment()


def test_unapproved_content_and_cross_context_denied_without_metadata(repo,bound_server):
    srv,token=bound_server; headers={ADMIN_SESSION_HEADER:token}; data=payload(repo); base=data['approved_revision']
    git(repo,'checkout','-qb','wiki/unapproved-read'); (repo/'finance/costs/result.md').write_text('unapproved branch secret-free preview\n');git(repo,'add','.');git(repo,'commit','-qm','preview');unapproved=git(repo,'rev-parse','HEAD')
    status,body=srv.post('/api/coordination/protected/packet',{**data,'content_revision':unapproved},headers=headers)
    assert status==409 and body['error_code']=='coordination_content_not_approved' and 'packet' not in body
    cross=json.loads(json.dumps(data)); cross['task']['evidence']=[{'ref':'finance/tax/source.md','producer':'tax','reason':'requested source','use':'interpretation','classification':'context'}]
    status,body=srv.post('/api/coordination/protected/packet',cross,headers=headers)
    assert status==409 and 'finance/tax/source.md' not in json.dumps(body) and 'packet' not in body


def test_legacy_snapshot_and_git_modes_declare_caller_trust(tmp_path):
    from tests.test_coordination import fixture
    config,snapshot,_=fixture(tmp_path)
    index=coordination_index(tmp_path,snapshot); packet=context_packet(tmp_path,config,snapshot,'research','task')
    for value in (index,packet):
        assert value['trust_boundary']=='caller_trust' and value['policy_enforced'] is False and value['coverage'].startswith('legacy_')


def test_backend_resolves_producer_only_after_authorized_selection(repo,bound_server):
    srv,token=bound_server; headers={ADMIN_SESSION_HEADER:token}; data=payload(repo)
    del data['task']['evidence'][0]['producer']
    status,out=srv.post('/api/coordination/protected/packet',data,headers=headers)
    assert status==200 and out['packet']['inputs'][-1]['producer']=='costs'
    data['task']['evidence']=[{'ref':'finance/tax/source.md','reason':'explicit source','use':'interpret','classification':'synthetic','section':'amount'}]
    status,out=srv.post('/api/coordination/protected/packet',data,headers=headers)
    assert status==200 and out['packet']['inputs'][-1]['producer']=='tax'
    data['task']['evidence'][0]['classification']='not-approved'
    status,out=srv.post('/api/coordination/protected/packet',data,headers=headers)
    assert status==409 and 'finance/tax/source.md' not in json.dumps(out) and 'producer' not in json.dumps(out)


def test_real_operator_entrypoint_loads_host_binding_only_at_startup(repo,monkeypatch):
    from wiki_core.web import server as module
    import wiki_core.web.admin.sessions as sessions
    monkeypatch.setattr(sessions,'_print_stdout',lambda line: None)
    monkeypatch.delenv('WIKI_COORDINATION_ALLOWED_CONTEXTS',raising=False)
    monkeypatch.delenv('WIKI_COORDINATION_TRUSTED_REF',raising=False)
    monkeypatch.delenv('WIKI_COORDINATION_MANIFEST',raising=False)
    seen=[]
    def stop(server):
        seen.append(server.coordination_binding)
        if server.coordination_binding is not None:
            monkeypatch.setenv('WIKI_COORDINATION_ALLOWED_CONTEXTS','tax')
            assert server.coordination_binding.contexts==('costs',)
        server.server_close()
    monkeypatch.setattr(CockpitServer,'serve_forever',stop)
    assert module.main(['--root',str(repo),'--port','0'])==0
    assert seen==[None]
    monkeypatch.setenv('WIKI_COORDINATION_ALLOWED_CONTEXTS','costs')
    monkeypatch.setenv('WIKI_COORDINATION_TRUSTED_REF','refs/remotes/origin/main')
    assert module.main(['--root',str(repo),'--port','0'])==0
    assert len(seen)==2 and seen[1].trusted_ref=='refs/remotes/origin/main'
