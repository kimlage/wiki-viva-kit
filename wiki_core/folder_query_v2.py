"""Read-only, owner-scoped v2 query used by folder packet and CLI flows.

The receipt has its own v2 identity/digests and cannot be made from a v1 digest.
No resident service, task execution, read attestation, external source access or
ACL is asserted.
"""
from __future__ import annotations

import json
from pathlib import Path

from wiki_core.context_policy import PolicyError, _git, revision, safe_path, within
from wiki_core.context_selection import _metadata, digest, normalize_query
from wiki_core.folder_declarations_v2 import preauthorize_index
from wiki_core.folder_integration_v2 import _rebuild
from wiki_core.folder_policy_v2 import FORMAT
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repository_reader import RepositoryReader


class FolderQueryError(ValueError):
    pass


def _preauthorize_packet_evidence(policy, packet, folder):
    """Check every input's current authority before replaying any body."""
    if packet.get('start_folder') is not None:
        raise FolderQueryError('query from auxiliary start requires separate qualification')
    context = policy.folder_ids.get(folder)
    if context is None or packet.get('context_id') != context:
        raise FolderQueryError('query packet context unavailable')
    if packet.get('policy_revision') != policy.policy_revision or packet.get('content_revision') != policy.policy_revision:
        raise FolderQueryError('query packet must use the current approved revision')
    for row in packet['inputs']:
        kind = row.get('kind')
        if kind in ('instruction','mandatory','index'):
            continue
        if kind != 'evidence':
            raise FolderQueryError('invalid query packet input')
        path = safe_path(row['path']); producer = row['producer_context']
        if policy.connection(producer,context,path,row['use'],row['classification'],
                             section=row.get('section'),field=row.get('field')) != 'approved':
            raise FolderQueryError('current query packet input authority unavailable')


def _scope_authorized(policy, folder, scope, index):
    context = policy.folder_ids.get(folder)
    if context is None or not within(scope, folder):
        raise FolderQueryError('query scope unavailable')
    if scope != '.' and policy.owner_of(scope) != context:
        raise FolderQueryError('query scope unavailable')
    preauthorize_index(policy, folder, index)
    effective = policy.effective[context]
    if not any(within(scope, item) for item in effective['read']):
        raise FolderQueryError('query scope unavailable')
    if any(within(scope, denied) or within(denied, scope) for denied in effective['deny']['read']):
        raise FolderQueryError('query scope requires narrower authority')
    for node in policy.contexts.values():
        other = node['root']
        if node['id'] != context and within(other, scope):
            raise FolderQueryError('query scope requires narrower authority')
    for ambiguous in policy.unindexed_instruction_folders:
        if within(ambiguous, scope) or within(scope, ambiguous):
            raise FolderQueryError('query scope requires narrower authority')
    return context


def _authority(policy, folder, scope, index, anchor=None):
    context = _scope_authorized(policy, folder, scope, index)
    anchor = index if anchor is None else safe_path(anchor)
    if policy.owner_of(anchor) != context or not policy.permits(context, 'read', anchor):
        raise FolderQueryError('query anchor authority unavailable')
    value = {'schema_version':'wiki.folder-query-authority/v2','context_id':context,
             'folder':folder,'scope':scope,'index':index,'scope_read':'authorized'}
    if anchor != index:
        value.update(anchor=anchor, anchor_read='authorized')
    return digest(value)


