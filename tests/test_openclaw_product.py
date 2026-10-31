"""Native HTTP plan/authority/dispatch/reconcile/proposal path, synthetic Gateway."""
import copy
import hashlib
import json
import subprocess

import pytest
import yaml

from tests.test_web_server import _repo, _server_action, _Server
from tests.test_admin_sessions import _arm, _code
from tests.test_admin_commands import _plan, _execute
from wiki_core.config import load_config
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.web import openclaw as oc
from wiki_core.web.admin.sessions import ADMIN_SESSION_HEADER


@pytest.fixture
def product(tmp_path,monkeypatch,request):
    monkeypatch.setattr('wiki_core.web.git_ops._gh_pr_metadata',lambda *a:None)
    _repo(tmp_path);action=_server_action(tmp_path)
    settings={'enabled':True,'node_binary':'/synthetic/node','entrypoint':'/synthetic/openclaw.mjs',
              'profile':'synthetic','state_dir':'/synthetic/state','gateway':'ws://127.0.0.1:19880',
              'routes':{'research':{'session_key':'agent:research:synthetic','session_id':'synthetic-session','label':'Synthetic worker','native_thread_id':'synthetic-native-thread'}}}
    settings['mission_options']={'execution':{'label':'Synthetic execution','model':'openai/example-model','effort':'high'}}
    cp=tmp_path/'wiki.config.yaml';cfg=yaml.safe_load(cp.read_text());cfg['openclaw']=settings
    cfg['claude']={'enabled':False};cp.write_text(yaml.safe_dump(cfg))
    (tmp_path/'wiki.coordination.yaml').write_text(yaml.safe_dump({'schema_version':'wiki_coordination.v1','profiles':{
       'research':{'label':'Research','scope':'Synthetic technical mission','action_ids':['action-server-synthetic']}}}))
    with (tmp_path/'.gitignore').open('a') as f:f.write('\ndata/derived/\n')
    for args in [('init','-b','main'),('config','user.name','Synthetic'),('config','user.email','fixture@example.test'),
                 ('remote','add','origin','git@github.com:synthetic/wiki.git'),('add','.'),('commit','-qm','fixture')]:
        subprocess.run(['git',*args],cwd=tmp_path,check=True,capture_output=True)
    if getattr(request,'param',False):
        log=tmp_path/'memories/historical-log.md'
        log.write_text('---\npage_id: historical-log\npage_type: system_log\ncontext: system\nvisibility: private_self\nupdated_at: 2026-01-01\nstale_after_days: 30\n---\n\n# Historical log\n\nHistorical note; no current assertion.\n')
        subprocess.run(['git','add','.'],cwd=tmp_path,check=True,capture_output=True)
        subprocess.run(['git','commit','-qm','Synthetic historical record'],cwd=tmp_path,check=True,capture_output=True)
        cfg=yaml.safe_load(cp.read_text());cfg['audit']={'freshness_scope':'impact','freshness_base':oc.git(tmp_path,'rev-parse','HEAD')};cp.write_text(yaml.safe_dump(cfg))
        subprocess.run(['git','add','.'],cwd=tmp_path,check=True,capture_output=True)
        subprocess.run(['git','commit','-qm','Use scoped freshness'],cwd=tmp_path,check=True,capture_output=True)
    h={'sessionId':'synthetic-session','sessionInfo':{'hasActiveRun':False,'status':'done','lastRunId':'previous', 'activeLeafEntryId':'leaf'},
       'pendingInputs':{'total':0},'messages':[]}
    calls=[]
    def call(self,method,params):
        calls.append((method,copy.deepcopy(params)))
        if method=='chat.send':
            from tests.test_openclaw_mission import simulate_guard
            plan=oc.read_receipt(oc.storage(tmp_path,load_config(tmp_path),params['idempotencyKey'])/'intent.json')['plan']
            simulate_guard(tmp_path,load_config(tmp_path),plan)
            h['sessionInfo'].update(lastRunId=params['idempotencyKey'],activeLeafEntryId='terminal')
            h['messages']=[{'role':'assistant','model':'example-model','stopReason':'stop','content':[{'type':'text','text':'Observed synthetic execution.'}],
                            '__openclaw':{'id':'terminal','runId':params['idempotencyKey'],'runTerminal':True}}]
            return {'runId':params['idempotencyKey'],'status':'started'}
        return copy.deepcopy(h)
    monkeypatch.setattr(oc.Gateway,'call',call)
    srv=_Server(tmp_path,load_config(tmp_path));lines,clock=_arm(srv)
    def unlock():
        _,q=srv.post('/api/admin/session/challenge',{})
        status,r=srv.post('/api/admin/session/unlock',{'challenge':q['challenge'],'code':_code(lines)})
        assert status==200,r
        return r['token']
    params={'profile':'research','action_id':'action-server-synthetic','action_sha256':hashlib.sha256(action.read_bytes()).hexdigest(),
            'mission_id':'execution','message':'Inspect synthetic status, return evidence, no data changes.'}
    try:yield srv,tmp_path,action,params,unlock,calls
    finally:srv.close()


