"""A missing native terminal after restart is never manufactured as an error."""
import datetime as dt
import hashlib
import json
import subprocess
import pytest
import yaml
from tests.test_openclaw_commands import runtime, complete
from tests.test_openclaw_failure import review_inputs
from wiki_core.web import openclaw as oc


def interrupted(runtime, monkeypatch, *, expire=True):
    root,cfg,params,h,_,_=runtime
    cfg.openclaw['recovery']={'mode':'read_only','max_continuations':1}
    doc=yaml.safe_load((root/'wiki.config.yaml').read_text());doc['openclaw']=cfg.openclaw
    (root/'wiki.config.yaml').write_text(yaml.safe_dump(doc))
    for args in (['add','.'],['commit','-qm','Bounded recovery policy']):
        subprocess.run(['git',*args],cwd=root,check=True,capture_output=True)
    plan=oc.plan_dispatch(root,cfg,params);oc.dispatch(root,cfg,plan);complete(runtime,plan)
    directory=oc.storage(root,cfg,plan['effect_key'])
    (directory/'guard-terminal.json').unlink()
    h['sessionInfo'].update(status='interrupted',hasActiveRun=False,lastRunId=None)
    h['messages'][0]['__openclaw']['runTerminal']=False
    contract=oc.read_receipt(directory/'mission.json')
    query,rp,ep=review_inputs(root,cfg,plan)
    evidence={'status':'expired_interrupted','runId':plan['effect_key'],
              'contract_sha256':hashlib.sha256((directory/'mission.json').read_bytes()).hexdigest(),
              'expires_at':contract['expires_at']}
    ep.write_text(json.dumps(evidence));review=json.loads(rp.read_text())
    review['evidence_sha256']=hashlib.sha256(ep.read_bytes()).hexdigest()
    review['reason']='Expired admitted turn; fresh native interrupted/idle state; no terminal fabricated.'
    rp.write_text(json.dumps(review));query['review_sha256']=hashlib.sha256(rp.read_bytes()).hexdigest()
    if expire:
        real=dt.datetime
        class Later(real):
            @classmethod
            def now(cls,tz=None):return real.now(tz)+dt.timedelta(hours=1)
        monkeypatch.setattr(oc.dt,'datetime',Later)
    return plan,directory,query


def test_expired_interrupted_original_resolves_without_result_or_replay(runtime,monkeypatch):
    root,cfg,_,h,calls,_=runtime;plan,d,q=interrupted(runtime,monkeypatch)
    before={p.name:p.read_bytes() for p in d.iterdir()}
    prepared=oc.plan_failure_resolution(root,cfg,q);got=oc.resolve_failed(root,cfg,q,prepared)
    assert got['reconciled'] and not got['result_available'] and not got['new_dispatch']
    assert got['resolution']['evidence']['status']=='expired_interrupted'
    assert got['resolution']['external_effects']=='not_determined_by_this_receipt'
    assert got['resolution']['observation']['leaf_run_id']==plan['effect_key']
    assert 'endedAt' not in got['resolution']['evidence'] and 'error' not in got['resolution']['evidence']
    assert not (d.parent/'mission-active.json').exists()
    assert all((d/k).read_bytes()==v for k,v in before.items())
    assert len([1 for method,_ in calls if method=='chat.send'])==1
    assert oc.resolve_failed(root,cfg,q,prepared)==got
    h['sessionInfo'].update(status='done',lastRunId='later-run',activeLeafEntryId='later-leaf')
    assert oc.inspect(root,cfg,q)['status']=='resolved_without_result'


@pytest.mark.parametrize('change',['active','queue','status','leaf_run','leaf_id','missing_turn',
    'missing_inference','selection','accepted','contract','foreign_lock','partial_recovery','terminal'])
