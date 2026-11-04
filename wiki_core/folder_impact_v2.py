"""One explicitly reported v2 source-consumer re-evaluation; never writes."""
from __future__ import annotations

import re
from pathlib import Path

from wiki_core.context_policy import ContextPolicy, PolicyError, _git, safe_path
from wiki_core.repo_read import contains_access_secrets
from wiki_core.folder_integration_v2 import _rebuild
from wiki_core.folder_policy_v2 import FORMAT, _at_revision
from wiki_core.folder_declarations_v2 import authorized_index, authorized_instruction_chain, preauthorize_index
from wiki_core.repository_reader import RepositoryReader
from wiki_core.folder_auxiliary_v2 import qualify_auxiliary


class FolderImpactError(ValueError):
    pass


def _current_packet_authority(policy, packet, folder, context):
    """Check every item before historical replay can open any body."""
    rows = packet.get('inputs')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise FolderImpactError('invalid v2 inputs')
    preauthorize_index(policy, folder, packet['index_path'])
    reader = RepositoryReader(policy._binding[0], policy.policy_revision)
    chain = authorized_instruction_chain(policy, reader, folder, max_bytes=packet['max_bytes'],
                                         start_folder=packet.get('start_folder'))
    index = authorized_index(policy, folder, packet['index_path'], chain)
    expected = []; seen = set()
    for entry in chain:
        expected.append(('instruction', entry['path'])); seen.add(entry['path'])
        for ref in entry['declarations']['mandatory']:
            if ref not in seen:
                expected.append(('mandatory', ref)); seen.add(ref)
    expected.append(('index', index))
    actual = [(row.get('kind'), row.get('path')) for row in rows if row.get('kind') in ('instruction', 'mandatory', 'index')]
    if actual != expected:
        raise FolderImpactError('current instruction chain or index changed')
    if sum(reader.blob_size(path) for path in {path for _, path in expected}) > packet['max_bytes']:
        raise FolderImpactError('current mandatory content exceeds byte budget')
    from wiki_core.context_policy import within
    for row in rows:
        kind = row.get('kind'); path = safe_path(row.get('path'))
        if any(within(path, scope) for scope in policy.effective[context]['deny']['read']):
            raise FolderImpactError('current input authority unavailable')
        if kind in ('instruction', 'mandatory', 'index'):
            continue
        if kind != 'evidence' or policy.connection(row['producer_context'], context, path, row['use'], row['classification'],
                section=row.get('section'), field=row.get('field')) != 'approved':
            raise FolderImpactError('current input authority unavailable')
    # Normative and index content must remain current before replaying old
    # bodies. A changed rule requires explicit requalification.
    for row in rows:
        if row['kind'] not in ('instruction', 'mandatory', 'index'):
            continue
        item = reader.read(row['path'], section=row.get('section'))
        if contains_access_secrets(item['text']) or item['content_digest'] != row['sha256']:
            raise FolderImpactError('current instruction or index changed')


