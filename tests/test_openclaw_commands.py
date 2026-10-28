"""Synthetic product-adapter tests: never contact a real Gateway or model."""
import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.test_coordination import fixture
from wiki_core.config import load_config
from wiki_core.web import openclaw as oc


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    _, snapshot, _ = fixture(tmp_path)
    route = {'session_key': 'agent:research:synthetic', 'session_id': 'synthetic-session', 'label': 'Synthetic worker'}
    settings = {'enabled': True, 'node_binary': '/synthetic/node', 'entrypoint': '/synthetic/openclaw.mjs',
                'profile': 'synthetic', 'state_dir': '/synthetic/state', 'gateway': 'ws://127.0.0.1:19880',
                'routes': {'research': route}}
    (tmp_path/'wiki.config.yaml').write_text(yaml.safe_dump({'repo_id':'synthetic','openclaw':settings}))
    (tmp_path/'.gitignore').write_text('data/\n')
    for args in [('init',),('config','user.name','Synthetic'),('config','user.email','fixture@example.test'),('add','.'),('commit','-qm','fixture')]:
        subprocess.run(['git',*args],cwd=tmp_path,check=True,capture_output=True)
    monkeypatch.setattr(oc,'build_snapshot',lambda *args:copy.deepcopy(snapshot))
    calls=[]
    observed={'sessionId':route['session_id'], 'sessionInfo':{'hasActiveRun':False,'status':'done', 'activeLeafEntryId':'leaf-before', 'lastRunId':'previous'},
              'pendingInputs':{'total':0},'messages':[]}
    def call(self,method,params):
        calls.append((method,params))
        if method=='chat.send':
            return {'runId':params['idempotencyKey'],'status':'started'}
        return copy.deepcopy(observed)
    monkeypatch.setattr(oc.Gateway,'call',call)
    config=load_config(tmp_path)
    params={'profile':'research','action_id':'task','action_sha256':snapshot['pages.json']['pages'][2]['content_sha256'],
            'message':'Inspect the synthetic status and return findings. Do not change data.'}
    return tmp_path,config,params,observed,calls,snapshot


def complete(runtime,plan):
    _,_,_,h,_,_=runtime
    h['sessionInfo'].update(lastRunId=plan['effect_key'],activeLeafEntryId='terminal',status='done')
    h['messages']=[{'role':'assistant','stopReason':'stop','content':[{'type':'text','text':'Synthetic result.'}],
                    '__openclaw':{'id':'terminal','runId':plan['effect_key'],'runTerminal':True}}]


def test_default_disabled_and_remote_or_unrecognized_config_refused():
    assert oc.validated_config(None)=={'enabled':False}
    with pytest.raises(ValueError):oc.validated_config({'enabled':True,'token':'not-allowed'})


def test_dispatch_one_run_and_recover_exact_result_after_restart(runtime):
    root,cfg,params,h,calls,_=runtime
    p=oc.plan_dispatch(root,cfg,params)
    assert all(m=='chat.history' for m,_ in calls)
    assert 'sessionId' not in calls[0][1]
    assert p['binding']['context_exported'] is False
    oc.dispatch(root,cfg,p)
    assert len([c for c in calls if c[0]=='chat.send'])==1
    with pytest.raises(ValueError,match='intent_exists'):oc.dispatch(root,cfg,p)
    complete(runtime,p)
    query={'profile':'research','action_id':'task','effect_key':p['effect_key']}
    result=oc.inspect(root,cfg,query)
    assert result['result_available'] and not result['integration_hold'] and not result['canonical_write']
    # Fresh config / adapter object reads the durable same run. No process state required.
    repeated=oc.inspect(root,load_config(root),query)
    assert repeated['idempotent_read'] and repeated['result']==result['result']
    assert len([c for c in calls if c[0]=='chat.send'])==1
    assert calls[-1][1]['sessionId']=='synthetic-session'
    assert oc.attempts(root,cfg,'research','task')[0]['effect_key']==p['effect_key']
    assert oc.attempts(root,cfg,'other','task')==[]


def test_changed_action_refuses_send_but_keeps_completed_result(runtime):
    root,cfg,params,_,calls,_=runtime
    p=oc.plan_dispatch(root,cfg,params)
    action=root/'memories/task.md'
    action.write_text(action.read_text()+'\nChanged after planning.\n')
    with pytest.raises(ValueError,match='checkout_not_clean'):oc.dispatch(root,cfg,p)
    assert not any(c[0]=='chat.send' for c in calls)
    subprocess.run(['git','restore','--','memories/task.md'],cwd=root,check=True)
    oc.dispatch(root,cfg,p);complete(runtime,p)
    action.write_text(action.read_text()+'\nChanged after execution.\n')
    got=oc.inspect(root,cfg,{**params,'effect_key':p['effect_key']})
    assert got['result_available'] and got['integration_hold']=='canonical_state_unavailable_or_ineligible'


def test_changed_session_and_other_profile_never_send(runtime):
    root,cfg,params,h,calls,_=runtime
    p=oc.plan_dispatch(root,cfg,params)
    h['sessionId']='another-account-session'
    with pytest.raises(ValueError,match='session_identity_changed'):oc.dispatch(root,cfg,p)
    with pytest.raises(ValueError,match='profile_not_configured'):oc.plan_dispatch(root,cfg,{**params,'profile':'other'})
    assert not any(c[0]=='chat.send' for c in calls)


