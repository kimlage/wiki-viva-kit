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
              'routes':{'research':{'session_key':'agent:research:synthetic','session_id':'synthetic-session','label':'Synthetic worker'}}}
    cp=tmp_path/'wiki.config.yaml';cfg=yaml.safe_load(cp.read_text());cfg['openclaw']=settings;cp.write_text(yaml.safe_dump(cfg))
    (tmp_path/'wiki.coordination.yaml').write_text(yaml.safe_dump({'schema_version':'wiki_coordination.v1','profiles':{
       'research':{'label':'Research','scope':'Synthetic technical mission','action_ids':['action-server-synthetic']}}}))
    with (tmp_path/'.gitignore').open('a') as f:f.write('\ndata/derived/\n')
    for args in [('init','-b','main'),('config','user.name','Synthetic'),('config','user.email','fixture@example.test'),
                 ('remote','add','origin','git@github.com:synthetic/wiki.git'),('add','.'),('commit','-qm','fixture')]:
        subprocess.run(['git',*args],cwd=tmp_path,check=True,capture_output=True)
    if getattr(request,'param',False):
        from wiki_core.freshness_impact import authored_graph
        from wiki_core.document_records import digest, edge_digest, sections
        log=tmp_path/'memories/historical-log.md'
        log.write_text('---\npage_id: historical-log\npage_type: system_log\ncontext: system\nvisibility: private_self\nupdated_at: 2026-01-01\nstale_after_days: 30\n---\n\n# Log\n\n## Historical pointer\n\nUse the [action](actions/action-server-synthetic.md) to navigate to its current card.\n')
        subprocess.run(['git','add','.'],cwd=tmp_path,check=True,capture_output=True)
        subprocess.run(['git','commit','-qm','Synthetic historical record'],cwd=tmp_path,check=True,capture_output=True)
        graph=authored_graph(tmp_path,load_config(tmp_path));ref='memories/historical-log.md'
        record={'id':'pointer','heading':'Historical pointer','independent':True,'rationale':'Historical locator only.',
                'epistemic_status':'observation','recorded_on':'2026-01-01','context_records':[],
                'base_sha256':digest(sections(graph['documents'][ref])[1]['Historical pointer'][2]),
                'current_sha256':digest(sections(graph['documents'][ref])[1]['Historical pointer'][2])}
        edge=next(e for e in graph['edges'] if e['source']==ref and e['target']==action.relative_to(tmp_path).as_posix())
        contract={'schema_version':'document_record.v1','documents':[{'path':ref,'records':[record]}],
                  'bindings':[{'origin':origin,'edge_sha256':edge_digest(edge),'consumer_record':'pointer','role':'navigation',
                    'target_document_sha256':hashlib.sha256(action.read_bytes()).hexdigest(),
                    'rationale':'Exact sentence directs navigation and asserts no current action facts.'} for origin in ('base','current')]}
        for origin in ('base','current'):contract[origin+'_documents_sha256']={p:digest(t) for p,t in graph['documents'].items()}
        contract_ref='docs/references/active-records.json';target=tmp_path/contract_ref;target.parent.mkdir(parents=True);target.write_text(json.dumps(contract))
        cfg=yaml.safe_load(cp.read_text());cfg['audit']={'freshness_base':oc.git(tmp_path,'rev-parse','HEAD'),'freshness_records':contract_ref};cp.write_text(yaml.safe_dump(cfg))
        subprocess.run(['git','add','.'],cwd=tmp_path,check=True,capture_output=True)
        subprocess.run(['git','commit','-qm','Pin historical review'],cwd=tmp_path,check=True,capture_output=True)
    h={'sessionId':'synthetic-session','sessionInfo':{'hasActiveRun':False,'status':'done','lastRunId':'previous', 'activeLeafEntryId':'leaf'},
       'pendingInputs':{'total':0},'messages':[]}
    calls=[]
    def call(self,method,params):
        calls.append((method,copy.deepcopy(params)))
        if method=='chat.send':
            h['sessionInfo'].update(lastRunId=params['idempotencyKey'],activeLeafEntryId='terminal')
            h['messages']=[{'role':'assistant','stopReason':'stop','content':[{'type':'text','text':'Observed synthetic execution.'}],
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
            'message':'Inspect synthetic status, return evidence, no data changes.'}
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


def test_product_dry_run_sends_nothing_and_unknown_route_stays_closed(product):
    srv,root,_,params,unlock,calls=product;token=unlock()
    status,p=_plan(srv,token,'agents.openclaw.dispatch',params=params,dry_run=True);assert status==200,p
    status,r=_execute(srv,token,p,confirmation=p['plan']['confirmation']['text'])
    assert status==200 and r['output']['dry_run']
    assert not any(x[0]=='chat.send' for x in calls)
    status,r=_plan(srv,token,'agents.openclaw.dispatch',params={**params,'profile':'another'})
    assert status==400 and r['error_code']=='admin_invalid_params'


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
    cfg=srv.server.config;before=json.loads((root/cfg.audit['freshness_records']).read_text())
    assert repository_report(root,cfg,cfg.audit['freshness_base'])['ok']
    sent,_=execute(srv,token,'agents.openclaw.dispatch',params)
    query={'profile':'research','action_id':params['action_id'],'effect_key':sent['effect_key']}
    execute(srv,token,'agents.openclaw.inspect',query)
    material,_=execute(srv,token,'agents.openclaw.receipt',query)
    execute(srv,token,'wiki.proposal.prepare',{k:material[k] for k in ('material_path','material_sha256')})
    current=load_config(root);after=json.loads((root/current.audit['freshness_records']).read_text())
    assert srv.server.config == current
    assert after['base_documents_sha256']==before['base_documents_sha256']
    assert after['documents']==before['documents'] and after['bindings'][0]==before['bindings'][0]
    expected=copy.deepcopy(before);new_sha=hashlib.sha256(action.read_bytes()).hexdigest()
    expected['current_documents_sha256'][action.relative_to(root).as_posix()]=new_sha
    expected['bindings'][1]['target_document_sha256']=new_sha
    assert after==expected
    report=repository_report(root,current,current.audit['freshness_base'])
    assert report['ok'],report
    assert len(report['operational_comments'])==1 and report['unrelated_debt']
    assert len([c for c in calls if c[0]=='chat.send'])==1
