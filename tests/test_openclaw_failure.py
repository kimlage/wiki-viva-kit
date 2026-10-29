"""Reviewed failed runs stay distinct from successful execution and incorporation."""
import copy
import hashlib
import json

import pytest

from tests.test_openclaw_commands import runtime
from wiki_core.web import openclaw as oc


def review_inputs(root, cfg, plan, *, author='synthetic-author', reviewer='independent-reviewer'):
    directory=oc.storage(root,cfg,plan['effect_key'])
    evidence={'status':'error','runId':plan['effect_key'],'startedAt':1000,'endedAt':2000,'error':'Synthetic terminal timeout'}
    ep=directory/'observed-error.json';ep.write_text(json.dumps(evidence))
    review={'schema_version':'wiki_openclaw_failure_review.v1','head':oc.git(root,'rev-parse','HEAD'),
            'plan_sha256':oc.digest(plan),'action_id':plan['binding']['action_id'],
            'action_sha256':plan['binding']['action_sha256'],'run_id':plan['effect_key'],
            'session_id':plan['route']['session_id'],'author':author,'reviewer':reviewer,
            'decision':'resolve_without_result','evidence_path':ep.relative_to(root).as_posix(),
            'evidence_sha256':hashlib.sha256(ep.read_bytes()).hexdigest(),
            'reason':'Independently reviewed preserved terminal error.',
            'limits':'Preserved observation; no result or assertion about external effects.'}
    rp=directory/'review.json';rp.write_text(json.dumps(review))
    query={'profile':plan['binding']['profile'],'action_id':plan['binding']['action_id'],
           'effect_key':plan['effect_key'],'review_path':rp.relative_to(root).as_posix(),
           'review_sha256':hashlib.sha256(rp.read_bytes()).hexdigest()}
    return query,rp,ep


def failed(runtime):
    root,cfg,params,h,calls,snap=runtime
    plan=oc.plan_dispatch(root,cfg,params);oc.dispatch(root,cfg,plan)
    h['sessionInfo'].update(status='killed',lastRunId='recovery-run')
    h['pendingInputs']={'total':2,'queuedCount':0,'items':[
        {'id':'cancelled-input','runId':'recovery-run','state':'cancelled'},
        {'id':'interrupted-input','runId':'old-recovery','state':'interrupted'}]}
    query,rp,ep=review_inputs(root,cfg,plan)
    return plan,query,rp,ep


def test_resolution_preserves_evidence_action_and_requires_explicit_new_dispatch(runtime):
    root,cfg,params,h,calls,_=runtime
    plan,q,_,_=failed(runtime)
    directory=oc.storage(root,cfg,plan['effect_key'])
    before={p.name:p.read_bytes() for p in directory.iterdir()}
    canonical=(root/plan['binding']['action_path']).read_bytes()
    with pytest.raises(ValueError,match='uncollected_attempt'):
        oc.plan_dispatch(root,cfg,{**params,'message':'Explicit changed mission'})
    prepared=oc.plan_failure_resolution(root,cfg,q)
    value=oc.resolve_failed(root,cfg,q,prepared)
    assert value['reconciled'] and not value['result_available'] and not value['new_dispatch']
    assert value['status']=='resolved_without_result'
    assert not (directory/'result.json').exists()
    assert all((directory/name).read_bytes()==raw for name,raw in before.items())
    assert canonical==(root/plan['binding']['action_path']).read_bytes()
    assert oc.resolve_failed(root,cfg,q,prepared)==value
    assert oc.inspect(root,cfg,q)['status']=='resolved_without_result'
    item=oc.attempts(root,cfg,'research','task')[0]
    assert item['reconciled'] and item['resolved_without_result'] and not item['has_result']
    with pytest.raises(ValueError,match='intent_exists'):oc.dispatch(root,cfg,plan)
    oc.plan_dispatch(root,cfg,{**params,'message':'Explicit changed mission'})
    assert len([c for c in calls if c[0]=='chat.send'])==1
    with pytest.raises(ValueError,match='receipt_missing'):oc.receipt_source(root,cfg,q)


@pytest.mark.parametrize('field,value',[('run_id','another-run'),('session_id','another-session'),
    ('reviewer','synthetic-author'),('decision','complete'),('head','a'*40)])
def test_review_must_bind_exact_failure_and_independent_actor(runtime,field,value):
    root,cfg,*_=runtime
    _,q,rp,_=failed(runtime)
    r=json.loads(rp.read_text());r[field]=value;rp.write_text(json.dumps(r))
    q['review_sha256']=hashlib.sha256(rp.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='independent_failure_review'):oc.plan_failure_resolution(root,cfg,q)


@pytest.mark.parametrize('target',['review','evidence','session','active','queue','canonical'])
def test_changed_inputs_refuse_before_receipt(runtime,target):
    root,cfg,_,h,_,_=runtime
    plan,q,rp,ep=failed(runtime);prepared=oc.plan_failure_resolution(root,cfg,q)
    if target=='review':rp.write_text(rp.read_text()+' ')
    elif target=='evidence':ep.write_text(ep.read_text()+' ')
    elif target=='session':h['sessionId']='foreign-session'
    elif target=='active':h['sessionInfo']['hasActiveRun']=True
    elif target=='queue':h['pendingInputs']['queuedCount']=1
    else:(root/plan['binding']['action_path']).write_text('Changed canonical action')
    with pytest.raises(ValueError):oc.resolve_failed(root,cfg,q,prepared)
    assert not (oc.storage(root,cfg,plan['effect_key'])/'failure-resolution.json').exists()


