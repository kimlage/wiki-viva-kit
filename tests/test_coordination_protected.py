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


def folderize(repo):
    """Add explicit physical owners and connections to the synthetic repo."""
    for path, text in [('AGENTS.md', '# Root guidance\n'), ('index.md', '# Root index\n'),
                       ('finance/costs/AGENTS.md', '# Costs guidance\n'),
                       ('finance/tax/AGENTS.md', '# Tax guidance\n'),
                       ('finance/tax/index.md', '# Tax index\n')]:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists(): target.write_text(text)
    index = repo / 'finance/costs/index.md'
    if not index.exists(): index.write_text('# Costs index\n')
    root_rule = {'from_context': '.', 'to_context': 'finance/costs', 'selector': 'AGENTS.md',
                 'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    tax_rule = {'from_context': 'finance/tax', 'to_context': 'finance/costs',
                'selector': 'finance/tax/source.md', 'section': 'amount', 'use': 'interpret',
                'classification': 'synthetic', 'expires': '2099-01-01'}
    grant = {'read': ['self'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []}
    config_path = repo / 'wiki.config.yaml'
    config = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
    config = config or {}
    config['context_access'] = {
        '.': {'owner': 'root operator', 'policy': grant, 'exports': [root_rule]},
        'finance/costs': {'owner': 'cost operator', 'policy': {**grant, 'read': ['self', 'AGENTS.md', 'finance/tax/source.md']},
                          'imports': [root_rule, tax_rule]},
        'finance/tax': {'owner': 'tax operator', 'policy': grant, 'exports': [tax_rule]},
    }
    config_path.write_text(yaml.safe_dump(config))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'synthetic folder authority')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')

@pytest.fixture
def bound_server(repo, monkeypatch):
    monkeypatch.delenv('WIKI_COCKPIT_CORS_ORIGINS',raising=False)
    monkeypatch.delenv('WIKI_COORDINATION_ALLOWED_CONTEXTS',raising=False)
    monkeypatch.delenv('WIKI_COORDINATION_TRUSTED_REF',raising=False)
    folderize(repo)
    srv=_Server.__new__(_Server); lines=[]
    srv.server=CockpitServer(('127.0.0.1',0),repo,load_config(repo),admin_announce=lines.append,start_jobs=False,coordination_binding=CoordinationBinding(('finance/costs',),'refs/remotes/origin/main','wiki.config.yaml'))
    srv.port=srv.server.server_address[1]; srv.thread=threading.Thread(target=srv.server.serve_forever,daemon=True); srv.thread.start()
    challenge=srv.server.admin_sessions.issue_challenge(); token=srv.server.admin_sessions.unlock(code=_code(lines),challenge=challenge['challenge'])['token']
    try:
        yield BoundServer(srv,token)
    finally:
        srv.close()
        srv.thread.join(timeout=5)
        assert not srv.thread.is_alive()


def payload(repo):
    base=git(repo,'rev-parse','HEAD'); src='finance/costs/result.md'; sha=hashlib.sha256((repo/src).read_bytes()).hexdigest()
    return {'context_id':'finance/costs','approved_revision':base,'content_revision':base,'entry_folder':'finance/costs','entry_index':'finance/costs/index.md','task':{'task_id':'task-1','goal':'Review costs','output':src,'integrator':'reviewer','max_bytes':20000,'evidence':[{'ref':src,'producer':'finance/costs','reason':'authorized task','use':'interpretation','classification':'context','expected_document_sha256':sha}]}}


