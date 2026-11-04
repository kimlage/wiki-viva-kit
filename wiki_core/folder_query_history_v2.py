"""Explicit, narrow v2 query replay; read reports are not execution proof.

This internal entry point returns an open review candidate and never migrates a
v1 receipt. The caller must independently enforce actual host access.
"""
from __future__ import annotations

import re
from pathlib import Path

from wiki_core.context_policy import _git, safe_path, within
from wiki_core.context_selection import normalize_query
from wiki_core.folder_impact_v2 import _current_packet_authority, _preauthorize_historical_replay
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import FORMAT, _at_revision
from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2, _query_observations
from wiki_core.folder_query_v2 import _scope_authorized
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repository_reader import RepositoryReader


class FolderQueryHistoryError(ValueError):
    pass


def assess_folder_query_history_v2(root, policy, *, packet, result, integrated_revision, query_id=None):
    """Reproduce a full v2 envelope and compare one selected query at the approved tip.

    Limited to a whole index, up to eight queries and no auxiliary folders. Modifications
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
        if (not isinstance(queries, list) or not 1 <= len(queries) <= 8 or base.get('index_section') is not None
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
        entries = [normalize_query(row['receipt']['request']) for row in queries]
        ids = [row['receipt']['query_id'] for row in queries]
        if query_id is None and len(ids) == 1:
            query_id = ids[0]
        if (not isinstance(query_id, str) or not re.fullmatch(r'[0-9a-f]{64}', query_id)
                or ids.count(query_id) != 1):
            raise FolderQueryHistoryError('one explicit query id required')
        selected = ids.index(query_id)
        entry = entries[selected]
        if any(item['target'] != index for item in entries) or base['context_id'] != context:
            raise FolderQueryHistoryError('query anchor or owner changed')
        if target == index or any(within(target, item['query']['scope']) for item in entries):
            raise FolderQueryHistoryError('output intersects query scope')
        # Establish current authority for the complete universe and output before
        # opening any historical instruction, index, source or output body.
        for item in entries:
            _scope_authorized(policy, folder, item['query']['scope'], index)
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
        for item in entries:
            _scope_authorized(historical, folder, item['query']['scope'], index)
        _preauthorize_historical_replay(root, policy, base, folder, context, historical)
        # Only the internally bound ancestor is replayed. Its objects are never
        # returned, and the trusted current ref is checked again before return.
        rebuilt = build_folder_query_packet_v2(root, historical, base_packet=base, queries=entries)
        from wiki_core.folder_query_requirements_v2 import same_json
        if not same_json(rebuilt, packet):
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
                or result['observed_queries'] != ids
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
        output_binding = 'matching_integrated_absence_only' if action == 'deleted' else 'matching_integrated_bytes_only'
        if action == 'deleted':
            if target in integrated_reader.paths or target in current_reader.paths:
                raise FolderQueryHistoryError('integrated deletion unavailable')
        else:
            if target not in integrated_reader.paths or target not in current_reader.paths:
                raise FolderQueryHistoryError('integrated output unavailable')
            integrated_output = integrated_reader.read(target)
            current_output = current_reader.read(target)
            if contains_access_secrets(integrated_output['text']) or contains_access_secrets(current_output['text']):
                raise FolderQueryHistoryError('integrated output unavailable')
            if action == 'modified' and old_reader.read(target)['content_sha256'] == integrated_output['content_sha256']:
                raise FolderQueryHistoryError('integrated modification unavailable')
            if integrated_output['content_sha256'] != current_output['content_sha256']:
                # An independently updated claim can preserve this reported
                # query. Compare its explicit declaration, not just whole-file
                # bytes; neither match proves review or semantic correctness.
                from wiki_core.context_selection import _metadata
                from wiki_core.folder_query_requirements_v2 import query_requirements, same_json
                from wiki_core.information_relations import information_requirements
                preserved = True
                try:
                    declarations = []
                    for document, reader in ((integrated_output, integrated_reader), (current_output, current_reader)):
                        parsed = information_requirements(_metadata(document),
                            lambda ref: [ref] if isinstance(ref, str) and ref in reader.paths else [])
                        chosen = [row for row in parsed if row.get('query_contract') == 'wiki.folder-query-receipt/v2'
                                  and row.get('query_id') == query_id]
                        if len(chosen) != 1 or not same_json(chosen, query_requirements([queries[selected]], chosen[0]['max_age_days'])):
                            raise ValueError('query declaration unavailable')
                        declarations.append(chosen[0])
                    preserved = same_json(*declarations)
                except (ValueError, KeyError, TypeError, AttributeError):
                    preserved = False
                output_binding = ('query_declaration_preserved_output_changed' if preserved
                                  else 'query_declaration_unverified_output_changed')
                if not preserved:
                    policy.fresh()
                    return {'schema_version':'wiki.folder-query-impact/v2', 'state':'review_pending',
                            'query_state':'unknown', 'query_id':query_id, 'target':target,
                            'consumed_revision':old_sha, 'integrated_revision':integrated_revision,
                            'current_revision':policy.policy_revision, 'output_binding':output_binding,
                            'read_verification':'reported_not_independently_verified',
                            'review':'not_performed', 'enforcement_claim':'none'}
        current_base = build_folder_packet_v2(root, policy, folder, base['max_bytes'],
                        content_revision=policy.policy_revision, index_path=index, task_id=base['task_id'],
                        goal=base['goal'], output=target, integrator=base['integrator'])
        current_packet = build_folder_query_packet_v2(root, policy, base_packet=current_base, queries=[entry])
        before = queries[selected]['receipt']; after = current_packet['queries'][0]['receipt']
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
                'output_binding': output_binding, 'enforcement_claim': 'none'}
    except (KeyError, TypeError, AttributeError) as exc:
        raise FolderQueryHistoryError('historical query authority or content unavailable') from exc
    except ValueError as exc:
        if isinstance(exc, FolderQueryHistoryError):
            raise
        raise FolderQueryHistoryError('historical query authority or content unavailable') from exc
