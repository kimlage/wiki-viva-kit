"""Real native queue/adapters on synthetic Git repositories; zero model calls."""
from __future__ import annotations

import json
import re
import threading
import time

import pytest

from tests.test_freshness_impact import git, commit
from tests.test_source_operations import _repo, _enable_inventory_adapter
from wiki_core.config import load_config
from wiki_core.paths import WikiPaths
from wiki_core.source_state import read_state, update_state
from wiki_core.web.admin.sessions import AdminSessionManager
from wiki_core.web.codex_jobs import JobRunner
from wiki_core.web.source_review_jobs import plan_source_review_jobs, submit_source_jobs, reconcile_source_job


def fixture(root, *, allowed=True):
    _repo(root)
    _enable_inventory_adapter(root, [
        {'external_id':'drive-123','label':'Changed A','filters':{'file_id':'drive-123','size_bytes':42}},
        {'external_id':'outside','label':'Unrelated new file','filters':{}},
    ])
    (root/'wiki.config.yaml').write_text(
        'repo_id: source-review-test\ndefault_context: system\n'
        'admin:\n  enabled: true\n'
        'audit:\n  freshness_scope: impact\n  information_impact: use_scoped\n'
        f'  source_review_allowed_sources: {"[source-a]" if allowed else "[]"}\n')
    (root/'.gitignore').write_text('data/\n')
    (root/'memories/index.md').write_text(
        '---\npage_id: claim\npage_type: claim\nconfidence: confirmed\n'
        'verified_at: 2026-01-01\nevidence_refs: [memories/evidence.md]\n'
        'updated_at: 2026-01-01\nstale_after_days: 30\n---\nAn observed fact.\n')
    (root/'memories/evidence.md').write_text(
        '---\npage_id: evidence\npage_type: note\n---\nPreserved observation.\n')
    (root/'memories/action.md').write_text(
        '---\npage_id: action\npage_type: action\naction_state: open\n'
        'information_requirements:\n- target: claim\n  fields: [body]\n'
        '  temporal: current\n  max_age_days: 1\n---\nUse a current fact.\n')
    script=root/'scripts/inventory_test.py'
    script.write_text("from pathlib import Path\np=Path('data/adapter-calls.txt')\n"
        "p.parent.mkdir(exist_ok=True)\np.write_text(p.read_text()+'x' if p.exists() else 'x')\n"+script.read_text())
    git(root,'init','-qb','main');git(root,'config','user.email','fixture@example.invalid')
    git(root,'config','user.name','Synthetic fixture');commit(root)
    config=load_config(root)
    lines=[];manager=AdminSessionManager(config,announce=lines.append)
    session=manager.unlock(code=re.search(r'code: ([A-Z0-9-]+)',lines[-1]).group(1),
        challenge=manager.issue_challenge()['challenge'])
    assert session['ok']
    return config,manager,session


def plan(root,config, **overrides):
    return plan_source_review_jobs(root,config,{'base':'HEAD','max_sources':'1',
        'max_attempts':'1','max_adapter_calls':'2',**overrides})


def submit(runner,planned,manager,session):
    return submit_source_jobs(runner,planned,manager=manager,token=session['token'],
        session_id=session['session']['session_id'])


