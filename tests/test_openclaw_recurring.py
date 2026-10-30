"""Canonical occurrence identity and bounded work, independent of wake-up retries."""
import datetime as dt
import subprocess

import pytest
import yaml
from tests.test_openclaw_commands import runtime, complete
from wiki_core.config import load_config
from wiki_core.web import openclaw as oc
from wiki_core.web import openclaw_recurring as recurring


@pytest.fixture
def scheduled(runtime, monkeypatch):
    root,cfg,params,h,calls,snapshot=runtime
    raw=yaml.safe_load((root/'wiki.config.yaml').read_text())
    raw['openclaw']['recurring']={'review':{'profile':'research','action_id':'task','mission_id':'execution',
        'message':'Read the approved technical package {approved_head}.','interval_minutes':120,
        'watch_paths':['wiki.config.yaml']}}
    (root/'wiki.config.yaml').write_text(yaml.safe_dump(raw))
    subprocess.run(['git','add','.'],cwd=root,check=True,capture_output=True)
    subprocess.run(['git','commit','-qm','recurring policy'],cwd=root,check=True,capture_output=True)
    runtime=(root,load_config(root),params,h,calls,snapshot)
    clock=[dt.datetime(2026,1,1,10,tzinfo=dt.timezone.utc)]
    monkeypatch.setattr(recurring,'now',lambda:clock[0])
    return runtime,clock


def test_same_occurrence_inspects_one_send_and_requires_incorporation(scheduled):
    runtime,clock=scheduled;root,cfg,params,h,calls,_=runtime
    p=recurring.plan_tick(root,cfg,{'rule_id':'review'})
    assert p['mode']=='dispatch' and p['slot']==int(clock[0].timestamp())//7200
    result=recurring.execute_tick(root,cfg,{'rule_id':'review'},p)
    assert result['new_dispatch']
    next=recurring.plan_tick(root,cfg,{'rule_id':'review'})
    assert next['mode']=='inspect' and next['effect_key']==p['effect_key']
    complete(runtime,p['prepared'])
    got=recurring.execute_tick(root,cfg,{'rule_id':'review'},next)
    assert got['result_available'] and not got['new_dispatch']
    clock[0]+=dt.timedelta(hours=2)
    assert recurring.plan_tick(root,cfg,{'rule_id':'review'})['mode']=='review_required'
    assert len([c for c in calls if c[0]=='chat.send'])==1


def test_slot_boundary_invalidates_old_plan_without_send(scheduled):
    runtime,clock=scheduled;root,cfg,_,_,calls,_=runtime
    p=recurring.plan_tick(root,cfg,{'rule_id':'review'});clock[0]+=dt.timedelta(hours=2)
    with pytest.raises(ValueError,match='inputs_changed'):recurring.execute_tick(root,cfg,{'rule_id':'review'},p)
    assert not any(m=='chat.send' for m,_ in calls)


def test_consumed_occurrence_before_intent_stops_future_wakeups(scheduled,monkeypatch):
    runtime,clock=scheduled;root,cfg,_,_,calls,_=runtime
    p=recurring.plan_tick(root,cfg,{'rule_id':'review'})
    monkeypatch.setattr(oc,'dispatch',lambda *a:(_ for _ in ()).throw(RuntimeError('interrupted before intent')))
    with pytest.raises(RuntimeError):recurring.execute_tick(root,cfg,{'rule_id':'review'},p)
    clock[0]+=dt.timedelta(days=1)
    assert recurring.plan_tick(root,cfg,{'rule_id':'review'})['mode']=='reconciliation_required'
    assert not any(m=='chat.send' for m,_ in calls)


def test_incorporated_unchanged_scope_does_not_launch_periodic_model(scheduled,monkeypatch):
    runtime,clock=scheduled;root,cfg,params,h,calls,_=runtime
    p=recurring.plan_tick(root,cfg,{'rule_id':'review'});recurring.execute_tick(root,cfg,{'rule_id':'review'},p)
    complete(runtime,p['prepared']);oc.inspect(root,cfg,{**params,'effect_key':p['effect_key']})
    monkeypatch.setattr(oc,'proposal_status',lambda *a:{'status':'received_in_main'})
    assert recurring.plan_tick(root,cfg,{'rule_id':'review'})['mode']=='already_observed'
    clock[0]+=dt.timedelta(hours=2)
    assert recurring.plan_tick(root,cfg,{'rule_id':'review'})['mode']=='unchanged'
    assert len([v for m,v in calls if m=='chat.send'])==1


def test_no_arbitrary_nonce_or_unconfigured_rule(scheduled):
    runtime,_=scheduled;root,cfg,*_=runtime
    for params in [{'rule_id':'other'},{'rule_id':'review','nonce':'arbitrary'}]:
        with pytest.raises(ValueError):recurring.plan_tick(root,cfg,params)


def test_native_http_wakeup_cli_deduplicates_and_drops_authentication(scheduled,capsys):
    import runpy
    from pathlib import Path
    runtime,_=scheduled;root,cfg,_,_,calls,_=runtime
    observe=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/wiki_openclaw_tick.py'))['observe']
    from wiki_core.paths import WikiPaths
    import json
    jobs=WikiPaths(root,cfg).derived_root/'codex-jobs';jobs.mkdir(parents=True,exist_ok=True)
    queued=jobs/'jsr-independent.json';queued.write_text(json.dumps({'job_id':'jsr-independent','kind':'source_review','status':'queued'}))
    retained=queued.read_bytes()
    first=observe(root,'review')
    assert first['ok'] and first['new_dispatch'] and first['mode']=='dispatch', first
    assert queued.read_bytes()==retained
    again=observe(root,'review')
    assert again['ok'] and again['mode']=='inspect' and not again['new_dispatch']
    assert len([v for m,v in calls if m=='chat.send'])==1
    captured=capsys.readouterr()
    assert 'unlock code' not in captured.out+captured.err
    assert not ({'token','nonce','code','text','message'} & first.keys())


def test_reviewed_failure_waits_for_changed_scope_instead_of_nonexistent_result(scheduled):
    from tests.test_openclaw_failure import review_inputs
    runtime,clock=scheduled;root,cfg,params,h,calls,_=runtime
    p=recurring.plan_tick(root,cfg,{'rule_id':'review'});recurring.execute_tick(root,cfg,{'rule_id':'review'},p)
    q,_,_=review_inputs(root,cfg,p['prepared'])
    h['sessionInfo']['status']='failed'
    resolution=oc.plan_failure_resolution(root,cfg,q);oc.resolve_failed(root,cfg,q,resolution)
    clock[0]+=dt.timedelta(hours=2)
    assert recurring.plan_tick(root,cfg,{'rule_id':'review'})['mode']=='unchanged'
    # An unrelated tick/clock change is not a changed failure condition.
    assert len([v for m,v in calls if m=='chat.send'])==1


def test_blocked_action_does_not_prevent_inspecting_retained_run(scheduled):
    runtime,_=scheduled;root,cfg,params,h,calls,snapshot=runtime
    p=recurring.plan_tick(root,cfg,{'rule_id':'review'});recurring.execute_tick(root,cfg,{'rule_id':'review'},p)
    snapshot['pages.json']['pages'][2]['action_state']='blocked'
    assert recurring.plan_tick(root,cfg,{'rule_id':'review'})['mode']=='inspect'
    assert len([v for m,v in calls if m=='chat.send'])==1