@pytest.mark.parametrize('pending',[{'total':True},{'total':-1},{'total':0,'items':None},
    {'total':1,'queuedCount':0,'items':[None]},
    {'total':1,'queuedCount':0,'items':[{'id':'a','state':[]}]},
    {'total':1,'queuedCount':0,'items':[{'id':'a','state':'queued'}]},
    {'total':2,'queuedCount':0,'items':[{'id':'a','state':'cancelled'}]*2},
    {'total':0,'nextBefore':False},{'total':0,'queuedCount':False}])
def test_malformed_or_unsafe_pending_state_refuses(runtime,pending):
    root,cfg,params,h,_,_=runtime;h['pendingInputs']=pending
    with pytest.raises(ValueError):oc.plan_dispatch(root,cfg,params)


def test_complete_pending_history_and_pagination_race(runtime,monkeypatch):
    root,cfg,params,h,calls,_=runtime
    h['pendingInputs']={'total':2,'queuedCount':0,'nextBefore':20,
        'items':[{'id':'a','state':'cancelled'}]}
    original=oc.Gateway.call
    def paged(self,method,args):
        out=original(self,method,args)
        if args.get('pendingBefore')==20:
            out['pendingInputs'].update(nextBefore=None,items=[{'id':'b','state':'interrupted'}])
        return out
    monkeypatch.setattr(oc.Gateway,'call',paged)
    oc.plan_dispatch(root,cfg,params)
    def raced(self,method,args):
        out=paged(self,method,args)
        if args.get('pendingBefore'):out['sessionInfo']['lastRunId']='concurrent-run'
        return out
    monkeypatch.setattr(oc.Gateway,'call',raced)
    with pytest.raises(ValueError,match='session_changed'):oc.plan_dispatch(root,cfg,params)


def test_retained_resolution_rejects_conflict_and_nested_tamper(runtime):
    root,cfg,*_=runtime
    plan,q,_,_=failed(runtime);oc.resolve_failed(root,cfg,q,oc.plan_failure_resolution(root,cfg,q))
    directory=oc.storage(root,cfg,plan['effect_key']);rp=directory/'failure-resolution.json';original=rp.read_bytes()
    r=json.loads(original);r['review']['run_id']='foreign';r['review_sha256']=oc.digest(r['review']);rp.write_text(json.dumps(r))
    with pytest.raises(ValueError):oc.attempts(root,cfg,'research','task')
    rp.write_bytes(original);(directory/'result.json').write_text('{}')
    with pytest.raises(ValueError):oc.inspect(root,cfg,q)


def test_review_digest_and_parse_use_the_same_bytes(runtime,monkeypatch):
    root,cfg,*_=runtime
    _,q,rp,ep=failed(runtime)
    original=oc.receipt_bytes
    def swap_after_read(path):
        raw=original(path)
        if path==rp:
            changed=json.loads(raw);changed['run_id']='foreign-run';path.write_text(json.dumps(changed))
        return raw
    monkeypatch.setattr(oc,'receipt_bytes',swap_after_read)
    # The first read is interpreted consistently. A subsequent execution sees
    # the changed bytes and refuses rather than validating another document.
    prepared=oc.plan_failure_resolution(root,cfg,q)
    assert prepared['review']['run_id']==q['effect_key']
    with pytest.raises(ValueError,match='reviewed_bytes_changed'):oc.resolve_failed(root,cfg,q,prepared)


def test_evidence_cannot_be_replaced_by_rehashing_only_the_retained_copy(runtime):
    root,cfg,*_=runtime
    plan,q,_,_=failed(runtime);oc.resolve_failed(root,cfg,q,oc.plan_failure_resolution(root,cfg,q))
    p=oc.storage(root,cfg,plan['effect_key'])/'failure-resolution.json'
    r=json.loads(p.read_text());r['evidence']['error']='Different unreviewed error'
    r['evidence_sha256']=oc.digest(r['evidence']);r['evidence_raw']=json.dumps(r['evidence'])
    p.write_text(json.dumps(r))
    with pytest.raises(ValueError,match='resolution_changed'):oc.attempts(root,cfg,'research','task')


def test_oversized_final_resolution_is_refused_without_persistence(runtime):
    root,cfg,*_=runtime
    plan,q,rp,ep=failed(runtime)
    ep.write_text(ep.read_text().ljust(oc.MAX_RECEIPT_BYTES-1))
    r=json.loads(rp.read_text());r['evidence_sha256']=hashlib.sha256(ep.read_bytes()).hexdigest()
    rp.write_text(json.dumps(r));q['review_sha256']=hashlib.sha256(rp.read_bytes()).hexdigest()
    prepared=oc.plan_failure_resolution(root,cfg,q)
    with pytest.raises(ValueError,match='receipt_too_large'):oc.resolve_failed(root,cfg,q,prepared)
    assert not (oc.storage(root,cfg,plan['effect_key'])/'failure-resolution.json').exists()