def execute(srv,token,command,params):
    status,p=_plan(srv,token,command,params=params)
    assert status==200,p
    status,out=_execute(srv,token,p,confirmation=p['plan']['confirmation']['text'])
    assert status==200 and out['ok'],out
    return out['output'],p


def test_product_dispatch_reconcile_receipt_and_native_proposal(product):
    srv,root,action,params,unlock,calls=product
    before=action.read_text();main=oc.git(root,'rev-parse','main');token=unlock()
    status,coord=srv.get('/api/coordination')
    assert status==200 and coord['profiles'][0]['runtime']['configured']
    sent,plan=execute(srv,token,'agents.openclaw.dispatch',params)
    assert sent['new_dispatch'] and action.read_text()==before
    query={'profile':'research','action_id':params['action_id'],'effect_key':sent['effect_key']}
    got,_=execute(srv,token,'agents.openclaw.inspect',query)
    assert got['result_available'] and not got['integration_hold']
    again,_=execute(srv,token,'agents.openclaw.inspect',query)
    assert again['idempotent_read']
    material,_=execute(srv,token,'agents.openclaw.receipt',query)
    assert material['next_command']=='wiki.proposal.prepare' and action.read_text()==before
    assert oc.git(root,'branch','--show-current').startswith('wiki/runtime-return-')
    out,_=execute(srv,token,'wiki.proposal.prepare',{k:material[k] for k in ('material_path','material_sha256')})
    assert out['prepared'] and not out['published']
    fm,body=parse_frontmatter(action);old,oldbody=parse_frontmatter(before)
    assert body==oldbody and fm['updated_at']==old['updated_at'] and fm['action_state']=='open'
    assert len(fm['action_dialogue'])==1 and fm['action_dialogue'][0]['kind']=='comment'
    observed=oc.runtime_observations(root,srv.server.config)['attempts'][0]
    assert observed['result']['excerpt']=='Observed synthetic execution.'
    assert observed['review']=={'status':'not_observed','head':None}
    assert observed['proposal']['result_path'].startswith('docs/references/runtime-returns/')
    assert observed['action_path']=='memories/actions/action-server-synthetic.md'
    assert oc.git(root,'rev-parse','main')==main
    assert len([x for x in calls if x[0]=='chat.send'])==1
    status, denied = _plan(srv,token,'agents.openclaw.dispatch',params={**params,'message':'Next mission.'})
    assert status==400 and denied['detail']=='openclaw_dispatch_requires_approved_checkout'
    status,replay=_execute(srv,token,plan,confirmation=plan['plan']['confirmation']['text'])
    assert status==409 and replay['error_code']=='admin_plan_already_executed'


def test_product_revocation_after_plan_prevents_gateway_send(product):
    srv,_,_,params,unlock,calls=product;token=unlock()
    status,p=_plan(srv,token,'agents.openclaw.dispatch',params=params);assert status==200,p
    status,_=srv.post('/api/admin/session/lock',{},headers={ADMIN_SESSION_HEADER:token});assert status==200
    status,r=_execute(srv,token,p,confirmation=p['plan']['confirmation']['text'])
    assert status==403 and r['error_code']=='admin_session_invalid'
    assert not any(x[0]=='chat.send' for x in calls)