def test_real_async_worker_groups_current_deficit_and_never_certifies_discovery(tmp_path):
    config,manager,session=fixture(tmp_path);head=git(tmp_path,'rev-parse','HEAD')
    planned=plan(tmp_path,config)
    assert len(planned['jobs'])==1 and len(planned['work']['groups'])==1
    assert not (tmp_path/'data/adapter-calls.txt').exists()
    runner=JobRunner(tmp_path,config,autostart=False)
    submitted=submit(runner,planned,manager,session);job_id=submitted['queued_jobs'][0]['job_id']
    runner.start();deadline=time.monotonic()+8
    while runner.get(job_id)['status'] in {'queued','running'} and time.monotonic()<deadline:
        time.sleep(.02)
    result=runner.get(job_id)
    assert result['status']=='delivered',result
    assert result['adapter_calls']==2 and result['model_calls']==0
    assert (tmp_path/'data/adapter-calls.txt').read_text()=='xx'
    assert git(tmp_path,'rev-parse','main')==head and git(tmp_path,'branch','--show-current').startswith('wiki/')
    text=(tmp_path/'memories/sources/config/source-a.md').read_text()
    assert 'Changed A' in text and 'Unrelated new file' not in text
    assert 'verified_at: 2026-01-01' in (tmp_path/'memories/index.md').read_text()
    state=read_state(WikiPaths(tmp_path,config).source_state,'source-a')
    request=state['streams']['file-a']['review_requests'][0]
    assert request['status']=='review_pending' and request['attempts'][0]['status']=='fetched'
    assert result['factual_review_pending']
    # Observing/submitting the same retained job cannot resend it.
    assert reconcile_source_job(runner,result)['status']=='delivered'
    assert (tmp_path/'data/adapter-calls.txt').read_text()=='xx'


@pytest.mark.parametrize('budget,allowed,expected', [('0',True,0),('1',True,0),('2',False,0),('2',True,1)])
def test_explicit_scope_and_adapter_budget_before_any_effect(tmp_path,budget,allowed,expected):
    config,manager,session=fixture(tmp_path,allowed=allowed)
    assert len(plan(tmp_path,config,max_adapter_calls=budget)['jobs'])==expected
    assert not (tmp_path/'data').exists()


def test_revoked_native_authority_blocks_adapter_after_queueing(tmp_path):
    config,manager,session=fixture(tmp_path);runner=JobRunner(tmp_path,config,autostart=False)
    result=submit(runner,plan(tmp_path,config),manager,session);job_id=result['queued_jobs'][0]['job_id']
    manager.lock(session['token'])
    with pytest.raises(ValueError,match='admin_session_invalid'):
        runner.run_job(job_id)
    assert not (tmp_path/'data/adapter-calls.txt').exists()
    assert git(tmp_path,'branch','--show-current')=='main'


def test_adapter_changed_after_plan_is_refused_without_execution(tmp_path):
    config,manager,session=fixture(tmp_path);runner=JobRunner(tmp_path,config,autostart=False)
    result=submit(runner,plan(tmp_path,config),manager,session);job_id=result['queued_jobs'][0]['job_id']
    with (tmp_path/'scripts/inventory_test.py').open('a') as f:f.write('\n# changed adapter\n')
    result=runner.run_job(job_id)
    assert result['status']=='failed' and result['reason']=='source_review_inputs_changed'
    assert not (tmp_path/'data/adapter-calls.txt').exists()


def test_cancel_during_preview_bars_apply_and_reports_completed_read(tmp_path,monkeypatch):
    import wiki_core.web.source_review_jobs as module
    config,manager,session=fixture(tmp_path);runner=JobRunner(tmp_path,config,autostart=False)
    result=submit(runner,plan(tmp_path,config),manager,session);job_id=result['queued_jobs'][0]['job_id']
    native=module.preview_source_refresh
    def preview(*args,**kwargs):
        value=native(*args,**kwargs)
        assert runner.cancel(job_id)['ok']
        return value
    monkeypatch.setattr(module,'preview_source_refresh',preview)
    result=runner.run_job(job_id)
    assert result['status']=='cancelled',result
    assert result['adapter_calls']==1 and not result['adapter_inflight']
    assert (tmp_path/'data/adapter-calls.txt').read_text()=='x'
    assert 'Changed A' not in (tmp_path/'memories/sources/config/source-a.md').read_text()


@pytest.mark.parametrize('status,returncode,own,expected',[
    ('inventory_no_change',0,True,'delivered'),('script_failed',1,True,'failed'),
    ('inventory_no_change',0,False,'failed')])
