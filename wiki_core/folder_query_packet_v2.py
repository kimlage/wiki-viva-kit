"""Explicit current-revision v2 query envelope and conservative preflight.

Historical v2 query replay, impact, v1 receipt migration and read attestation
remain unavailable. A caller-trust host must enforce actual access separately.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from wiki_core.context_policy import _git, revision, safe_path, within
from wiki_core.folder_integration_v2 import FolderIntegrationError, preflight_folder_v2
from wiki_core.folder_policy_v2 import FORMAT
from wiki_core.folder_query_v2 import FolderQueryError, select_folder_query_v2
from wiki_core.repo_read import contains_access_secrets


class FolderQueryPacketError(ValueError):
    pass


def build_folder_query_packet_v2(root, policy, *, base_packet, queries):
    """Build an envelope with a reproduced v2 base and one to eight queries."""
    if getattr(policy,'format_version',None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise FolderQueryPacketError('bound v2 policy required')
    policy = policy.fresh()
    if not isinstance(queries,list) or not 1 <= len(queries) <= 8:
        raise FolderQueryPacketError('one to eight v2 queries required')
    if not isinstance(base_packet,dict) or base_packet.get('schema_version') != 'wiki.folder-task-context/v2':
        raise FolderQueryPacketError('v2 base packet required')
    if base_packet.get('content_revision') != policy.policy_revision:
        raise FolderQueryPacketError('query base must use the current approved revision')
    max_bytes=base_packet.get('max_bytes')
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1_000_000:
        raise FolderQueryPacketError('invalid query packet byte limit')
    from wiki_core.context_selection import normalize_query
    if contains_access_secrets(queries):
        raise FolderQueryPacketError('secret detected in query request')
    try:
        normalized = [normalize_query(request) for request in queries]
    except ValueError as exc:
        raise FolderQueryPacketError('invalid v2 query request') from exc
    if sum(item['query']['max_scan_bytes'] for item in normalized) > 2_000_000:
        raise FolderQueryPacketError('combined query scan limit exceeded')
    results=[]; identities=set()
    for request in normalized:
        try:
            query=select_folder_query_v2(root,policy,packet=base_packet,content_revision=policy.policy_revision,
                                         request=request,max_return_bytes=max_bytes)
        except ValueError as exc:
            raise FolderQueryPacketError('v2 query selection unavailable') from exc
        key=query['receipt']['query_id']
        if key in identities:
            raise FolderQueryPacketError('duplicate v2 query')
        identities.add(key); results.append(query)
    envelope={'schema_version':'wiki.folder-query-task-context/v2','base_packet':base_packet,
              'queries':results,'max_bytes':max_bytes,'bytes_used':0,
              'limitations':['Current approved revision only; no historical query requalification or impact',
                             'Read reports do not prove execution; no ACL or merge approval']}
    if contains_access_secrets(envelope):
        raise FolderQueryPacketError('secret detected in query packet')
    envelope['packet_digest']='0'*64
    from wiki_core.context_selection import digest
    while True:
        length=len(json.dumps(envelope,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8'))
        if envelope['bytes_used']==length: break
        envelope['bytes_used']=length
    if envelope['bytes_used'] > max_bytes:
        raise FolderQueryPacketError('complete query packet exceeds byte budget')
    envelope['packet_digest']=digest({k:v for k,v in envelope.items() if k!='packet_digest'})
    policy.fresh()
    return envelope


def _query_observations(envelope):
    rows=[]
    for item in envelope['queries']:
        qid=item['receipt']['query_id']
        for source in item['selected']:
            rows.append({'kind':'query_evidence','path':source['path'],'revision':source['revision'],
                         'sha256':source['sha256'],'section':source['section'],'field':source['field'],'query_id':qid})
    return rows


def preflight_folder_query_v2(root, policy, *, base, head, branch, packet, result,
                              binding=None, source_request=None, requalify_source=False):
    """Preflight only if the proposal leaves every selected query scope intact."""
    if getattr(policy,'format_version',None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise FolderQueryPacketError('bound v2 policy required')
    policy=policy.fresh()
    if not isinstance(packet,dict) or packet.get('schema_version') != 'wiki.folder-query-task-context/v2':
        raise FolderQueryPacketError('v2 query packet required; v1 receipts need explicit migration')
    try:
        base_packet = packet['base_packet']
        if not isinstance(base_packet, dict):
            raise FolderQueryPacketError('v2 base packet required')
        if base_packet.get('ingestion_binding') is not None or source_request is not None:
            from wiki_core.folder_coordination_v2 import _bound_policy
            _bound_policy(root, binding, base_packet.get('context_folder'), policy.policy_revision)
        queries=packet['queries']
        if not isinstance(queries,list): raise FolderQueryPacketError('invalid v2 query packet')
        requests=[item['receipt']['request'] for item in queries]
        rebuilt=build_folder_query_packet_v2(root,policy,base_packet=packet['base_packet'],queries=requests)
        if rebuilt != packet:
            raise FolderQueryPacketError('v2 query packet cannot be reproduced')
        required={'schema_version','status','task_id','context_id','packet_digest','observed','observed_queries','changes'}
        if (not isinstance(result,dict) or set(result)!=required
                or result.get('schema_version')!='wiki.folder-query-task-result/v2'):
            raise FolderQueryPacketError('v2 query result required; v1 receipts need explicit migration')
        if contains_access_secrets(result): raise FolderQueryPacketError('secret detected in query result')
        base_packet=packet['base_packet']
        if (result['status']!='completed' or result['packet_digest']!=packet['packet_digest']
                or result['task_id']!=base_packet['task_id'] or result['context_id']!=base_packet['context_id']):
            raise FolderQueryPacketError('query result does not match packet')
        base_observed=[{'path':r['path'],'kind':r['kind'],'revision':r['revision'],'sha256':r['sha256'],
                        'section':r.get('section'),'field':r.get('field')} for r in base_packet['inputs']]
        if result['observed'] != base_observed + _query_observations(packet):
            raise FolderQueryPacketError('all query inputs require exact reported reads')
        if result['observed_queries'] != [item['receipt']['query_id'] for item in queries]:
            raise FolderQueryPacketError('all v2 queries require exact reported coverage')
        if not all(isinstance(value,str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',value) for value in (base,head)):
            raise FolderQueryPacketError('fixed base and head required')
        base_sha=revision(root,base); head_sha=revision(root,head)
        if base_sha != policy.policy_revision:
            raise FolderQueryPacketError('approved base moved')
        if not isinstance(branch,str) or not re.fullmatch(r'wiki/[A-Za-z0-9][A-Za-z0-9._-]*',branch) or '..' in branch or branch.endswith('.'):
            raise FolderQueryPacketError('invalid proposal branch')
        branch_sha=_git(root,'rev-parse','--verify','refs/heads/'+branch+'^{commit}').decode().strip()
        if branch_sha != head_sha:
            raise FolderQueryPacketError('proposal branch moved')
        _git(root,'merge-base','--is-ancestor',base_sha,head_sha)
        changed=_git(root,'diff','--no-ext-diff','--no-textconv','--no-renames','--name-only','-z',base_sha,head_sha).split(b'\0')
        paths=[safe_path(raw.decode('utf-8')) for raw in changed if raw]
        for item in queries:
            scope=item['receipt']['request']['query']['scope']; anchor=item['receipt']['index_path']
            if any(path == anchor or within(path,scope) for path in paths):
                raise FolderQueryPacketError('proposal changes query scope; independent requalification required')
        base_result={'schema_version':'wiki.folder-task-result/v2','status':'completed',
                     'task_id':base_packet['task_id'],'context_id':base_packet['context_id'],
                     'packet_digest':base_packet['packet_digest'],'observed':base_observed,'changes':result['changes']}
        if base_packet.get('ingestion_binding') is not None or source_request is not None:
            from wiki_core.folder_coordination_v2 import prepare_folder_preflight
            outcome = prepare_folder_preflight(root, binding, {
                'folder': base_packet['context_folder'], 'approved_revision': policy.policy_revision,
                'base': base_sha, 'head': head_sha, 'branch': branch,
                'packet': base_packet, 'result': base_result,
                'source_request': source_request, 'query_packet':packet, 'query_result':result,
                'requalify_source':requalify_source})['preflight']
        else:
            outcome=preflight_folder_v2(root,policy,base=base_sha,head=head_sha,branch=branch,
                                        packet=base_packet,result=base_result,
                                        query_packet=packet, query_result=result, requalify_source=requalify_source)
        policy.fresh()
        return {'schema_version':'wiki.folder-query-preflight/v2','state':'independent_review_required',
                'base':base_sha,'head':head_sha,'branch':branch,'context_id':base_packet['context_id'],
                'packet_digest':packet['packet_digest'],'changes':outcome['changes'],
                **{key:outcome[key] for key in ('requirements_handling', 'capture_handling', 'modified_ingestion_bodies', 'prior_ingestion_provenance',
                                                  'repository_handling') if key in outcome},
                'query_coverage':'reported_not_independently_verified','review':'not_performed',
                'merge':'not_performed','enforcement_claim':'none'}
    except (KeyError,TypeError,AttributeError,UnicodeError) as exc:
        raise FolderQueryPacketError('v2 query preflight unavailable') from exc
    except (FolderIntegrationError,FolderQueryError) as exc:
        raise FolderQueryPacketError('v2 query preflight unavailable') from exc
    except ValueError as exc:
        if isinstance(exc,FolderQueryPacketError): raise
        raise FolderQueryPacketError('v2 query preflight unavailable') from exc