def test_cli_api_packet_result_preflight_without_global_catalogue(repo,bound_server,monkeypatch,tmp_path):
    srv,token=bound_server; data=payload(repo); headers={ADMIN_SESSION_HEADER:token}
    monkeypatch.setattr(RepositoryReader,'catalogue',lambda *a,**kw: (_ for _ in ()).throw(AssertionError('global catalogue must not run')))
    status,cap=srv.get('/api/coordination/protected-capability',headers=headers)
    assert status==200 and cap['available'] and cap['contexts']==['finance/costs'] and cap['policy_revision']==data['approved_revision']
    status,out=srv.post('/api/coordination/protected/packet',data,headers=headers)
    assert status==200 and out['mode']=='approved' and out['packet']['schema_version']=='wiki.task-context/v1'
    packet=out['packet']; assert packet['inputs'][-1]['text']=='Independent cost assessment\n'
    task=tmp_path/'selection.json'; task.write_text(json.dumps(data['task']))
    cmd=[sys.executable,str(BASE/'scripts/wiki_coordination.py'),'--root',str(repo),'--context-id','finance/costs','--approved-revision',data['approved_revision'],'--revision',data['content_revision'],'--packet-request',str(task),'--folder','finance/costs','--index','finance/costs/index.md']
    assert json.loads(subprocess.check_output(cmd))['packet']==packet
    git(repo,'checkout','-qb','wiki/costs-http'); (repo/'finance/costs/result.md').write_text('Approved branch proposal\n'); git(repo,'add','finance/costs/result.md'); git(repo,'commit','-qm','proposal'); head=git(repo,'rev-parse','HEAD')
    result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':'task-1','context_id':'finance/costs','packet_digest':packet['packet_digest'],'changes':[{'path':'finance/costs/result.md','action':'modified'}],'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':packet['coverage']['missing']},'blockers':[]}
    request={'context_id':'finance/costs','approved_revision':data['approved_revision'],'base':data['approved_revision'],'head':head,'branch':'wiki/costs-http','packet':packet,'result':result}
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
    context_path=repo/'wiki.config.yaml'; d=yaml.safe_load(context_path.read_text());d['context_access']['finance/costs']['policy']['read']=[];context_path.write_text(yaml.safe_dump(d));git(repo,'add','.');git(repo,'commit','-qm','revoke');git(repo,'update-ref','refs/remotes/origin/main','HEAD')
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


@pytest.mark.parametrize('mode', ['', 'v1'])
def test_v1_host_binding_refuses_new_packet_before_policy_read(repo, monkeypatch, mode):
    from wiki_core import coordination_context as coordination
    binding = CoordinationBinding.from_environment({'WIKI_COORDINATION_ALLOWED_CONTEXTS': 'costs',
                                                     'WIKI_COORDINATION_CONTEXT_MODE': mode})
    monkeypatch.setattr(coordination, 'load_policy', lambda *a, **k: pytest.fail('v1 policy opened'))
    monkeypatch.setattr(coordination, 'build_packet', lambda *a, **k: pytest.fail('v1 packet built'))
    with pytest.raises(coordination.ProtectedCoordinationError) as error:
        coordination.prepare_packet(repo, binding, {})
    assert error.value.code == 'coordination_v1_retired'


def test_unapproved_content_and_cross_context_denied_without_metadata(repo,bound_server):
    srv,token=bound_server; headers={ADMIN_SESSION_HEADER:token}; data=payload(repo); base=data['approved_revision']
    git(repo,'checkout','-qb','wiki/unapproved-read'); (repo/'finance/costs/result.md').write_text('unapproved branch secret-free preview\n');git(repo,'add','.');git(repo,'commit','-qm','preview');unapproved=git(repo,'rev-parse','HEAD')
    status,body=srv.post('/api/coordination/protected/packet',{**data,'content_revision':unapproved},headers=headers)
    assert status==409 and body['error_code']=='coordination_content_not_approved' and 'packet' not in body
    cross=json.loads(json.dumps(data)); cross['task']['evidence']=[{'ref':'finance/tax/source.md','producer':'finance/tax','reason':'requested source','use':'interpretation','classification':'context'}]
    status,body=srv.post('/api/coordination/protected/packet',cross,headers=headers)
    assert status==409 and 'finance/tax/source.md' not in json.dumps(body) and 'packet' not in body


def test_legacy_snapshot_and_git_modes_declare_caller_trust(tmp_path):
    from tests.test_coordination import fixture
    config,snapshot,_=fixture(tmp_path)
    index=coordination_index(tmp_path,snapshot); packet=context_packet(tmp_path,config,snapshot,'research','task')
    assert index['trust_boundary']=='caller_trust' and index['policy_enforced'] is False
    assert packet['error_code']=='coordination_context_required' and 'pages' not in packet


def test_backend_resolves_producer_only_after_authorized_selection(repo,bound_server):
    srv,token=bound_server; headers={ADMIN_SESSION_HEADER:token}; data=payload(repo)
    del data['task']['evidence'][0]['producer']
    status,out=srv.post('/api/coordination/protected/packet',data,headers=headers)
    assert status==200 and out['packet']['inputs'][-1]['producer']=='finance/costs'
    data['task']['evidence']=[{'ref':'finance/tax/source.md','reason':'explicit source','use':'interpret','classification':'synthetic','section':'amount'}]
    status,out=srv.post('/api/coordination/protected/packet',data,headers=headers)
    # The bilateral rule alone does not qualify a sibling context for this
    # dispatch; no sibling body or owner metadata is exposed.
    assert status==409 and 'finance/tax/source.md' not in json.dumps(out) and 'producer' not in json.dumps(out)
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