def test_restart_matches_exact_attempt_and_success_without_resend(tmp_path,status,returncode,own,expected):
    config,manager,session=fixture(tmp_path);runner=JobRunner(tmp_path,config,autostart=False)
    result=submit(runner,plan(tmp_path,config),manager,session);record=result['queued_jobs'][0]
    record.update(status='running',source_preview_token='same-content-token',source_config_sha256='same-config')
    runner._write(record)
    folder=WikiPaths(tmp_path,config).derived_root/'source-operations';folder.mkdir(parents=True)
    (folder/'sop-synthetic.json').write_text(json.dumps({'source_id':'source-a',
        'operation_id':'sop-synthetic','preview_token':'same-content-token','config_sha256':'same-config',
        'request_id':record['source_attempt_id'] if own else 'older-attempt','status':status,'returncode':returncode}))
    restarted=JobRunner(tmp_path,config,autostart=False)
    assert restarted.get(record['job_id'])['status']==expected
    assert restarted._source_review_authorities=={}
    assert not (tmp_path/'data/adapter-calls.txt').exists()


def test_lost_adapter_custody_blocks_other_condition_on_same_source(tmp_path):
    config,manager,session=fixture(tmp_path);runner=JobRunner(tmp_path,config,autostart=False)
    result=submit(runner,plan(tmp_path,config),manager,session);job_id=result['queued_jobs'][0]['job_id']
    def lost(state):
        state['streams']['file-a']['review_requests'][0]['attempts']=[
            {'condition':'different-old-input','status':'started','job_id':'old-job'}]
        return state
    update_state(WikiPaths(tmp_path,config).source_state,'source-a',lost)
    with pytest.raises(ValueError,match='source_review_unreconciled_attempt'):
        runner.run_job(job_id)
    assert not (tmp_path/'data/adapter-calls.txt').exists()


def test_adapter_cannot_launder_unrelated_edits_as_owned_batch_output(tmp_path):
    config,manager,session=fixture(tmp_path)
    script=tmp_path/'scripts/inventory_test.py'
    script.write_text("from pathlib import Path\nPath('unrelated.txt').write_text('external edit')\n"+script.read_text())
    commit(tmp_path)
    runner=JobRunner(tmp_path,config,autostart=False)
    result=submit(runner,plan(tmp_path,config),manager,session);job_id=result['queued_jobs'][0]['job_id']
    result=runner.run_job(job_id)
    assert result['status']=='failed' and result['reason']=='source_review_unexpected_output'
    assert (tmp_path/'unrelated.txt').read_text()=='external edit'  # preserve, never reset WIP
    assert runner._source_review_batches[result['batch_id']]['outputs']=={}


@pytest.mark.parametrize('dry_run',[True,False])
def test_native_http_plan_execute_uses_existing_worker_and_exact_confirmation(tmp_path,dry_run):
    from tests.test_web_server import _Server
    from tests.test_admin_commands import _unlock_admin, _plan, _execute
    config,_,_=fixture(tmp_path)
    server=_Server(tmp_path,config)
    try:
        token=_unlock_admin(server)
        status,response=_plan(server,token,'sources.review_pending',dry_run=dry_run,
            params={'base':'HEAD','max_sources':'1','max_attempts':'1','max_adapter_calls':'2'})
        assert status==200 and response['ok'],response
        planned=response['plan']
        assert bool(planned['effects']['external_calls']) is not dry_run
        assert not (tmp_path/'data/adapter-calls.txt').exists()
        confirmation=planned['confirmation']['text']
        status,result=_execute(server,token,response,confirmation=confirmation)
        assert status==200 and result['ok'],result
        if dry_run:
            assert result['output']['dry_run']
            assert not (tmp_path/'data/adapter-calls.txt').exists()
            assert server.server.jobs.list()==[]
        else:
            job_id=result['output']['queued_jobs'][0]['job_id'];deadline=time.monotonic()+8
            while server.server.jobs.get(job_id)['status'] in {'queued','running'} and time.monotonic()<deadline:
                time.sleep(.02)
            assert server.server.jobs.get(job_id)['status']=='delivered',server.server.jobs.get(job_id)
            assert (tmp_path/'data/adapter-calls.txt').read_text()=='xx'
            from wiki_core.web.admin.sessions import ADMIN_SESSION_HEADER
            status,returned=server.post(f'/api/codex/jobs/{job_id}/return',{'feedback':'Review collection'},
                headers={ADMIN_SESSION_HEADER:token})
            assert status==400 and returned['error']=='source_review_requires_qualified_semantic_reader'
            assert server.server.jobs.briefs.list()==[]
    finally:
        server.close()


