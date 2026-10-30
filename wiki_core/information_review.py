"""Information obligations projected into the existing source/stream queue.

No provider or model is invoked while planning or enqueueing. Executors use the
existing source adapters and job stream; these functions grant no capability.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from wiki_core.paths import WikiPaths
from wiki_core.source_state import merge_review_requests, read_state, update_state


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()


def project_review_work(report: dict, sources: list[dict], *, include_on_demand: bool=False) -> dict:
    """Resolve only declared source-stream targets; never guess a data source."""
    if report.get('schema_version') != 'wiki_information_impact.v1':
        raise ValueError('source_review_requires_use_scoped_report')
    by_target=defaultdict(list)
    for source in sources:
        if not source.get('recipe_ok'):continue
        for stream in source.get('streams',[]):
            if stream.get('selected',True):
                for target in stream.get('target_pages',[]):
                    by_target[target].append((source,stream))
    groups={};unresolved=[];deferred=[]
    for row in report.get('pending_reviews',[]):
        if row['priority']=='on_demand' and not include_on_demand:
            deferred.append(row['path'])  # Preserve complete queue projection; defer execution only.
        matches=by_target.get(row['seed'] if row.get('reason')=='current_information_unusable' else row['path'],[])
        if not matches:
            unresolved.append({'consumer':row['path'],'fields':row['fields'],
                               'reason':'source_stream_scope_unresolved','priority':row['priority']})
        for source,stream in matches:
            key=(source['source_id'],stream['id'])
            group=groups.setdefault(key,{'source_id':key[0],'stream_id':key[1],
                'source_path':source['path'],'config_ref':source.get('config_ref',''),'input_paths':[],'requests':[]})
            group['input_paths']=sorted(set(group['input_paths']) | {row['path'],row['seed']})
            condition=digest({'consumer':row['path'],'fields':row['fields'],
                'inputs':{p:report.get('input_sha256',{}).get(p) for p in
                    {row['path'],row['seed']}},
                'causes':row.get('causes',[])})
            request={'scope':stream['id'],'fields':sorted(set(row['fields'])),
                'consumer':row['path'],'condition':condition,'priority':row['priority']}
            if request not in group['requests']:group['requests'].append(request)
    return {'schema_version':'wiki_information_review_plan.v1',
            'head':report.get('head_sha'),'base':report.get('base_sha'),
            'managed_sources':sorted(s['source_id'] for s in sources if s.get('recipe_ok')),
            'groups':[groups[k] for k in sorted(groups)],'unresolved':unresolved,
            'on_demand':sorted(set(deferred)), 'provider_calls':0,'model_calls':0}


def enqueue_review_work(root: Path, config, plan: dict) -> dict:
    """Persist a complete source/stream projection without changing cursors/dates."""
    from wiki_core.action_transition import _assert_no_secrets
    _assert_no_secrets(json.dumps(plan,default=str))
    paths=WikiPaths(root,config);by_source=defaultdict(list)
    for group in plan['groups']:by_source[group['source_id']].append(group)
    affected=[]
    for source_id in plan.get('managed_sources', sorted(by_source)):
        groups=by_source[source_id]
        def merge(state):
            targets={g['stream_id']:g['requests'] for g in groups}
            stream_ids=set(targets) | {sid for sid,s in state.get('streams',{}).items() if s.get('review_requests')}
            for stream_id in sorted(stream_ids):
                state=merge_review_requests(state,stream_id,targets.get(stream_id,[]))
            return state
        before=read_state(paths.source_state,source_id)
        # An empty source projection without prior obligations needs no file.
        if not groups and not any(s.get('review_requests') for s in before.get('streams',{}).values()):continue
        after=update_state(paths.source_state,source_id,merge)
        if before!=after:affected.append(source_id)
    return {'source_ids':affected,'groups':len(plan['groups']),
            'unresolved':plan['unresolved'],'provider_calls':0,'model_calls':0}