def test_interrupted_transport_leaves_intent_and_does_not_retry(runtime,monkeypatch):
    root,cfg,params,h,calls,_=runtime
    p=oc.plan_dispatch(root,cfg,params)
    original=oc.Gateway.call
    def failed(self,method,body):
        if method=='chat.send':raise oc.RuntimeErrorCode('openclaw_transport_failed_reconcile')
        return original(self,method,body)
    monkeypatch.setattr(oc.Gateway,'call',failed)
    with pytest.raises(ValueError,match='transport_failed'):oc.dispatch(root,cfg,p)
    with pytest.raises(ValueError,match='intent_exists'):oc.dispatch(root,cfg,p)
    monkeypatch.setattr(oc.Gateway,'call',original)
    complete(runtime,p)
    assert oc.inspect(root,cfg,{**params,'effect_key':p['effect_key']})['result_available']


def test_result_errors_truncation_and_wrong_run_fail_closed(runtime):
    root,cfg,params,h,_,_=runtime
    p=oc.plan_dispatch(root,cfg,params);oc.dispatch(root,cfg,p);complete(runtime,p)
    for field,value in [('truncated',True),('runId','unrelated')]:
        h['messages'][0]['__openclaw'][field]=value
        with pytest.raises(ValueError,match='result_not_complete'):oc.inspect(root,cfg,{**params,'effect_key':p['effect_key']})
        complete(runtime,p)


def test_receipt_tampering_and_cross_card_rejected(runtime):
    root,cfg,params,_,_,_=runtime
    p=oc.plan_dispatch(root,cfg,params);oc.dispatch(root,cfg,p);complete(runtime,p)
    q={**params,'effect_key':p['effect_key']}
    with pytest.raises(ValueError,match='wrong_action'):oc.inspect(root,cfg,{**q,'action_id':'archived'})
    got=oc.inspect(root,cfg,q)
    path=oc.storage(root,cfg,p['effect_key'])/'result.json'
    raw=json.loads(path.read_text());raw['text']='Tampered';path.write_text(json.dumps(raw))
    with pytest.raises(ValueError,match='retained_result_changed'):oc.inspect(root,cfg,q)


def test_snapshot_clock_alone_does_not_change_binding(runtime):
    root,cfg,params,_,_,snapshot=runtime
    p=oc.plan_dispatch(root,cfg,params)
    snapshot['manifest.json']['snapshot_id']='later-clock'
    assert oc.plan_dispatch(root,cfg,params)['binding']==p['binding']


def test_no_external_gateway(runtime):
    _,cfg,_,_,_,_=runtime
    bad=copy.deepcopy(cfg.openclaw);bad['gateway']='wss://example.test:443'
    with pytest.raises(ValueError,match='local_gateway'):oc.validated_config(bad)


def test_second_prepared_plan_cannot_bypass_uncertain_intent(runtime,monkeypatch):
    root,cfg,params,_,calls,_=runtime
    first=oc.plan_dispatch(root,cfg,params)
    second=oc.plan_dispatch(root,cfg,{**params,'message':'A different proposed mission.'})
    original=oc.Gateway.call
    def failed(self,method,body):
        if method=='chat.send':raise oc.RuntimeErrorCode('openclaw_transport_failed_reconcile')
        return original(self,method,body)
    monkeypatch.setattr(oc.Gateway,'call',failed)
    with pytest.raises(ValueError,match='transport_failed'):oc.dispatch(root,cfg,first)
    monkeypatch.setattr(oc.Gateway,'call',original)
    with pytest.raises(ValueError,match='uncollected_attempt'):oc.dispatch(root,cfg,second)
    assert not any(c[0]=='chat.send' for c in calls)


def test_committed_config_change_cannot_reuse_startup_route(runtime):
    root,cfg,params,_,calls,_=runtime
    p=oc.plan_dispatch(root,cfg,params)
    cp=root/'wiki.config.yaml';raw=yaml.safe_load(cp.read_text());raw['openclaw']={'enabled':False};cp.write_text(yaml.safe_dump(raw))
    subprocess.run(['git','add','wiki.config.yaml'],cwd=root,check=True)
    subprocess.run(['git','commit','-qm','Disable route'],cwd=root,check=True)
    with pytest.raises(ValueError,match='config_changed_restart'):oc.plan_dispatch(root,cfg,params)
    with pytest.raises(ValueError,match='config_changed_restart'):oc.dispatch(root,cfg,p)
    assert not any(c[0]=='chat.send' for c in calls)


def test_atomic_intent_creation_preserves_existing_and_refuses_corrupt_receipt(runtime):
    root,cfg,params,_,calls,_=runtime
    p=oc.plan_dispatch(root,cfg,params)
    d=oc.storage(root,cfg,p['effect_key']);d.mkdir(parents=True)
    path=d/'intent.json';path.write_text('{partial')
    with pytest.raises(FileExistsError):oc.write_new(path,{'new':'not written'})
    assert path.read_text()=='{partial'
    assert not list(d.glob('.pending-receipt-*'))
    with pytest.raises(ValueError,match='intent_exists'):oc.dispatch(root,cfg,p)
    with pytest.raises(ValueError,match='receipt_corrupt'):oc.plan_dispatch(root,cfg,{**params,'message':'Different'})
    assert not any(c[0]=='chat.send' for c in calls)


@pytest.mark.parametrize('payload', ['', '{partial', '{}', '{"run_id":"another-run"}'])
def test_invalid_result_never_releases_uncertain_attempt(runtime, payload):
    root,cfg,params,_,calls,_=runtime
    p=oc.plan_dispatch(root,cfg,params);oc.dispatch(root,cfg,p)
    (oc.storage(root,cfg,p['effect_key'])/'result.json').write_text(payload)
    with pytest.raises(ValueError):oc.plan_dispatch(root,cfg,{**params,'message':'Another mission.'})
    assert len([c for c in calls if c[0]=='chat.send'])==1
