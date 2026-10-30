"""Synthetic Guard observations; actual relay tests live in Node tests."""
import hashlib,json
from wiki_core.web import openclaw as oc

def simulate_guard(root, cfg, plan):
    directory=oc.storage(root,cfg,plan['effect_key']);contract=oc.read_receipt(directory/'mission.json')
    sha=hashlib.sha256((directory/'mission.json').read_bytes()).hexdigest()
    claim={'schema_version':'wiki_openclaw_guard_turn.v1','run_id':plan['effect_key'],
           'session_id':contract['session_id'],'thread_id':contract['native_thread_id'],
           'model':contract['model'],'effort':contract['effort'],'contract_sha256':sha}
    if not (directory/'guard-turn.json').exists():oc.write_new(directory/'guard-turn.json',claim)
    bound={**claim,'turn_id':'synthetic-turn'}
    for name,value in [('guard-bound-turn.json',bound),('guard-terminal.json',{**bound,'status':'completed'})]:
        if not (directory/name).exists():oc.write_new(directory/name,value)
    (directory/'guard-inference.jsonl').write_text(json.dumps({**claim,'turn_id':'synthetic-turn','path':'/responses'})+'\n')

from tests.test_openclaw_commands import runtime, complete
import pytest

def test_policy_choice_is_part_of_plan_intent_and_native_send(runtime):
    root,cfg,params,h,calls,_=runtime
    plan=oc.plan_dispatch(root,cfg,params)
    assert plan['mission']['effort']=='high'
    oc.dispatch(root,cfg,plan)
    patch=next(p for m,p in calls if m=='sessions.patch')
    send=next(p for m,p in calls if m=='chat.send')
    assert patch=={'key':plan['route']['session_key'],'expectedSessionId':plan['route']['session_id'],'model':'openai/example-model','thinkingLevel':'high'}
    assert send['thinking']=='high' and send['suppressCommandInterpretation'] is True
    assert len(send['wikiMission'])==64 and send['sessionId']==plan['route']['session_id']
    with pytest.raises(ValueError,match='mission_policy_required'):oc.plan_dispatch(root,cfg,{**params,'mission_id':'unapproved'})
    complete(runtime,plan)
    h['messages'][0]['model']='different-model'
    with pytest.raises(ValueError,match='selection_unproven'):oc.inspect(root,cfg,{'profile':'research','action_id':'task','effect_key':plan['effect_key']})
    assert (oc.storage(root,cfg,plan['effect_key']).parent/'mission-active.json').exists()
    h['messages'][0]['model']='example-model'
    oc.inspect(root,cfg,{'profile':'research','action_id':'task','effect_key':plan['effect_key']})
    assert not (oc.storage(root,cfg,plan['effect_key']).parent/'mission-active.json').exists()


def test_old_result_inspection_preserves_new_mission_lock(runtime):
    root,cfg,params,h,_,_=runtime
    plan=oc.plan_dispatch(root,cfg,params);oc.dispatch(root,cfg,plan);complete(runtime,plan)
    query={**params,'effect_key':plan['effect_key']}
    first=oc.inspect(root,cfg,query)
    active=oc.storage(root,cfg,plan['effect_key']).parent/'mission-active.json'
    newer={'run_id':'wiki-run-'+'a'*32,'contract_sha256':'b'*64}
    oc.write_new(active,newer)
    h['sessionInfo'].update(lastRunId=newer['run_id'],hasActiveRun=True)
    assert oc.inspect(root,cfg,query)['result']==first['result']
    assert oc.read_receipt(active)==newer


@pytest.mark.parametrize('field,value',[('turn_id','wrong-turn'),('path','/guardian')])
def test_inference_turn_and_path_chain_required(runtime,field,value):
    root,cfg,params,h,_,_=runtime
    plan=oc.plan_dispatch(root,cfg,params);oc.dispatch(root,cfg,plan);complete(runtime,plan)
    file=oc.storage(root,cfg,plan['effect_key'])/'guard-inference.jsonl'
    item=json.loads(file.read_text());item[field]=value;file.write_text(json.dumps(item)+'\n')
    with pytest.raises(ValueError,match='selection_unproven'):oc.inspect(root,cfg,{**params,'effect_key':plan['effect_key']})


def test_module_imports_without_posix_lock_backend():
    import subprocess,sys
    result=subprocess.run([sys.executable,'-c',"import sys;sys.modules['fcntl']=None;import wiki_core.web.openclaw"],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