def select_folder_query_v2(root, policy, *, packet, content_revision, request, max_return_bytes=1_000_000):
    """Select a bounded single-owner set at the current approved revision.

    A current, reproduced v2 context packet and a whole selected index are
    required. All packet evidence is authorized before replaying any body. The
    current policy must authorize the entire single-owner
    scope; nested owners, denies or ambiguous instruction folders block the query.
    Historical selections remain blocked pending explicit normative requalification.
    The return includes only selected content, and does not assert native loading.
    """
    if getattr(policy,'format_version',None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise FolderQueryError('bound v2 policy required')
    policy = policy.fresh()
    if not isinstance(packet,dict) or packet.get('schema_version') != 'wiki.folder-task-context/v2':
        raise FolderQueryError('v2 packet required; v1 receipts require explicit migration')
    if not isinstance(packet.get('inputs'),list) or any(not isinstance(r,dict) for r in packet['inputs']):
        raise FolderQueryError('invalid query packet input')
    if packet.get('index_section') is not None:
        raise FolderQueryError('query requires a whole authorized index')
    if type(max_return_bytes) is not int or not 1 <= max_return_bytes <= 1_000_000:
        raise FolderQueryError('invalid query return limit')
    if contains_access_secrets(request):
        raise FolderQueryError('secret detected in query')
    try:
        folder = packet['context_folder']; index = packet['index_path']
        entry = normalize_query(request); q = entry['query']; scope = q['scope']; anchor_path = entry['target']
        preauthorize_index(policy,folder,index)
        _preauthorize_packet_evidence(policy,packet,folder)
        current_auth = _authority(policy,folder,scope,index,anchor_path)
        _rebuild(root,policy,packet)
        content_sha = revision(root,content_revision)
        _git(root,'merge-base','--is-ancestor',content_sha,policy.policy_revision)
        if content_sha != policy.policy_revision:
            # Historical index declarations and all applicable normative bodies
            # need independent requalification before old content can be read.
            raise FolderQueryError('historical v2 query requalification unavailable')
        old = policy
        reader = RepositoryReader(root,content_sha)
        if reader.invalid_paths:
            raise FolderQueryError('query tree contains unsupported paths')
        context = policy.folder_ids[folder]
        def allowed(path):
            return (path != anchor_path and path.endswith('.md') and within(path,scope)
                    and policy.owner_of(path) == context and old.owner_of(path) == context
                    and policy.permits(context,'read',path) and old.permits(context,'read',path))
        for path in reader.unsupported_paths:
            if within(path,scope):
                raise FolderQueryError('query scope contains unsupported paths')
        candidates = [path for path in reader.paths if allowed(path)]
        if len(candidates) > q['max_enumerated']:
            raise FolderQueryError('query enumeration limit exceeded')
        scanned = 0
        def read(path, *, section=None, field=None):
            nonlocal scanned
            scanned += reader.blob_size(path)
            if scanned > q['max_scan_bytes']:
                raise FolderQueryError('query scan byte limit exceeded')
            item = reader.read(path,section=section,field=field)
            if contains_access_secrets(item['text']):
                raise FolderQueryError('secret detected in query content')
            return item
        anchor = read(anchor_path)
        anchor_meta = _metadata(anchor)
        if (anchor_meta.get('page_type') not in ('context_hub','ontology_index','source_catalog','root_entity')
                or not isinstance(anchor_meta.get('page_id'),str) or not anchor_meta['page_id'].strip()
                or (anchor_path != index and any(ord(c)<32 for c in anchor_meta['page_id']))):
            raise FolderQueryError('query anchor is not a collection contract')
        members=[]; selected=[]; identities={anchor_meta['page_id']}
        for path in candidates:
            item=read(path); meta=_metadata(item); page_id=meta.get('page_id')
            if page_id is None: continue
            if not isinstance(page_id,str) or not page_id.strip() or any(ord(c)<32 for c in page_id) or page_id in identities:
                raise FolderQueryError('query page identity missing or ambiguous')
            identities.add(page_id)
            def matches(key,value):
                values=value if isinstance(value,list) else [value]
                return any(type(meta.get(key)) is type(v) and meta.get(key)==v for v in values)
            if not all(matches(k,v) for k,v in q['filters'].items()): continue
            if len(members) >= q['max_matches']:
                raise FolderQueryError('query match limit exceeded')
            selection = reader.read(path,section=q.get('section'),field=q.get('field'))
            if contains_access_secrets(selection['text']):
                raise FolderQueryError('secret detected in query content')
            members.append({'ref':path,'page_id':page_id})
            selected.append({'path':path,'revision':content_sha,'section':q.get('section'),'field':q.get('field'),
                             'sha256':selection['content_digest'],'document_sha256':selection['content_sha256'],
                             'text':selection['text']})
        query_id=digest({'schema_version':'wiki.folder-query-identity/v2','context_id':context,'request':entry})
        selection = {'schema_version':'wiki.folder-query-selection/v2','query_id':query_id,
                     'anchor':anchor['content_digest'],
                     'selected':[{'path':r['path'],'sha256':r['sha256']} for r in selected]}
        if anchor_path != index:
            selection['index'] = next(row['sha256'] for row in packet['inputs'] if row['kind'] == 'index' and row['path'] == index)
        receipt={'schema_version':'wiki.folder-query-receipt/v2','query_id':query_id,'request':entry,
                 'context_id':context,'folder':folder,'index_path':index,'content_revision':content_sha,
                 'policy_revision':policy.policy_revision,'packet_digest':packet['packet_digest'],'authority_digest':current_auth,
                 'members':members,'members_digest':digest({'schema_version':'wiki.folder-query-members/v2','query_id':query_id,'members':members}),
                 'selected_digest':digest(selection),
                 'coverage':'complete_only_within_authorized_single_owner_scope','enumerated':len(candidates)}
        receipt['receipt_digest']=digest(receipt)
        out={'schema_version':'wiki.folder-query-result/v2','receipt':receipt,'selected':selected,
             'read_verification':'not_performed','enforcement_claim':'none'}
        if anchor_path != index:
            out['anchor'] = {'path':anchor_path,'revision':content_sha,
                             'sha256':anchor['content_digest'],'text':anchor['text']}
        if contains_access_secrets(out): raise FolderQueryError('secret detected in query result')
        if len(json.dumps(out,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()) > max_return_bytes:
            raise FolderQueryError('query return byte limit exceeded')
        policy.fresh()
        return out
    except (PolicyError, KeyError, TypeError, AttributeError) as exc:
        raise FolderQueryError('query authority or content unavailable') from exc
    except ValueError as exc:
        if isinstance(exc,FolderQueryError): raise
        raise FolderQueryError('query authority or content unavailable') from exc


def revalidate_folder_query_v2(root, policy, *, receipt):
    """Fail closed until historical query and normative authority can be reproduced.

    A caller-provided v2 digest is not proof that a prior selection or execution
    happened. This entry deliberately does not open historic member bodies.
    """
    if getattr(policy,'format_version',None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise FolderQueryError('bound v2 policy required')
    policy.fresh()
    if not isinstance(receipt,dict) or receipt.get('schema_version') != 'wiki.folder-query-receipt/v2':
        raise FolderQueryError('v2 query receipt required; v1 receipts require explicit migration')
    if contains_access_secrets(receipt):
        raise FolderQueryError('secret detected in query receipt')
    raise FolderQueryError('historical v2 query requalification unavailable')
