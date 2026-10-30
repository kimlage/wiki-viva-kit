"""Continuation lineage is independent of session defaults and expiry at readback."""
import copy
import hashlib
import json
import uuid

import pytest
from tests.test_openclaw_commands import runtime, complete
from wiki_core.web import openclaw as oc


def recovered(runtime):
    root, cfg, params, history, calls, _ = runtime
    cfg.openclaw['recovery'] = {'mode': 'read_only', 'max_continuations': 1}
    # The fixture loader reads these exact options too.
    import yaml
    doc = yaml.safe_load((root/'wiki.config.yaml').read_text())
    doc['openclaw'] = cfg.openclaw
    (root/'wiki.config.yaml').write_text(yaml.safe_dump(doc))
    import subprocess
    subprocess.run(['git','add','.'],cwd=root,check=True,capture_output=True)
    subprocess.run(['git','commit','-qm','qualify recovery'],cwd=root,check=True,capture_output=True)
    plan = oc.plan_dispatch(root,cfg,params)
    oc.dispatch(root,cfg,plan)
    complete(runtime,plan)
    directory=oc.storage(root,cfg,plan['effect_key'])
    claim=oc.read_receipt(directory/'guard-turn.json')
    native=str(uuid.uuid4())
    lineage={'schema_version':'wiki_openclaw_recovery.v1','run_id':plan['effect_key'],
             'native_run_id':native,'session_id':plan['route']['session_id'],
             'thread_id':claim['thread_id'],'source_turn_id':'synthetic-turn',
             'contract_sha256':claim['contract_sha256'],'model':claim['model'],'effort':claim['effort']}
    oc.write_new(directory/'guard-recovery.json',lineage)
    new={**claim,'native_run_id':native,'turn_id':'native-continuation'}
    for file,value in [('turn.json',new),('bound-turn.json',new),('terminal.json',{**new,'status':'completed'})]:
        oc.write_new(directory/('guard-recovery-'+file),value)
    (directory/'guard-recovery-inference.jsonl').write_text(json.dumps({**new,'path':'/responses'})+'\n')
    (directory/'guard-terminal.json').unlink()
    history['sessionInfo']['lastRunId']=native
    history['messages'][0]['__openclaw']['runId']=native
    return plan,directory,native


def test_native_recovery_captures_actual_run_and_retains_original_identity(runtime):
    root,cfg,params,h,calls,_=runtime
    p,d,native=recovered(runtime)
    got=oc.inspect(root,cfg,{**params,'effect_key':p['effect_key']})
    assert got['result_available'] and got['same_run'] and not got['new_dispatch']
    assert got['result']['run_id']==p['effect_key'] and got['result']['native_run_id']==native
    assert len([v for m,v in calls if m=='chat.send'])==1
    repeated=oc.inspect(root,cfg,{**params,'effect_key':p['effect_key']})
    assert repeated['idempotent_read'] and repeated['result']==got['result']


@pytest.mark.parametrize('file,field,value',[
    ('guard-recovery.json','source_turn_id','other'),
    ('guard-recovery.json','native_run_id',str(uuid.uuid4())),
    ('guard-recovery-turn.json','effort','ultra'),
    ('guard-recovery-bound-turn.json','native_run_id','other'),
    ('guard-recovery-terminal.json','turn_id','other'),
    ('guard-recovery-inference.jsonl','model','other'),
    ('guard-inference.jsonl','effort','ultra'),
])
def test_recovery_refuses_broken_lineage_or_selection(runtime,file,field,value):
    root,cfg,params,_,_,_=runtime
    p,d,_=recovered(runtime)
    doc=json.loads((d/file).read_text());doc[field]=value;(d/file).write_text(json.dumps(doc)+'\n')
    with pytest.raises(ValueError):oc.inspect(root,cfg,{**params,'effect_key':p['effect_key']})
    assert not (d/'result.json').exists()