def test_changed_native_or_guard_proof_refuses_before_receipt_and_unlock(runtime,monkeypatch,change):
    root,cfg,_,h,_,_=runtime;plan,d,q=interrupted(runtime,monkeypatch)
    prepared=oc.plan_failure_resolution(root,cfg,q)
    active=d.parent/'mission-active.json'
    if change=='active':h['sessionInfo']['hasActiveRun']=True
    elif change=='queue':h['pendingInputs']={'total':1,'queuedCount':1,'items':[{'id':'new','runId':'other','state':'queued'}]}
    elif change=='status':h['sessionInfo']['status']='done'
    elif change=='leaf_run':h['messages'][0]['__openclaw']['runId']='other'
    elif change=='leaf_id':h['messages'][0]['__openclaw']['id']='other'
    elif change=='missing_turn':(d/'guard-bound-turn.json').unlink()
    elif change=='missing_inference':(d/'guard-inference.jsonl').write_text('')
    elif change=='selection':
        p=d/'guard-turn.json';x=json.loads(p.read_text());x['effort']='ultra';p.write_text(json.dumps(x))
    elif change=='accepted':
        p=d/'accepted.json';x=json.loads(p.read_text());x['plan_sha256']='0'*64;p.write_text(json.dumps(x))
    elif change=='contract':
        p=d/'mission.json';x=json.loads(p.read_text());x['model']='other';p.write_text(json.dumps(x))
    elif change=='foreign_lock':active.write_text(json.dumps({'run_id':'wiki-run-'+'a'*32,'contract_sha256':'a'*64}))
    elif change=='partial_recovery':(d/'guard-recovery-inference.jsonl').write_text('partial')
    elif change=='terminal':(d/'guard-terminal.json').write_text('{}')
    lock_before=active.read_bytes()
    with pytest.raises((ValueError,OSError)):oc.resolve_failed(root,cfg,q,prepared)
    assert not (d/'failure-resolution.json').exists() and active.read_bytes()==lock_before


def test_unexpired_interruption_is_not_permission_to_release(runtime,monkeypatch):
    root,cfg,_,_,_,_=runtime;_,d,q=interrupted(runtime,monkeypatch,expire=False)
    with pytest.raises(ValueError,match='not_expired'):oc.plan_failure_resolution(root,cfg,q)
    assert (d.parent/'mission-active.json').exists() and not (d/'failure-resolution.json').exists()


def test_race_before_persistence_keeps_lock_and_no_resolution(runtime,monkeypatch):
    root,cfg,_,h,_,_=runtime;_,d,q=interrupted(runtime,monkeypatch)
    prepared=oc.plan_failure_resolution(root,cfg,q)
    original=oc.plan_failure_resolution;calls=[]
    def changing(*args):
        calls.append(1)
        if len(calls)==2:h['sessionInfo']['hasActiveRun']=True
        return original(*args)
    monkeypatch.setattr(oc,'plan_failure_resolution',changing)
    with pytest.raises(ValueError):oc.resolve_failed(root,cfg,q,prepared)
    assert (d.parent/'mission-active.json').exists() and not (d/'failure-resolution.json').exists()


@pytest.mark.parametrize('change',['queued','last_run','later_leaf'])
def test_exact_leaf_or_later_complete_observation_race_refuses(runtime,monkeypatch,change):
    import copy
    root,cfg,_,h,_,_=runtime;_,d,q=interrupted(runtime,monkeypatch)
    prepared=oc.plan_failure_resolution(root,cfg,q);original=oc.Gateway.call;seen=[]
    def racing(self,method,params):
        result=original(self,method,params)
        if params.get('messageId'):
            seen.append(1)
            if change=='queued':result['pendingInputs']={'total':1,'queuedCount':1,'items':[{'id':'later','runId':'other','state':'queued'}]}
            elif change=='last_run':result['sessionInfo']['lastRunId']='other'
            else:h['sessionInfo']['activeLeafEntryId']='later'
        return result
    monkeypatch.setattr(oc.Gateway,'call',racing)
    with pytest.raises(ValueError):oc.resolve_failed(root,cfg,q,prepared)
    assert seen and (d.parent/'mission-active.json').exists()
    assert not (d/'failure-resolution.json').exists()


