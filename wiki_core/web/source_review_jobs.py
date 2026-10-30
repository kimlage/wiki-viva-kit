"""Fixed deterministic source jobs on the existing job runner and source queue.

The source task is bounded, not a general async host capability. Live authority
stays in RAM and is checked at every native effect. A restart never restores a
grant from a JSON job record. No model, account or connector is selected here.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from wiki_core.config import load_config
from wiki_core.information_review import digest
from wiki_core.paths import WikiPaths
from wiki_core.source_state import review_attempt_allowed, update_state
from wiki_core.web.source_operations import preview_source_refresh, run_source_refresh, list_source_operation_receipts


def git(root, *args):
    return subprocess.check_output(['git',*args],cwd=root,text=True,stderr=subprocess.DEVNULL).strip()


def source_input_hashes(root, candidate):
    return {ref: hashlib.sha256((root/ref).read_bytes()).hexdigest()
            for ref in candidate['input_paths']}


def plan_source_review_jobs(root, config, params):
    from wiki_core.freshness_impact import repository_report
    from wiki_core.information_review import project_review_work
    from wiki_core.web.sources import build_sources_payload
    if config.audit.get('information_impact') != 'use_scoped':
        raise ValueError('source_review_requires_qualified_use_scoped_policy')
    try:
        budget={key:int(params[key]) for key in ['max_sources','max_attempts','max_adapter_calls']}
    except (ValueError,TypeError,KeyError) as exc:raise ValueError('source_review_budget_required') from exc
    if not (0<=budget['max_sources']<=8 and 1<=budget['max_attempts']<=3 and 0<=budget['max_adapter_calls']<=16):
        raise ValueError('source_review_budget_invalid')
    if git(root,'status','--porcelain','--untracked-files=all'):
        raise ValueError('source_review_requires_clean_checkout')
    report=repository_report(root,config,params['base'])
    if not report['ok']:raise ValueError('source_review_integrity_blocked')
    sources=build_sources_payload(root,config)['sources']
    work=project_review_work(report,sources)
    by_id={s['source_id']:s for s in sources};selected=[]
    allowed_sources=config.audit.get('source_review_allowed_sources') or []
    if (not isinstance(allowed_sources,list) or any(not isinstance(s,str) or not s.strip() for s in allowed_sources)
            or len(set(allowed_sources)) != len(allowed_sources)):
        raise ValueError('source_review_allowlist_invalid')
    qualified_sources=set(allowed_sources)
    priorities={'immediate':0,'active':1,'on_demand':2}
    source_ids={g['source_id'] for g in work['groups']}
    for source_id in sorted(source_ids,key=lambda sid:(min(priorities[r['priority']]
            for g in work['groups'] if g['source_id']==sid for r in g['requests']),sid)):
        if source_id not in qualified_sources:continue
        source=by_id[source_id]
        groups=[{**g,'requests':[r for r in g['requests'] if r['priority']!='on_demand']}
            for g in work['groups'] if g['source_id']==source_id]
        groups=[g for g in groups if g['requests']]
        if not groups:continue
        refs={source['path'],source['config_ref']} | {ref for group in groups for ref in group['input_paths']}
        from wiki_core.source_recipe import extract_recipe_mapping,parse_recipe
        recipe=parse_recipe(extract_recipe_mapping((root/source['config_ref']).read_text()))
        argv=recipe.refresh_argv or recipe.ingest_argv
        if len(argv)>=2:
            ref=argv[1]
            if Path(ref).is_absolute() or not ref.startswith('scripts/') or '..' in Path(ref).parts:
                raise ValueError('source_review_adapter_not_owned')
            if git(root,'hash-object','--',ref)!=git(root,'rev-parse','HEAD:'+ref):
                raise ValueError('source_review_adapter_uncommitted')
            refs.add(ref)
        refs=sorted(refs)
        mode=(source.get('update_route') or {}).get('mode')
        selected.append({'source_id':source_id,'groups':groups,'mode':mode,
            'input_paths':refs,'inputs':{ref:hashlib.sha256((root/ref).read_bytes()).hexdigest() for ref in refs},
            'head':report['head_sha'],'raw_path':'','budget':budget})
    remaining_calls=budget['max_adapter_calls']
    bounded=[]
    for candidate in selected:
        estimate=2 if candidate['mode']=='deterministic_connector' else 1 if candidate['mode']=='script' else 0
        if estimate>remaining_calls:continue
        remaining_calls-=estimate;bounded.append(candidate)
        if len(bounded)>=budget['max_sources']:break
    selected=bounded if budget['max_sources'] else []
    return {'schema_version':'wiki_source_review_batch.v1','work':work,'jobs':selected,
            'head':report['head_sha'],'branch':git(root,'branch','--show-current'),
            'budget':budget,'model_calls':0,'adapter_calls_during_plan':0}


def submit_source_jobs(runner, plan, *, manager, token, session_id):
    """Only called by the fixed native command after exact plan validation."""
    from wiki_core.information_review import enqueue_review_work
    def admitted(capabilities, call):
        value=manager.execute_current(token,session_id,capabilities,call)
        if not value.get('ok'):raise ValueError(value.get('error_code','source_review_authority_expired'))
        return value['result']
    if load_config(runner.root)!=runner.config or git(runner.root,'rev-parse','HEAD')!=plan['head']:
        raise ValueError('source_review_context_changed')
    admitted(('sources.execute',),lambda:enqueue_review_work(runner.root,runner.config,plan['work']))
    jobs=[]
    batch_id=digest(plan)
    runner._source_review_batches.setdefault(batch_id,{'head':plan['head'],'branch':plan['branch'],'outputs':{}})
    for candidate in plan['jobs']:
        if source_input_hashes(runner.root,candidate)!=candidate['inputs']:
            raise ValueError('source_review_inputs_changed')
        job_id='jsr'+digest(candidate)[:16]
        previous=runner.get(job_id)
        if previous:
            # A record is not proof of a live worker. Reconcile retained native
            # results; never launch again merely because observation stopped.
            jobs.append(reconcile_source_job(runner,previous))
            continue
        record={'schema_version':'wiki_web_codex_job.v1','job_id':job_id,'kind':'source_review',
            'source_id':candidate['source_id'],'source_plan':candidate,'source_attempt_id':'sr-'+__import__('uuid').uuid4().hex,'batch_id':batch_id,'status':'queued','reason':'','created_at':runner_now(),
            'agent':'deterministic_source','mission_kind':'source_refresh','intent':'Collect the declared source scope; retain factual review.',
            'steps':[{'id':k,'label':label,'status':'pending'} for k,label in [
                ('ground','Check source scope and budget'),('branch','Prepare proposal'),
                ('refresh','Collect source'),('review','Await factual review')]],
            'adapter_calls':0,'model_calls':0,'factual_review_pending':True,'branch':None,
            'started_at':None,'finished_at':None,'dry_run':False}
        runner._source_review_authorities[job_id]=admitted
        admitted(('sources.execute',),lambda:runner._write(record))
        runner._queue.put(job_id);jobs.append(record)
    return {'queued_jobs':jobs,'model_calls':0,'work_groups':len(plan['work']['groups']),
            'unresolved':plan['work']['unresolved']}


def runner_now():
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _retained_receipt(runner, record):
    token = record.get('source_preview_token')
    if not token or not record.get('source_attempt_id'):
        return None
    receipts = list_source_operation_receipts(runner.root,runner.config,record['source_plan']['source_id'])
    return next((receipt for receipt in receipts if receipt.get('preview_token') == token
        and receipt.get('request_id') == record['source_attempt_id']
        and receipt.get('config_sha256') == record.get('source_config_sha256')), None)


def _successful_receipt(receipt):
    return receipt.get('returncode') == 0 and receipt.get('status') in {
        'script_complete','inventory_applied','inventory_no_change','inventory_reviewed'}


def reconcile_source_job(runner, record):
    if record['status'] not in {'queued','running'}:return record
    owned=record['job_id'] in runner._source_review_authorities
    with runner._queue.mutex:
        queued = record['job_id'] in runner._queue.queue
    if owned and (runner._running_id == record['job_id'] or queued):return record
    receipt = _retained_receipt(runner,record)
    if receipt:
        record['source_operation']=receipt['operation_id']
        success=_successful_receipt(receipt)
        return runner._set_status(record,'delivered' if success else 'failed',
            reason='Source result recovered; factual review remains pending' if success else 'source_review_failed_receipt_recovered')
    return runner._set_status(record,'failed',reason='source_review_reconciliation_required_no_automatic_retry')


def run_source_job(runner, record):
    try:
        return _run_source_job(runner, record)
    finally:
        runner._source_review_authorities.pop(record['job_id'],None)


def _run_source_job(runner, record):
    candidate=record['source_plan'];authority=runner._source_review_authorities.get(record['job_id'])
    if authority is None:return reconcile_source_job(runner,record)
    def admitted(capabilities, call):
        if record['job_id'] in runner._cancelled:
            raise ValueError('source_review_cancelled_before_next_effect')
        return authority(capabilities,call)
    if load_config(runner.root)!=runner.config or source_input_hashes(runner.root,candidate)!=candidate['inputs']:
        return runner._set_status(record,'failed',reason='source_review_inputs_changed')
    batch=runner._source_review_batches.get(record.get('batch_id'))
    if (not batch or git(runner.root,'rev-parse','HEAD')!=candidate['head']
            or git(runner.root,'branch','--show-current')!=batch['branch']
            or runner._dirty_hashes()!=batch['outputs']):
        return runner._set_status(record,'failed',reason='source_review_checkout_changed')
    paths=WikiPaths(runner.root,runner.config)
    condition=digest({'inputs':candidate['inputs'],'conditions':sorted({r['condition'] for g in candidate['groups'] for r in g['requests']})})
    required_calls=2 if candidate['mode']=='deterministic_connector' else 1
    precondition = ('source_requires_qualified_semantic_reader_or_export' if candidate['mode'] not in {'script','deterministic_connector'}
        else 'source_query_budget_insufficient' if candidate['budget']['max_adapter_calls']<required_calls
        else 'source_review_raw_scope_unresolved' if candidate['mode']=='script' and not candidate.get('raw_path') else None)
    if precondition:return runner._set_status(record,'failed',reason=precondition)
    def adapter_effect(call):
        def invoke():
            if record['adapter_calls'] >= candidate['budget']['max_adapter_calls']:
                raise ValueError('source_review_adapter_budget_exhausted')
            record['adapter_calls'] += 1
            record['adapter_inflight'] = True
            runner._write(record)
            try:
                return call()
            finally:
                record['adapter_inflight'] = False
                runner._write(record)
        return admitted(('sources.execute',),invoke)
    can_run=[]
    def claim(state):
        attempts={a.get('job_id') for stream in state.get('streams',{}).values()
            for request in stream.get('review_requests',[]) for a in request.get('attempts',[])}
        active_conditions={r['condition'] for g in candidate['groups'] for r in g['requests']}
        for previous in runner.list():
            if (previous.get('job_id')==record['job_id'] or previous.get('kind')!='source_review'
                or previous.get('source_plan',{}).get('source_id')!=candidate['source_id']
                or not previous.get('adapter_calls') or previous['job_id'] in attempts):continue
            # A missing ledger is not a new source. Retained job custody and
            # exact receipts still govern authorization of the next attempt.
            receipt=_retained_receipt(runner,previous)
            if not receipt:raise ValueError('source_review_unreconciled_attempt')
            previous_conditions={r['condition'] for g in previous['source_plan']['groups'] for r in g['requests']}
            if _successful_receipt(receipt) and previous_conditions & active_conditions:
                raise ValueError('source_review_collected_scope_requires_factual_review')
            previous_condition=digest({'inputs':previous['source_plan']['inputs'],
                'conditions':sorted(previous_conditions)})
            if not _successful_receipt(receipt) and previous_condition == condition:
                raise ValueError('source_review_blocked_condition_requires_change')
        # A lost operator does not prove its adapter stopped. Source custody
        # survives changed budgets/inputs and bars another background effect.
        for stream in state.get('streams',{}).values():
            for request in stream.get('review_requests',[]):
                for attempt in request.get('attempts',[]):
                    if attempt.get('status') not in {'started','uncertain'}:continue
                    prior=runner.get(attempt.get('job_id',''))
                    receipt=_retained_receipt(runner,prior) if prior and prior.get('kind')=='source_review' else None
                    if receipt:
                        attempt['status']='fetched' if _successful_receipt(receipt) else 'blocked'
                        attempt['reason']='exact_native_receipt_reconciled'
                    else:
                        raise ValueError('source_review_unreconciled_attempt')
        for group in candidate['groups']:
            requests=state.get('streams',{}).get(group['stream_id'],{}).get('review_requests',[])
            from wiki_core.source_state import merge_review_requests
            expected=merge_review_requests({'source_id':candidate['source_id'],'streams':{}}, group['stream_id'],group['requests'])
            ids={r['request_id'] for r in expected['streams'][group['stream_id']]['review_requests']}
            for request in requests:
                if request['request_id'] not in ids:continue
                if request.get('status')=='verified':continue
                if any(a.get('status')=='fetched' and (not a.get('review_conditions')
                    or set(a['review_conditions']) & set(request.get('conditions',[])))
                    for a in request.get('attempts',[])):
                    continue  # Collected work needs factual review, not another fetch.
                if any(a.get('condition')==condition and a.get('status') in {'started','fetched'} for a in request.get('attempts',[])):
                    continue
                if review_attempt_allowed(request,condition,max_attempts=candidate['budget']['max_attempts']):
                    request.setdefault('attempts',[]).append({'job_id':record['job_id'],'condition':condition,'status':'started','review_conditions':request['conditions'],'at':runner_now()})
                    can_run.append(request['request_id'])
        return state
    admitted(('sources.execute',),lambda:update_state(paths.source_state,candidate['source_id'],claim))
    if not can_run:return runner._set_status(record,'failed',reason='source_review_budget_or_condition_blocks_repeat')
    def outcome(status, reason):
        def update(state):
            for group in candidate['groups']:
                for request in state.get('streams',{}).get(group['stream_id'],{}).get('review_requests',[]):
                    for attempt in request.get('attempts',[]):
                        if attempt.get('job_id')==record['job_id']:
                            attempt['status']=status;attempt['reason']=reason
                            request['status']='blocked' if status=='blocked' else 'review_pending'
            return state
        authority(('sources.execute',),lambda:update_state(paths.source_state,candidate['source_id'],update))
    try:
        runner._set_status(record,'running');runner._set_step(record,'ground','complete')
        from wiki_core.web.git_workflows import run_git_workflow
        if batch['branch'] == str(runner.config.approval.get('default_branch') or 'main'):
            branch=admitted(('git.propose',),lambda:run_git_workflow(runner.root,runner.config,'start_proposal',
                {'theme':'source-review-'+record['job_id']},dry_run=False))
            if not branch.get('ok'):raise ValueError('source_review_proposal_failed')
            batch['branch']=branch.get('data',{}).get('branch')
        record['branch']=batch['branch'];runner._set_step(record,'branch','complete')
        runner._set_step(record,'refresh','running')
        if source_input_hashes(runner.root,candidate)!=candidate['inputs'] or load_config(runner.root)!=runner.config:
            raise ValueError('source_review_inputs_changed')
        preview=adapter_effect(lambda:preview_source_refresh(runner.root,runner.config,
            candidate['source_id'],'__source__',candidate['raw_path']))
        record['source_preview_token']=preview['preview_token']
        record['source_config_sha256']=preview['config_sha256'];runner._write(record)
        # The native adapter rechecks the inventory on run (two budgeted calls),
        # preserving its existing TOCTOU guard rather than treating a preview as current.
        stream_ids={g['stream_id'] for g in candidate['groups']}
        selected=[r['external_id'] for r in (preview.get('discovery') or {}).get('records',[])
                  if r.get('status') in {'new','changed','enriched'} and r.get('stream_id') in stream_ids]
        record['selected_external_ids']=selected
        runner._write(record)
        if source_input_hashes(runner.root,candidate)!=candidate['inputs'] or load_config(runner.root)!=runner.config:
            raise ValueError('source_review_inputs_changed')
        result=adapter_effect(lambda:run_source_refresh(runner.root,runner.config,
            candidate['source_id'],'__source__',candidate['raw_path'],preview['preview_token'],selected,request_id=record['source_attempt_id']))
        if not result.get('ok'):raise ValueError('source_review_refresh_failed')
        outputs=runner._dirty_hashes()
        modified={ref for ref in set(outputs)|set(batch['outputs'])
            if outputs.get(ref)!=batch['outputs'].get(ref)}
        if modified - {candidate['groups'][0]['config_ref']}:
            raise ValueError('source_review_unexpected_output')
        config_ref=candidate['groups'][0]['config_ref']
        if hashlib.sha256((runner.root/config_ref).read_bytes()).hexdigest() != result['config_sha256_after']:
            raise ValueError('source_review_output_changed')
        batch['outputs']=outputs
        record['source_operation']=result.get('operation_id') or (result.get('receipt') or {}).get('operation_id')
        if not record['source_operation'] and result.get('receipt_path'):
            receipt=json.loads((runner.root/result['receipt_path']).read_text())
            record['source_operation']=receipt.get('operation_id')
        runner._set_step(record,'refresh','complete');runner._set_step(record,'review','pending')
        outcome('fetched','awaiting_factual_review')
        return runner._set_status(record,'delivered',reason='Source collected on proposal; factual review and incorporation remain pending')
    except Exception as exc:
        try:outcome('blocked',str(exc))
        except Exception:pass  # Revoked authority never permits another write.
        return runner._set_status(record,'cancelled' if record['job_id'] in runner._cancelled else 'failed',reason=str(exc))
    finally:
        runner._source_review_authorities.pop(record['job_id'],None)