def test_complete_projection_preserves_on_demand_requests_when_execution_defers_them(tmp_path):
    from wiki_core.information_review import project_review_work,enqueue_review_work
    from wiki_core.web.sources import build_sources_payload
    config,_,_=fixture(tmp_path)
    report={'schema_version':'wiki_information_impact.v1','pending_reviews':[
        {'path':'memories/index.md','seed':'memories/evidence.md','fields':['body'],
         'priority':'on_demand','reason':'information_changed'}]}
    work=project_review_work(report,build_sources_payload(tmp_path,config)['sources'])
    assert work['on_demand']==['memories/index.md']
    assert work['groups'][0]['requests'][0]['priority']=='on_demand'
    enqueue_review_work(tmp_path,config,work);enqueue_review_work(tmp_path,config,work)
    row=read_state(WikiPaths(tmp_path,config).source_state,'source-a')['streams']['file-a']['review_requests'][0]
    assert row['status']=='review_pending' and row['consumers']==['memories/index.md']


def test_catalogue_commit_or_new_budget_does_not_repeat_unreviewed_collection(tmp_path):
    config,manager,session=fixture(tmp_path);runner=JobRunner(tmp_path,config,autostart=False)
    result=submit(runner,plan(tmp_path,config),manager,session)
    assert runner.run_job(result['queued_jobs'][0]['job_id'])['status']=='delivered'
    commit(tmp_path)
    result=submit(runner,plan(tmp_path,config,max_attempts='2'),manager,session)
    result=runner.run_job(result['queued_jobs'][0]['job_id'])
    assert result['status']=='failed' and result['reason']=='source_review_budget_or_condition_blocks_repeat'
    assert (tmp_path/'data/adapter-calls.txt').read_text()=='xx'


def test_concurrent_edit_to_same_config_after_native_replace_is_preserved_and_refused(tmp_path,monkeypatch):
    from pathlib import Path
    config,manager,session=fixture(tmp_path);runner=JobRunner(tmp_path,config,autostart=False)
    result=submit(runner,plan(tmp_path,config),manager,session)
    target=tmp_path/'memories/sources/config/source-a.md';native=Path.replace
    def replace(path,destination):
        value=native(path,destination)
        if Path(destination)==target:
            target.write_text(target.read_text()+'\nConcurrent authored note.\n')
        return value
    monkeypatch.setattr(Path,'replace',replace)
    result=runner.run_job(result['queued_jobs'][0]['job_id'])
    assert result['status']=='failed' and result['reason']=='source_review_output_changed'
    assert 'Concurrent authored note.' in target.read_text()


def test_missing_ledger_does_not_erase_retained_unknown_adapter_custody(tmp_path):
    config,manager,session=fixture(tmp_path);runner=JobRunner(tmp_path,config,autostart=False)
    first=submit(runner,plan(tmp_path,config),manager,session)['queued_jobs'][0]
    first.update(status='running',adapter_calls=1);runner._write(first)
    (WikiPaths(tmp_path,config).source_state/'source-a.json').unlink()
    second=submit(runner,plan(tmp_path,config,max_attempts='2'),manager,session)['queued_jobs'][0]
    with pytest.raises(ValueError,match='source_review_unreconciled_attempt'):
        runner.run_job(second['job_id'])
    assert not (tmp_path/'data/adapter-calls.txt').exists()


