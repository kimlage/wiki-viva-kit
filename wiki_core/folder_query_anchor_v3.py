"""Experimental single-owner collection query with a separate context index.

No v1/v2 receipt is reused. This current-revision prototype is opt-in, does
not perform historical migration, and does not claim native ACL enforcement.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from wiki_core.context_policy import _git, revision, safe_path, within
from wiki_core.context_selection import _metadata, digest, normalize_query
from wiki_core.folder_declarations_v2 import preauthorize_index
from wiki_core.folder_integration_v2 import _rebuild, preflight_folder_v2
from wiki_core.folder_policy_v2 import FORMAT
from wiki_core.folder_query_v2 import _preauthorize_packet_evidence, _scope_authorized
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repository_reader import RepositoryReader


class FolderAnchorQueryError(ValueError):
    pass


def _json_size(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'))


def build_anchor_query_packet_v3(root, policy, *, base_packet, request):
    """Build one bounded query; index and collection anchor are explicit.

    All current authority checks precede any query or packet body. A v2 base
    packet is independently rebuilt; it is not itself a query receipt. History,
    auxiliary starts, cross-owner queries and v1/v2 receipt migration are absent.
    """
    if getattr(policy, 'format_version', None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise FolderAnchorQueryError('bound v2 folder policy required')
    policy = policy.fresh()
    if not isinstance(base_packet, dict) or base_packet.get('schema_version') != 'wiki.folder-task-context/v2':
        raise FolderAnchorQueryError('v2 base packet required; no receipt migration')
    if contains_access_secrets(request) or contains_access_secrets(base_packet):
        raise FolderAnchorQueryError('secret detected in query input')
    try:
        if (not isinstance(base_packet.get('inputs'), list)
                or any(not isinstance(row, dict) for row in base_packet['inputs'])
                or base_packet.get('index_section') is not None or base_packet.get('start_folder') is not None):
            raise FolderAnchorQueryError('whole index and non-auxiliary packet required')
        max_bytes = base_packet['max_bytes']
        if type(max_bytes) is not int or not 1 <= max_bytes <= 1_000_000:
            raise FolderAnchorQueryError('invalid packet byte limit')
        entry = normalize_query(request)
        folder = base_packet['context_folder']; index = base_packet['index_path']
        anchor = entry['target']; q = entry['query']; scope = q['scope']
        context = policy.folder_ids[folder]
        preauthorize_index(policy, folder, index)
        _scope_authorized(policy, folder, scope, index)
        if policy.owner_of(anchor) != context or not policy.permits(context, 'read', anchor):
            raise FolderAnchorQueryError('collection anchor authority unavailable')
        _preauthorize_packet_evidence(policy, base_packet, folder)
        # From here onward every intended body has a current authority check.
        _rebuild(root, policy, base_packet)
        reader = RepositoryReader(root, policy.policy_revision)
        if reader.invalid_paths or anchor not in reader.paths:
            raise FolderAnchorQueryError('query metadata or anchor unavailable')
        if any(within(path, scope) for path in reader.unsupported_paths):
            raise FolderAnchorQueryError('unsupported query scope')
        candidates = [p for p in reader.paths if p != anchor and p.endswith('.md') and within(p, scope)
                      and policy.owner_of(p) == context and policy.permits(context, 'read', p)]
        if len(candidates) > q['max_enumerated']:
            raise FolderAnchorQueryError('query enumeration limit exceeded')
        scanned = 0
        def read(path, *, section=None, field=None):
            nonlocal scanned
            scanned += reader.blob_size(path)
            if scanned > q['max_scan_bytes']:
                raise FolderAnchorQueryError('query scan byte limit exceeded')
            item = reader.read(path, section=section, field=field)
            if contains_access_secrets(item['text']):
                raise FolderAnchorQueryError('secret detected in query content')
            return item
        anchor_item = read(anchor)
        meta = _metadata(anchor_item); anchor_id = meta.get('page_id')
        if (meta.get('page_type') not in ('context_hub', 'ontology_index', 'source_catalog', 'root_entity')
                or not isinstance(anchor_id, str) or not anchor_id.strip() or any(ord(c) < 32 for c in anchor_id)):
            raise FolderAnchorQueryError('anchor collection contract unavailable')
        members = []; selected = []; identities = {anchor_id}
        for path in candidates:
            item = read(path); fm = _metadata(item); page_id = fm.get('page_id')
            if page_id is None: continue
            if not isinstance(page_id, str) or not page_id.strip() or any(ord(c) < 32 for c in page_id) or page_id in identities:
                raise FolderAnchorQueryError('query page identity missing or ambiguous')
            identities.add(page_id)
            def matches(key, value):
                options = value if isinstance(value, list) else [value]
                return any(type(fm.get(key)) is type(v) and fm.get(key) == v for v in options)
            if not all(matches(key, value) for key, value in q['filters'].items()): continue
            if len(members) >= q['max_matches']:
                raise FolderAnchorQueryError('query match limit exceeded')
            item = reader.read(path, section=q.get('section'), field=q.get('field'))
            if contains_access_secrets(item['text']):
                raise FolderAnchorQueryError('secret detected in query content')
            members.append({'ref': path, 'page_id': page_id})
            selected.append({'path': path, 'revision': reader.revision, 'section': q.get('section'),
                             'field': q.get('field'), 'sha256': item['content_digest'],
                             'document_sha256': item['content_sha256'], 'text': item['text']})
        query_id = digest({'schema_version':'wiki.folder-query-identity/v3','context_id':context,'request':entry})
        authority = digest({'schema_version':'wiki.folder-query-authority/v3','context_id':context,
                            'folder':folder,'scope':scope,'index':index,'anchor':anchor,
                            'scope_read':'authorized','anchor_read':'authorized'})
        receipt = {'schema_version':'wiki.folder-query-receipt/v3','query_id':query_id,'request':entry,
                   'context_id':context,'folder':folder,'index_path':index,'anchor_path':anchor,
                   'content_revision':reader.revision,'policy_revision':policy.policy_revision,
                   'packet_digest':base_packet['packet_digest'],'authority_digest':authority,'members':members,
                   'members_digest':digest({'schema_version':'wiki.folder-query-members/v3','query_id':query_id,'members':members}),
                   'selected_digest':digest({'schema_version':'wiki.folder-query-selection/v3','query_id':query_id,
                       'anchor':anchor_item['content_digest'],
                       'selected':[{'path':item['path'],'sha256':item['sha256']} for item in selected]}),
                   'coverage':'complete_only_within_authorized_single_owner_scope','enumerated':len(candidates)}
        receipt['receipt_digest'] = digest(receipt)
        result = {'schema_version':'wiki.folder-anchor-query-task-context/v3','base_packet':base_packet,
                  'query':{'receipt':receipt, 'anchor':{'path':anchor, 'revision':reader.revision,
                      'sha256':anchor_item['content_digest'], 'text':anchor_item['text']}, 'selected':selected},
                  'max_bytes':max_bytes, 'bytes_used':0,
                  'limitations':['Current approved revision only; no historic migration or requalification',
                                 'Read reports are not execution proof; no ACL or merge approval']}
        if contains_access_secrets(result):
            raise FolderAnchorQueryError('secret detected in query packet')
        result['packet_digest'] = '0' * 64
        while True:
            length = _json_size(result)
            if result['bytes_used'] == length: break
            result['bytes_used'] = length
        if result['bytes_used'] > max_bytes:
            raise FolderAnchorQueryError('query packet exceeds byte limit')
        result['packet_digest'] = digest({k:v for k,v in result.items() if k != 'packet_digest'})
        policy.fresh()
        return result
    except (KeyError, TypeError, AttributeError) as exc:
        raise FolderAnchorQueryError('query authority or content unavailable') from exc
    except ValueError as exc:
        if isinstance(exc, FolderAnchorQueryError): raise
        raise FolderAnchorQueryError('query authority or content unavailable') from exc


def _observed(packet):
    base = packet['base_packet']; query = packet['query']; qid = query['receipt']['query_id']
    result = [{'path':r['path'],'kind':r['kind'],'revision':r['revision'],'sha256':r['sha256'],
               'section':r.get('section'),'field':r.get('field')} for r in base['inputs']]
    anchor = query['anchor']
    result.append({'path':anchor['path'],'kind':'query_anchor','revision':anchor['revision'],
                   'sha256':anchor['sha256'],'section':None,'field':None,'query_id':qid})
    result.extend({'path':r['path'],'kind':'query_evidence','revision':r['revision'],'sha256':r['sha256'],
                   'section':r['section'],'field':r['field'],'query_id':qid} for r in query['selected'])
    return result


def preflight_anchor_query_v3(root, policy, *, base, head, branch, packet, result):
    """Verify a reported readset and a narrow proposal; no review or merge."""
    if getattr(policy, 'format_version', None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise FolderAnchorQueryError('bound v2 folder policy required')
    policy = policy.fresh()
    if not isinstance(packet, dict) or packet.get('schema_version') != 'wiki.folder-anchor-query-task-context/v3':
        raise FolderAnchorQueryError('v3 anchor query packet required')
    if contains_access_secrets(packet) or contains_access_secrets(result):
        raise FolderAnchorQueryError('secret detected in query preflight')
    try:
        query = packet['query']; base_packet = packet['base_packet']
        rebuilt = build_anchor_query_packet_v3(root, policy, base_packet=base_packet, request=query['receipt']['request'])
        if packet != rebuilt:
            raise FolderAnchorQueryError('query packet cannot be reproduced')
        required = {'schema_version','status','task_id','context_id','packet_digest','observed','observed_queries','changes'}
        if (not isinstance(result,dict) or set(result) != required
                or result.get('schema_version') != 'wiki.folder-anchor-query-task-result/v3'
                or result['status'] != 'completed' or result['task_id'] != base_packet['task_id']
                or result['context_id'] != base_packet['context_id'] or result['packet_digest'] != packet['packet_digest']
                or result['observed'] != _observed(packet)
                or result['observed_queries'] != [query['receipt']['query_id']]):
            raise FolderAnchorQueryError('query result or reported readset differs')
        if not all(isinstance(v,str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',v) for v in (base,head)):
            raise FolderAnchorQueryError('fixed base and head required')
        base_sha = revision(root,base); head_sha = revision(root,head)
        if base_sha != policy.policy_revision:
            raise FolderAnchorQueryError('approved base moved')
        if not isinstance(branch,str) or not re.fullmatch(r'wiki/[A-Za-z0-9][A-Za-z0-9._-]*',branch) or '..' in branch or branch.endswith('.'):
            raise FolderAnchorQueryError('invalid proposal branch')
        if _git(root,'rev-parse','--verify','refs/heads/'+branch+'^{commit}').decode().strip() != head_sha:
            raise FolderAnchorQueryError('proposal branch moved')
        _git(root,'merge-base','--is-ancestor',base_sha,head_sha)
        changed = _git(root,'diff','--no-ext-diff','--no-textconv','--no-renames','--name-only','-z',base_sha,head_sha).split(b'\0')
        paths = [safe_path(raw.decode('utf-8')) for raw in changed if raw]
        scope = query['receipt']['request']['query']['scope']
        anchor = query['anchor']['path']; index = base_packet['index_path']
        if any(path in (anchor,index) or within(path,scope) for path in paths):
            raise FolderAnchorQueryError('proposal changes query scope or anchor')
        base_result = {'schema_version':'wiki.folder-task-result/v2','status':'completed',
                       'task_id':base_packet['task_id'],'context_id':base_packet['context_id'],
                       'packet_digest':base_packet['packet_digest'],
                       'observed':[{'path':r['path'],'kind':r['kind'],'revision':r['revision'],'sha256':r['sha256'],
                                    'section':r.get('section'),'field':r.get('field')} for r in base_packet['inputs']],
                       'changes':result['changes']}
        outcome = preflight_folder_v2(root,policy,base=base_sha,head=head_sha,branch=branch,
                                      packet=base_packet,result=base_result)
        policy.fresh()
        return {'schema_version':'wiki.folder-anchor-query-preflight/v3','state':'independent_review_required',
                'base':base_sha,'head':head_sha,'branch':branch,'context_id':base_packet['context_id'],
                'packet_digest':packet['packet_digest'],'changes':outcome['changes'],
                'query_coverage':'reported_not_independently_verified','review':'not_performed',
                'merge':'not_performed','enforcement_claim':'none'}
    except (KeyError, TypeError, AttributeError, UnicodeError) as exc:
        raise FolderAnchorQueryError('query preflight unavailable') from exc
    except ValueError as exc:
        if isinstance(exc, FolderAnchorQueryError): raise
        raise FolderAnchorQueryError('query preflight unavailable') from exc