@pytest.mark.parametrize('snapshot_leaf',[None,'foreign'])
def test_native_exact_snapshot_unset_leaf_uses_live_identity_before_and_after(runtime,monkeypatch,snapshot_leaf):
    root,cfg,_,_,_,_=runtime;_,d,q=interrupted(runtime,monkeypatch)
    original=oc.Gateway.call
    def snapshot(self,method,params):
        result=original(self,method,params)
        if params.get('messageId'):result['sessionInfo']['activeLeafEntryId']=snapshot_leaf
        return result
    monkeypatch.setattr(oc.Gateway,'call',snapshot)
    if snapshot_leaf=='foreign':
        with pytest.raises(ValueError):oc.plan_failure_resolution(root,cfg,q)
        assert (d.parent/'mission-active.json').exists()
    else:
        p=oc.plan_failure_resolution(root,cfg,q);r=oc.resolve_failed(root,cfg,q,p)
        assert r['status']=='resolved_without_result' and not r['result_available']
        assert not (d.parent/'mission-active.json').exists()


def preparation(directory,plan,native='00000000-0000-4000-8000-000000000001'):
    bound=oc.read_receipt(directory/'guard-bound-turn.json')
    claim={'schema_version':'wiki_openclaw_recovery.v1','run_id':plan['effect_key'],
      'native_run_id':native,'session_id':plan['route']['session_id'],
      'thread_id':plan['mission']['native_thread_id'],'source_turn_id':bound['turn_id'],
      'contract_sha256':bound['contract_sha256'],'model':plan['mission']['model'].split('/')[1],
      'effort':plan['mission']['effort']}
    oc.write_new(directory/'guard-recovery.json',claim)
    return claim


def test_expired_preparation_only_is_not_a_fabricated_terminal_or_model_result(runtime,monkeypatch):
    root,cfg,_,_,calls,_=runtime;plan,d,q=interrupted(runtime,monkeypatch)
    claim=preparation(d,plan);before={p.name:p.read_bytes() for p in d.iterdir()}
    prepared=oc.plan_failure_resolution(root,cfg,q);got=oc.resolve_failed(root,cfg,q,prepared)
    obs=got['resolution']['observation']['recovery_preparation']
    assert obs['native_run_id']==claim['native_run_id']
    assert obs['sha256']==hashlib.sha256((d/'guard-recovery.json').read_bytes()).hexdigest()
    assert all((d/k).read_bytes()==v for k,v in before.items())
    assert got['status']=='resolved_without_result' and not got['new_dispatch']
    assert got['resolution']['external_effects']=='not_determined_by_this_receipt'
    assert not (d.parent/'mission-active.json').exists() and not (d/'result.json').exists()
    assert len([1 for method,_ in calls if method=='chat.send'])==1
    oc.verified_failure_resolution(d,plan,root)


@pytest.mark.parametrize('change',['turn','inference','terminal','foreign_turn','changed_preparation'])
def test_preparation_resolution_refuses_model_claims_or_marker_drift(runtime,monkeypatch,change):
    root,cfg,_,_,_,_=runtime;plan,d,q=interrupted(runtime,monkeypatch);preparation(d,plan)
    prepared=oc.plan_failure_resolution(root,cfg,q)
    if change in {'turn','inference','terminal'}:(d/('guard-recovery-'+change+'.json')).write_text('{}')
    else:
        f=d/'guard-recovery.json';v=json.loads(f.read_text());v['source_turn_id' if change=='foreign_turn' else 'native_run_id']='changed';f.write_text(json.dumps(v))
    with pytest.raises((ValueError,OSError)):oc.resolve_failed(root,cfg,q,prepared)
    assert (d.parent/'mission-active.json').exists() and not (d/'failure-resolution.json').exists()