def assess_folder_source_v2(root, policy, *, packet, result, target, source, section=None, field=None):
    """Compare a reported exact source selection to the current approved tree.

    Caller-provided result is a report, not independent execution proof. This
    does not discover consumers, update content, migrate v1 receipts, or prove
    complete propagation. Current authority is checked before source reads.
    """
    if getattr(policy, 'format_version', None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise FolderImpactError('bound v2 policy required')
    policy = policy.fresh()
    if not isinstance(packet, dict) or packet.get('schema_version') != 'wiki.folder-task-context/v2':
        raise FolderImpactError('v2 packet required; v1 packets need explicit migration')
    if contains_access_secrets(packet):
        raise FolderImpactError('secret detected in packet')
    required = {'schema_version', 'status', 'task_id', 'context_id', 'packet_digest', 'observed', 'changes'}
    if not isinstance(result, dict) or set(result) != required or result.get('schema_version') != 'wiki.folder-task-result/v2':
        raise FolderImpactError('v2 result required; v1 results need explicit migration')
    if contains_access_secrets(result):
        raise FolderImpactError('secret detected in result')
    try:
        target = safe_path(target); source = safe_path(source)
        if target == source or (section is not None and field is not None):
            raise FolderImpactError('invalid source or target selection')
        folder = packet['context_folder']; context = policy.folder_ids[folder]
        if packet['context_id'] != context or packet['output'] != target:
            raise FolderImpactError('packet target or context differs')
        if packet.get('start_folder') is not None:
            preauthorize_index(policy, folder, packet['index_path'])
            if ContextPolicy.owner_of(policy, target) != context or not policy.permits(context, 'read', target):
                raise FolderImpactError('consumer is outside authorized context')
            reader = RepositoryReader(root, policy.policy_revision)
            policy = qualify_auxiliary(policy, reader, folder, packet['start_folder'], max_bytes=packet['max_bytes'])
        if policy.owner_of(target) != context or not policy.permits(context, 'read', target):
            raise FolderImpactError('consumer is outside authorized context')
        _current_packet_authority(policy, packet, folder, context)
        rows = [row for row in packet['inputs'] if row.get('kind') == 'evidence'
                and row.get('path') == source and row.get('section') == section and row.get('field') == field]
        if len(rows) != 1:
            raise FolderImpactError('exact v2 source selection required')
        row = rows[0]
        if policy.connection(row['producer_context'], context, source, row['use'], row['classification'],
                             section=section, field=field) != 'approved':
            raise FolderImpactError('current source authority unavailable')
        old_sha = packet['policy_revision']
        if not isinstance(old_sha, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', old_sha):
            raise FolderImpactError('fixed prior policy revision required')
        _git(root, 'merge-base', '--is-ancestor', old_sha, policy.policy_revision)
        old = _at_revision(Path(root), old_sha, policy.controls_path)
        # Historical proof is limited to an ancestor of the current approved ref.
        old._binding = (str(Path(root).resolve()), old_sha, policy.controls_path)
        _rebuild(root, old, packet)
        if result['status'] != 'completed' or any(result[k] != packet[k] for k in ('task_id', 'context_id', 'packet_digest')):
            raise FolderImpactError('result does not match packet')
        observed = [{'path': item['path'], 'kind': item['kind'], 'revision': item['revision'], 'sha256': item['sha256'],
                     'section': item.get('section'), 'field': item.get('field')} for item in packet['inputs']]
        if result['observed'] != observed or not isinstance(result['changes'], list) or not any(
                isinstance(c, dict) and c.get('path') == target and c.get('action') in ('created', 'modified') for c in result['changes']):
            raise FolderImpactError('reported consumption or output unavailable')
        current = RepositoryReader(root, policy.policy_revision)
        consumer = current.read(target)
        if contains_access_secrets(consumer['text']):
            raise FolderImpactError('secret detected in consumer')
        try:
            latest = current.read(source, section=section, field=field)
        except ValueError:
            latest = None
        if latest and contains_access_secrets(latest['text']):
            raise FolderImpactError('secret detected in source')
        if latest and latest['content_digest'] == row['sha256']:
            policy.fresh()
            # Identical bytes do not establish that the claimed output was
            # integrated or that the reported read occurred. Keep the item open.
            return {'schema_version': 'wiki.folder-impact/v2', 'state': 'verification_pending',
                    'candidates': [{'source': source, 'target': target, 'section': section, 'field': field,
                                    'consumed_revision': row['revision'], 'current_revision': policy.policy_revision,
                                    'before_digest': row['sha256'], 'after_digest': latest['content_digest'],
                                    'target_digest': consumer['content_sha256'], 'state': 'verification_pending',
                                    'source_state': 'unchanged', 'interpretation': 'independent',
                                    'verification': 'reported_not_independently_verified'}],
                    'policy_revision': policy.policy_revision, 'coverage': 'one_explicit_reported_consumption_only'}
        candidate = {'source': source, 'target': target, 'section': section, 'field': field,
                     'consumed_revision': row['revision'], 'current_revision': policy.policy_revision,
                     'before_digest': row['sha256'], 'after_digest': latest['content_digest'] if latest else None,
                     'target_digest': consumer['content_sha256'],
                     'state': 'review_pending' if latest else 'blocked_missing_source',
                     'interpretation': 'independent', 'verification': 'reported_not_independently_verified'}
        policy.fresh()
        if contains_access_secrets(candidate):
            raise FolderImpactError('secret detected in impact metadata')
        return {'schema_version': 'wiki.folder-impact/v2', 'state': candidate['state'], 'candidates': [candidate],
                'policy_revision': policy.policy_revision, 'coverage': 'one_explicit_reported_consumption_only'}
    except (PolicyError, KeyError, TypeError, AttributeError) as exc:
        raise FolderImpactError('v2 source or authority unavailable') from exc
