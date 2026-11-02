"""Synthetic schedule advice; no live scheduler or LLM involved."""
import copy
import json
import subprocess
import sys
from pathlib import Path
import pytest
import yaml
from wiki_core.context_policy import PolicyError, load_policy
from wiki_core.context_schedule import evaluate_wake, occurrence_id, validate_schedule

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture
def case(tmp_path):
    def git(*args):
        return subprocess.check_output(['git','-C',str(tmp_path),*args], stderr=subprocess.PIPE).decode().strip()
    git('init','-q'); git('config','user.name','Synthetic'); git('config','user.email','synthetic@example.invalid')
    document = {'schema_version':'wiki.context/v1','id':'demo','parent':None,'root':'.','purpose':'synthetic','owner':'operator','instructions':[],'skills':[],'templates':[], 'policy':{'read':['self'],'write':[],'deny':{},'capabilities':[],'publication':[]},'imports':[],'exports':[]}
    (tmp_path/'context.yaml').write_text(yaml.safe_dump(document))
    (tmp_path/'demo').mkdir(); (tmp_path/'demo/review.md').write_text('# Synthetic review template\n')
    git('add','.'); git('commit','-qm','synthetic'); git('update-ref','refs/remotes/origin/main','HEAD')
    policy=load_policy(tmp_path,'HEAD')
    request=json.loads((BASE/'examples/context-schedule/request.json').read_text())
    s,w=request['schedule'],request['wake']; s['policy_revision']=policy.policy_revision
    s['enabled']=True
    return policy,s,w,git,tmp_path


def test_disabled_configuration_and_unknown_binding(case):
    p,s,w,_,_=case
    s.pop('enabled')
    assert not validate_schedule(s)['enabled']
    assert evaluate_wake(p,s,w)['decision']=='no-op'
    s['enabled']=True
    result=evaluate_wake(p,s,w)
    assert result['decision']=='eligible' and result['binding']=='unknown'
    assert result['admission']=='blocked' and not result['execution_authorized']
    assert result['llm_calls']==0 and result['state_write']=='not_performed'


def record(s,w,status='completed'):
    t=w['tasks'][0]
    return {**t,'occurrence_id':occurrence_id(s,w['due_at']),'attempts':1,'status':status}


def test_pause_dedupe_and_unchanged_zero_calls(case):
    p,s,w,_,_=case
    w['global_paused']=True
    assert evaluate_wake(p,s,w)['reason']=='global_paused'
    w['global_paused']=False
    w['records']=[record(s,w)]
    original=copy.deepcopy(w)
    assert evaluate_wake(p,s,w)['decision']=='no-op'
    assert w==original
    w['records'][0]['occurrence_id']='c'*64
    result=evaluate_wake(p,s,w)
    assert result['decision']=='no-op' and result['llm_calls']==0
    assert original['records'][0]['status']==w['records'][0]['status']


@pytest.mark.parametrize('status,reason',[('uncertain','effect_reconciliation_required'),('running','executor_completion_unknown'),('denied','authorization_denied')])
def test_receipts_block_replay_even_new_occurrence(case,status,reason):
    p,s,w,_,_=case
    w['records']=[record(s,w,status)]; w['records'][0]['occurrence_id']='c'*64
    assert evaluate_wake(p,s,w)['reason']==reason


def test_limits_overlap_catchup_and_retry(case):
    p,s,w,_,_=case
    w['tasks'].append({**w['tasks'][0],'task_id':'review-two'})
    assert len(evaluate_wake(p,s,w)['eligible'])==1
    w['attempts_this_wake']=1
    assert evaluate_wake(p,s,w)['eligible']==[]
    w['attempts_this_wake']=0; w['active_runs']=1
    assert evaluate_wake(p,s,w)['reason']=='overlap_skip_and_record'
    w['active_runs']=0; w['due_at']='2026-11-02T09:00:00Z'
    assert evaluate_wake(p,s,w)['reason']=='not_latest_due'
    w['due_at']=w['latest_due_at']; w['records']=[record(s,w,'safe_failure')]
    w['tasks']=w['tasks'][:1]
    assert not evaluate_wake(p,s,w)['eligible']
    s['limits']['max_attempts_per_effect']=2
    assert evaluate_wake(p,s,w)['decision']=='eligible'


def test_revocation_and_no_reference_leak(case):
    p,s,w,git,path=case
    (path/'new.md').write_text('synthetic')
    git('add','.'); git('commit','-qm','new approval'); git('update-ref','refs/remotes/origin/main','HEAD')
    result=evaluate_wake(p,s,w)
    assert result['decision']=='blocked' and result['eligible']==[]
    w['global_paused']=True
    assert evaluate_wake(p,s,w)['reason']=='global_paused'