def test_lost_ledger_failed_receipt_cannot_retry_same_condition_with_larger_budget(tmp_path):
    config,manager,session=fixture(tmp_path);runner=JobRunner(tmp_path,config,autostart=False)
    first=submit(runner,plan(tmp_path,config),manager,session)['queued_jobs'][0]
    first.update(status='failed',adapter_calls=1,source_preview_token='p',source_config_sha256='c')
    runner._write(first)
    folder=WikiPaths(tmp_path,config).derived_root/'source-operations';folder.mkdir(parents=True)
    (folder/'sop-failed.json').write_text(json.dumps({'operation_id':'sop-failed',
        'source_id':'source-a','request_id':first['source_attempt_id'],'preview_token':'p',
        'config_sha256':'c','status':'script_failed','returncode':1}))
    (WikiPaths(tmp_path,config).source_state/'source-a.json').unlink()
    second=submit(runner,plan(tmp_path,config,max_attempts='2'),manager,session)['queued_jobs'][0]
    with pytest.raises(ValueError,match='source_review_blocked_condition_requires_change'):
        runner.run_job(second['job_id'])
    assert not (tmp_path/'data/adapter-calls.txt').exists()


def add_second_source(root):
    for ref in ['memories/sources/source-a.md','memories/sources/config/source-a.md']:
        new=root/ref.replace('source-a','source-b')
        new.write_text((root/ref).read_text().replace('source-a','source-b').replace('source-config-a','source-config-b').replace('file-a','file-b')
            .replace('memories/index.md','memories/claim-b.md').replace('scripts/inventory_test.py','scripts/inventory_b.py'))
    script=root/'scripts/inventory_b.py'
    script.write_text((root/'scripts/inventory_test.py').read_text().replace('source-a','source-b'))
    (root/'memories/claim-b.md').write_text((root/'memories/index.md').read_text().replace('page_id: claim','page_id: claim-b'))
    (root/'memories/action-b.md').write_text((root/'memories/action.md').read_text()
        .replace('page_id: action','page_id: action-b').replace('target: claim','target: claim-b'))
    cfg=root/'wiki.config.yaml';cfg.write_text(cfg.read_text().replace('[source-a]','[source-a, source-b]'))
    commit(root)
    return load_config(root)


def test_two_source_jobs_share_proposal_and_preserve_each_others_outputs(tmp_path):
    _,manager,session=fixture(tmp_path);config=add_second_source(tmp_path)
    runner=JobRunner(tmp_path,config,autostart=False)
    planned=plan(tmp_path,config,max_sources='2',max_adapter_calls='4')
    assert len(planned['jobs'])==2
    jobs=submit(runner,planned,manager,session)['queued_jobs']
    results=[runner.run_job(job['job_id']) for job in jobs]
    assert [result['status'] for result in results]==['delivered','delivered'],results
    assert results[0]['branch']==results[1]['branch']
    assert (tmp_path/'data/adapter-calls.txt').read_text()=='xxxx'
    assert 'Changed A' in (tmp_path/'memories/sources/config/source-a.md').read_text()
    assert 'Changed A' in (tmp_path/'memories/sources/config/source-b.md').read_text()


def test_immediate_source_precedes_alphabetically_earlier_active_review(tmp_path,monkeypatch):
    import wiki_core.freshness_impact as module
    _,_,_=fixture(tmp_path);config=add_second_source(tmp_path)
    native=module.repository_report
    def report(*args,**kwargs):
        result=native(*args,**kwargs)
        for row in result['pending_reviews']:
            if row['path']=='memories/action.md':row['priority']='active'
        return result
    monkeypatch.setattr(module,'repository_report',report)
    planned=plan(tmp_path,config,max_sources='1',max_adapter_calls='2')
    assert planned['jobs'][0]['source_id']=='source-b'