@pytest.mark.parametrize('characters,accepted', [(120_000, True), (128_000, False)])
def test_receipt_manifest_utf8_limit_precedes_publication(product, characters, accepted):
    srv, root, action, params, unlock, calls = product
    action.write_text(action.read_text() + '\n\n' + 'é' * characters + '\n')
    subprocess.run(['git', 'add', '.'], cwd=root, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-qm', 'Synthetic large action'], cwd=root, check=True, capture_output=True)
    params = {**params, 'action_sha256': hashlib.sha256(action.read_bytes()).hexdigest()}
    before = action.read_bytes(); token = unlock()
    sent, _ = execute(srv, token, 'agents.openclaw.dispatch', params)
    query = {'profile': 'research', 'action_id': params['action_id'], 'effect_key': sent['effect_key']}
    execute(srv, token, 'agents.openclaw.inspect', query)
    status, plan = _plan(srv, token, 'agents.openclaw.receipt', params=query)
    assert status == 200, plan
    _, out = _execute(srv, token, plan, confirmation=plan['plan']['confirmation']['text'])
    directory = oc.storage(root, srv.server.config, sent['effect_key'])
    assert action.read_bytes() == before and len([c for c in calls if c[0] == 'chat.send']) == 1
    if accepted:
        assert out['ok'], out
        manifest = directory/'receipt-material-integrity.json'
        assert manifest.stat().st_size <= oc.MAX_RECEIPT_BYTES
        assert oc.read_receipt(manifest)['action_after_text']
        assert out['output']['proposal']['status'] == 'material_ready'
    else:
        assert not out['ok'] and 'openclaw_receipt_material_too_large' in out['failed_preconditions'], out
        assert not (directory/'receipt-material.json').exists()
        assert not (directory/'receipt-material-integrity.json').exists()
        assert not (directory/'receipt-preview.json').exists()
        assert (directory/'intent.json').is_file() and (directory/'result.json').is_file()


def test_product_dry_run_sends_nothing_and_unknown_route_stays_closed(product):
    srv,root,_,params,unlock,calls=product;token=unlock()
    status,p=_plan(srv,token,'agents.openclaw.dispatch',params=params,dry_run=True);assert status==200,p
    assert all(method=='chat.history' for method,_ in calls) and calls
    assert p['plan']['effects']['external_calls']==[]
    assert 'native orphan reconciliation is possible' in p['plan']['effects']['preparatory_observations'][0]
    assert p['plan']['validation']['dry_run_scope'].startswith('execution only')
    status,r=_execute(srv,token,p,confirmation=p['plan']['confirmation']['text'])
    assert status==200 and r['output']['dry_run']
    assert not any(x[0]=='chat.send' for x in calls)
    status,r=_plan(srv,token,'agents.openclaw.dispatch',params={**params,'profile':'another'})
    assert status==400 and r['error_code']=='admin_invalid_params'


def test_failed_plan_reports_the_native_preparation_that_already_happened(product,monkeypatch):
    srv,_,_,params,unlock,_=product;token=unlock()
    monkeypatch.setattr(oc.Gateway,'call',lambda *args:{'sessionId':'changed-synthetic-session'})
    status,result=_plan(srv,token,'agents.openclaw.dispatch',params=params,dry_run=True)
    assert status==400 and result['detail']=='openclaw_session_identity_changed'
    assert 'chat.history during planning (1 calls)' in result['preparatory_observations'][0]


def test_reviewed_result_cannot_be_replaced_before_receipt_effect(product):
    srv,root,action,params,unlock,calls=product;token=unlock()
    sent,_=execute(srv,token,'agents.openclaw.dispatch',params)
    query={'profile':'research','action_id':params['action_id'],'effect_key':sent['effect_key']}
    execute(srv,token,'agents.openclaw.inspect',query)
    status,p=_plan(srv,token,'agents.openclaw.receipt',params=query);assert status==200,p
    directory=oc.storage(root,srv.server.config,sent['effect_key'])
    target=directory/'result.json';result=json.loads(target.read_text())
    result['text']='Replaced after review.';result['text_sha256']=hashlib.sha256(result['text'].encode()).hexdigest()
    target.write_text(json.dumps(result));before=action.read_bytes()
    status,out=_execute(srv,token,p,confirmation=p['plan']['confirmation']['text'])
    assert not out['ok'] and 'openclaw_reviewed_result_changed' in out['failed_preconditions'],out
    assert action.read_bytes()==before and oc.git(root,'branch','--show-current')=='main'
    assert not (directory/'receipt-material.json').exists()


def test_server_restart_recovers_same_run_and_prepared_proposal_without_dispatch(product):
    srv,root,action,params,unlock,calls=product;token=unlock()
    sent,_=execute(srv,token,'agents.openclaw.dispatch',params)
    query={'profile':'research','action_id':params['action_id'],'effect_key':sent['effect_key']}
    execute(srv,token,'agents.openclaw.inspect',query)
    material,_=execute(srv,token,'agents.openclaw.receipt',query)
    prepared,_=execute(srv,token,'wiki.proposal.prepare',{k:material[k] for k in ('material_path','material_sha256')})
    # A new server has no plan/session state. It derives recovery from the same
    # retained execution and exact native proposal outputs committed in Git.
    restarted=_Server(root,load_config(root))
    try:
        status,coord=restarted.get('/api/coordination');assert status==200,coord
        item=next(a for a in coord['actions'] if a['action_id']==params['action_id'])['runtime_attempts'][0]
        assert item['effect_key']==sent['effect_key'] and item['proposal']['status']=='prepared'
        assert item['proposal']['head']==prepared['head']
        assert len(parse_frontmatter(action)[0]['action_dialogue'])==1
        assert len([c for c in calls if c[0]=='chat.send'])==1
    finally:restarted.close()


@pytest.mark.parametrize('product',[True],indirect=True)
def test_product_c3_preserves_history_and_admits_pure_receipt(product):
    from wiki_core.freshness_impact import repository_report
    srv,root,action,params,unlock,calls=product;token=unlock()
    cfg=srv.server.config;before=(root/'memories/historical-log.md').read_bytes()
    assert repository_report(root,cfg,cfg.audit['freshness_base'])['ok']
    sent,_=execute(srv,token,'agents.openclaw.dispatch',params)
    query={'profile':'research','action_id':params['action_id'],'effect_key':sent['effect_key']}
    execute(srv,token,'agents.openclaw.inspect',query)
    material,_=execute(srv,token,'agents.openclaw.receipt',query)
    execute(srv,token,'wiki.proposal.prepare',{k:material[k] for k in ('material_path','material_sha256')})
    current=load_config(root)
    assert srv.server.config == current == cfg
    assert (root/'memories/historical-log.md').read_bytes() == before
    assert not list((root/'docs').rglob('records.json'))
    report=repository_report(root,current,current.audit['freshness_base'])
    assert report['ok'],report
    assert len(report['operational_comments'])==1 and report['unrelated_debt']
    assert len([c for c in calls if c[0]=='chat.send'])==1


def test_failure_resolution_native_authority_and_no_result(product,monkeypatch):
    from tests.test_openclaw_failure import review_inputs
    srv,root,action,params,unlock,calls=product
    token=unlock();sent,_=execute(srv,token,'agents.openclaw.dispatch',params)
    cfg=load_config(root)
    directory=oc.storage(root,cfg,sent['effect_key'])
    plan=oc.read_receipt(directory/'intent.json')['plan']
    q,_,_=review_inputs(root,cfg,plan)
    # Gateway error has been independently observed; the model produced no reply.
    def failed_history(self,method,args):
        assert method=='chat.history'
        calls.append((method,args))
        return {'sessionId':'synthetic-session','sessionInfo':{'hasActiveRun':False,'status':'killed',
            'lastRunId':'cancelled-recovery','activeLeafEntryId':'failed-leaf'},
            'pendingInputs':{'total':0,'queuedCount':0},'messages':[]}
    monkeypatch.setattr(oc.Gateway,'call',failed_history)
    before=action.read_bytes()
    status,p=_plan(srv,token,'agents.openclaw.resolve_failed',params=q);assert status==200,p
    srv.post('/api/admin/session/lock',{},headers={ADMIN_SESSION_HEADER:token})
    status,out=_execute(srv,token,p,confirmation=p['plan']['confirmation']['text'])
    assert status==403 and not out['ok'],out
    assert not (directory/'failure-resolution.json').exists()
    token=unlock()
    result,_=execute(srv,token,'agents.openclaw.resolve_failed',q)
    assert result['status']=='resolved_without_result' and not result['result_available']
    assert before==action.read_bytes() and not (directory/'result.json').exists()
    assert len([c for c in calls if c[0]=='chat.send'])==1