def test_packet_budget_api_cli_and_denied_input_are_safe(repo,bound_server,tmp_path):
    srv,token=bound_server; data=payload(repo); headers={ADMIN_SESSION_HEADER:token}
    data['task']['max_bytes']=100
    status,body=srv.post('/api/coordination/protected/packet',data,headers=headers)
    assert status==409 and body['error_code']=='coordination_budget_exceeded'
    assert 'reduce' in body['blocker']['required_action'].lower() and 'packet' not in body
    assert 'finance/' not in json.dumps(body) and 'Independent cost assessment' not in json.dumps(body)
    task=tmp_path/'selection.json'; task.write_text(json.dumps(data['task']))
    cmd=[sys.executable,str(BASE/'scripts/wiki_coordination.py'),'--root',str(repo),'--context-id','finance/costs','--approved-revision',data['approved_revision'],'--revision',data['content_revision'],'--packet-request',str(task),'--folder','finance/costs','--index','finance/costs/index.md']
    cli=subprocess.run(cmd,capture_output=True,text=True)
    assert cli.returncode != 0 and json.loads(cli.stdout)==body
    data['task']['max_bytes']=20000
    data['task']['evidence']=[{'ref':'finance/tax/source.md','producer':'finance/tax','reason':'selection','use':'interpretation','classification':'context'}]
    status,denied=srv.post('/api/coordination/protected/packet',data,headers=headers)
    assert status==409 and denied['error_code']=='coordination_input_unavailable' and 'finance/' not in json.dumps(denied)


@pytest.mark.parametrize('message', ['mandatory content exceeds byte budget', 'selected content exceeds byte budget', 'complete packet exceeds byte budget'])
def test_only_stable_builder_budget_errors_are_classified(repo,monkeypatch,message):
    from wiki_core import coordination_context as module
    from wiki_core.context_policy import PolicyError
    folderize(repo)
    def fail(*args,**kwargs): raise PolicyError(message)
    monkeypatch.setattr(module,'build_packet',fail)
    with pytest.raises(module.ProtectedCoordinationError) as error:
        module.prepare_packet(repo,CoordinationBinding(('finance/costs',),'refs/remotes/origin/main','wiki.config.yaml'),payload(repo))
    assert error.value.code=='coordination_budget_exceeded'
    def unrelated(*args,**kwargs): raise PolicyError('other budget details')
    monkeypatch.setattr(module,'build_packet',unrelated)
    with pytest.raises(module.ProtectedCoordinationError) as error:
        module.prepare_packet(repo,CoordinationBinding(('finance/costs',),'refs/remotes/origin/main','wiki.config.yaml'),payload(repo))
    assert error.value.code=='coordination_input_unavailable'


def test_profile_changes_never_grant_canonical_context_or_evidence(repo):
    from wiki_core.coordination_context import prepare_packet, ProtectedCoordinationError
    folderize(repo)
    data = payload(repo)
    binding = CoordinationBinding(('finance/costs',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    profile = {'schema_version':'wiki_coordination.v1','common_context':['finance/tax/source.md'],
               'profiles':{'costs':{'label':'Cross-cutting','scope':'Navigation','action_ids':[],
                                    'context_pages':['finance/tax/source.md']}}}
    (repo/'wiki.coordination.yaml').write_text(yaml.safe_dump(profile))
    # Even a profile with the exact canonical context name cannot grant a sibling.
    sibling = json.loads(json.dumps(data))
    sibling['task']['evidence'] = [{'ref':'finance/tax/source.md','producer':'finance/tax','reason':'selected',
                                   'use':'not-approved','classification':'synthetic'}]
    with pytest.raises(ProtectedCoordinationError):
        prepare_packet(repo,binding,sibling)
    with pytest.raises(ProtectedCoordinationError):
        prepare_packet(repo,binding,{**data,'context_id':'tax'})
    approved = prepare_packet(repo,binding,data)
    assert approved['ok'] and approved['packet']['context_id']=='finance/costs'
    assert 'finance/tax/source.md' not in {item['ref'] for item in approved['packet']['inputs']}