def test_validation_secret_and_foreign_owner(case):
    p,s,w,_,_=case
    for field,value in [('task_template','../bad'),('id','bad\nvalue')]:
        bad={**s,field:value}
        with pytest.raises(PolicyError): evaluate_wake(p,bad,w)
    w['tasks'][0]['context_id']='foreign'
    with pytest.raises(PolicyError): evaluate_wake(p,s,w)
    w['tasks'][0]['context_id']='demo'
    observation={'scheduler':'demo','host':'local','owner':'operator','installed':True,'last_wake':None,'next_expected':None,'interaction':'unknown','paused':False}
    result=evaluate_wake(p,s,w,observation)
    assert result['binding']=='reported' and result['admission']=='blocked'
    assert not result['execution_authorized']
    observation['host']='sk-'+'A'*48
    with pytest.raises(PolicyError): evaluate_wake(p,s,w,observation)


def test_cli_bounded_readonly(case):
    p,s,w,_,path=case
    request=path/'request.json'; request.write_text(json.dumps({'schedule':s,'wake':w}))
    args=[sys.executable,str(BASE/'scripts/wiki_context_schedule.py'),'--repo',str(path),'--approved-revision',p.policy_revision,'--request',str(request)]
    result=subprocess.run(args,capture_output=True,text=True)
    assert result.returncode==0, result.stderr
    assert json.loads(result.stdout)['execution_authorized'] is False
    s['enabled']=False
    request.write_text(json.dumps({'schedule':s,'wake':w}))
    result=subprocess.run(args,capture_output=True,text=True)
    assert result.returncode==0
    assert json.loads(result.stdout)['decision']=='no-op'
    assert json.loads(result.stdout)['llm_calls']==0
    request.write_text(' '*65537)
    assert subprocess.run(args,capture_output=True).returncode==1


def test_stale_declaration_and_input_limits(case):
    p,s,w,_,_=case
    s['policy_revision']='d'*40
    assert evaluate_wake(p,s,w)['reason']=='policy_changed'
    s['policy_revision']=p.policy_revision
    s['limits']['max_tasks_per_wake']=0
    with pytest.raises(PolicyError): evaluate_wake(p,s,w)
    s['limits']['max_tasks_per_wake']=1
    s['trigger']['timezone']='No/Such_Zone'
    with pytest.raises(PolicyError): evaluate_wake(p,s,w)
    s['trigger']['timezone']='Etc/UTC'
    w['now']='not-a-time'
    with pytest.raises(PolicyError): evaluate_wake(p,s,w)
    w['now']=w['due_at']
    w['tasks']*=101
    with pytest.raises(PolicyError): evaluate_wake(p,s,w)


def test_completed_new_version_has_distinct_effect_budget(case):
    p,s,w,_,_=case
    first=evaluate_wake(p,s,w)['eligible'][0]
    w['records']=[record(s,w)]
    w['tasks'][0]['fingerprint']='e'*64
    assert evaluate_wake(p,s,w)['decision']=='no-op'
    w['now']=w['due_at']=w['latest_due_at']='2026-11-02T12:00:00Z'
    second=evaluate_wake(p,s,w)['eligible'][0]
    assert first['task_identity']==second['task_identity']
    assert first['work_id']!=second['work_id']
    assert first['effect_id']!=second['effect_id']
    assert first['occurrence_id']!=second['occurrence_id']
    assert second['effect_identity_version']=='wiki.schedule-effect/v1'
    for status in ('denied','uncertain','running'):
        w['records'][0]['status']=status
        assert evaluate_wake(p,s,w)['decision']=='blocked'


def test_owner_real_identity_missing_template_and_exact_sha(case):
    p,s,w,git,path=case
    document=yaml.safe_load((path/'context.yaml').read_text())
    document['owner']='Kim'
    (path/'context.yaml').write_text(yaml.safe_dump(document))
    git('add','.'); git('commit','-qm','real owner'); git('update-ref','refs/remotes/origin/main','HEAD')
    p=load_policy(path,'HEAD'); s['policy_revision']=p.policy_revision; s['owner']='Kim'
    assert evaluate_wake(p,s,w)['decision']=='eligible'
    s['task_template']='demo/missing.md'
    assert evaluate_wake(p,s,w)['reason']=='template_missing_or_unsupported'
    for size in (41,48,63):
        s['policy_revision']='a'*size
        with pytest.raises(PolicyError): evaluate_wake(p,s,w)
    for size in (40,64):
        s['policy_revision']='a'*size
        assert validate_schedule(s)['owner']=='Kim'
    s['owner']='  '
    with pytest.raises(PolicyError): validate_schedule(s)


def test_task_identity_tuple_avoids_slash_collision(case):
    p,s,w,git,path=case
    document=yaml.safe_load((path/'context.yaml').read_text())
    identities=[]
    for cid,task_id in (('finance/costs','review'),('finance','costs/review')):
        document['id']=cid
        (path/'context.yaml').write_text(yaml.safe_dump(document))
        git('add','.'); git('commit','-qm','synthetic context identity')
        git('update-ref','refs/remotes/origin/main','HEAD')
        p=load_policy(path,'HEAD'); s['policy_revision']=p.policy_revision
        s['context_id']=cid; w['tasks'][0]['context_id']=cid
        w['tasks'][0]['task_id']=task_id
        identities.append(evaluate_wake(p,s,w)['eligible'][0]['task_identity'])
    assert identities[0]!=identities[1]
