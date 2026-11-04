"""Explicit, narrow v2 query replay; read reports are not execution proof.

This internal entry point returns an open review candidate and never migrates a
v1 receipt. The caller must independently enforce actual host access.
"""
from __future__ import annotations

import re
from pathlib import Path

from wiki_core.context_policy import _git, safe_path, within
from wiki_core.context_selection import normalize_query
from wiki_core.folder_impact_v2 import _current_packet_authority
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import FORMAT, _at_revision
from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2, _query_observations
from wiki_core.folder_query_v2 import _scope_authorized
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repository_reader import RepositoryReader


class FolderQueryHistoryError(ValueError):
    pass


def assess_folder_query_history_v2(root, policy, *, packet, result, integrated_revision):
    """Reproduce one prior v2 query and compare it at the approved tip.

    Limited to a whole index, one query and no auxiliary folders. Modifications
    and deletions require the complete prior output as authorized evidence.
    This is not proof of a read, review or merge.
    """
    if getattr(policy, 'format_version', None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise FolderQueryHistoryError('bound v2 policy required')
    policy = policy.fresh()
    if not isinstance(packet, dict) or packet.get('schema_version') != 'wiki.folder-query-task-context/v2':
        raise FolderQueryHistoryError('v2 query packet required; v1 migration unavailable')
    if contains_access_secrets(packet) or contains_access_secrets(result):
        raise FolderQueryHistoryError('secret detected in historical query input')
    try:
        base = packet['base_packet']; queries = packet['queries']
        if (not isinstance(queries, list) or len(queries) != 1 or base.get('index_section') is not None
                or base.get('start_folder') is not None or not isinstance(base.get('inputs'), list)
                or any(row.get('kind') not in ('instruction', 'mandatory', 'index', 'evidence') for row in base['inputs'])):
            raise FolderQueryHistoryError('historical query packet outside supported scope')
        old_sha = base['policy_revision']
        if (not isinstance(old_sha, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', old_sha)
                or base['content_revision'] != old_sha or not isinstance(integrated_revision, str)
                or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', integrated_revision)):
            raise FolderQueryHistoryError('fixed historical and output revisions required')
        _git(root, 'merge-base', '--is-ancestor', old_sha, integrated_revision)
        _git(root, 'merge-base', '--is-ancestor', integrated_revision, policy.policy_revision)
        folder = base['context_folder']; context = policy.folder_ids[folder]
        target = safe_path(base['output']); index = base['index_path']
        entry = normalize_query(queries[0]['receipt']['request'])
        if entry['target'] != index or base['context_id'] != context:
            raise FolderQueryHistoryError('query anchor or owner changed')
        scope = entry['query']['scope']
        if target == index or within(target, scope):
            raise FolderQueryHistoryError('output intersects query scope')
        # Establish current authority for the complete universe and output before
        # opening any historical instruction, index, source or output body.
        _scope_authorized(policy, folder, scope, index)
        if (policy.owner_of(target) != context or not policy.permits(context, 'read', target)
                or not policy.permits(context, 'write', target)):
            raise FolderQueryHistoryError('current output authority unavailable')
        _current_packet_authority(policy, base, folder, context)
        historical = _at_revision(Path(root), old_sha, policy.controls_path)
        historical._binding = (str(Path(root).resolve()), old_sha, policy.controls_path)
        integrated = _at_revision(Path(root), integrated_revision, policy.controls_path)
        if (historical.folder_ids.get(folder) != context or integrated.folder_ids.get(folder) != context
                or historical.owner_of(target) != context or integrated.owner_of(target) != context
                or not historical.permits(context, 'read', target) or not integrated.permits(context, 'read', target)
                or not historical.permits(context, 'write', target) or not integrated.permits(context, 'write', target)):
            raise FolderQueryHistoryError('historical output authority unavailable')
        _scope_authorized(historical, folder, scope, index)
        # Only the internally bound ancestor is replayed. Its objects are never
        # returned, and the trusted current ref is checked again before return.
        rebuilt = build_folder_query_packet_v2(root, historical, base_packet=base, queries=[entry])
        if rebuilt != packet:
            raise FolderQueryHistoryError('historical v2 query packet cannot be reproduced')
        required = {'schema_version', 'status', 'task_id', 'context_id', 'packet_digest', 'observed', 'observed_queries', 'changes'}
        if (not isinstance(result, dict) or set(result) != required
                or result.get('schema_version') != 'wiki.folder-query-task-result/v2'
                or result['status'] != 'completed' or result['task_id'] != base['task_id']
                or result['context_id'] != context or result['packet_digest'] != packet['packet_digest']):
            raise FolderQueryHistoryError('reported result does not match packet')
        observed = [{'path': row['path'], 'kind': row['kind'], 'revision': row['revision'], 'sha256': row['sha256'],
                     'section': row.get('section'), 'field': row.get('field')} for row in base['inputs']]
        changes = result['changes']
        if (result['observed'] != observed + _query_observations(packet)
                or result['observed_queries'] != [queries[0]['receipt']['query_id']]
                or not isinstance(changes, list) or len(changes) != 1
                or not isinstance(changes[0], dict) or set(changes[0]) != {'path', 'action'}
                or changes[0]['path'] != target or changes[0]['action'] not in ('created', 'modified', 'deleted')):
            raise FolderQueryHistoryError('reported readset or output outside supported scope')
        action = changes[0]['action']
        if action != 'created' and not any(row.get('kind') == 'evidence' and row.get('path') == target
                and row.get('section') is None and row.get('field') is None
                and row.get('revision') == old_sha for row in base['inputs']):
            raise FolderQueryHistoryError('whole prior output evidence required')
        old_reader = RepositoryReader(root, old_sha)
        integrated_reader = RepositoryReader(root, integrated_revision)
        current_reader = RepositoryReader(root, policy.policy_revision)
        if any(target in reader.unsupported_paths for reader in (old_reader, integrated_reader, current_reader)):
            raise FolderQueryHistoryError('unsupported output object')
        if action == 'created' and target in old_reader.paths:
            raise FolderQueryHistoryError('integrated creation unavailable')
        if action != 'created' and target not in old_reader.paths:
            raise FolderQueryHistoryError('prior output unavailable')
        if action == 'deleted':
            if target in integrated_reader.paths or target in current_reader.paths:
                raise FolderQueryHistoryError('integrated deletion unavailable')
        else:
            if target not in integrated_reader.paths or target not in current_reader.paths:
                raise FolderQueryHistoryError('integrated output unavailable')
            integrated_output = integrated_reader.read(target)
            current_output = current_reader.read(target)
            if (contains_access_secrets(integrated_output['text']) or contains_access_secrets(current_output['text'])
                    or integrated_output['content_sha256'] != current_output['content_sha256']):
                raise FolderQueryHistoryError('integrated output differs or is unavailable')
            if action == 'modified' and old_reader.read(target)['content_sha256'] == integrated_output['content_sha256']:
                raise FolderQueryHistoryError('integrated modification unavailable')
        current_base = build_folder_packet_v2(root, policy, folder, base['max_bytes'],
                        content_revision=policy.policy_revision, index_path=index, task_id=base['task_id'],
                        goal=base['goal'], output=target, integrator=base['integrator'])
        current_packet = build_folder_query_packet_v2(root, policy, base_packet=current_base, queries=[entry])
        before = queries[0]['receipt']; after = current_packet['queries'][0]['receipt']
        if before['query_id'] != after['query_id']:
            raise FolderQueryHistoryError('query identity changed')
        state = 'unchanged' if (before['members_digest'] == after['members_digest']
                                and before['selected_digest'] == after['selected_digest']) else 'changed'
        policy.fresh()
        return {'schema_version': 'wiki.folder-query-impact/v2', 'state': 'review_pending',
                'query_state': state, 'query_id': before['query_id'], 'target': target,
                'consumed_revision': old_sha, 'integrated_revision': integrated_revision,
                'current_revision': policy.policy_revision,
                'before_members_digest': before['members_digest'], 'after_members_digest': after['members_digest'],
                'before_selected_digest': before['selected_digest'], 'after_selected_digest': after['selected_digest'],
                'read_verification': 'reported_not_independently_verified', 'review': 'not_performed',
                'output_binding': ('matching_integrated_absence_only' if action == 'deleted'
                                   else 'matching_integrated_bytes_only'), 'enforcement_claim': 'none'}
    except (KeyError, TypeError, AttributeError) as exc:
        raise FolderQueryHistoryError('historical query authority or content unavailable') from exc
    except ValueError as exc:
        if isinstance(exc, FolderQueryHistoryError):
            raise
        raise FolderQueryHistoryError('historical query authority or content unavailable') from exc
