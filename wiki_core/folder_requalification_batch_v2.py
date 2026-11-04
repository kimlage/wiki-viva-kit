"""Explicit caller-trust coordinator batch for v1 requirements.

This internal helper neither grants host access nor belongs to the protected
executor API. The host must independently authorize its coordinator to read
all historical v1 manifests used by the existing coordinator routine.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from wiki_core.context_packet import validate_result
from wiki_core.context_policy import PolicyError, _git, _policy_at, safe_path, within
from wiki_core.folder_declarations_v2 import (authorized_index, authorized_instruction_chain,
                                              preauthorize_index)
from wiki_core.folder_policy_v2 import FORMAT
from wiki_core.folder_requalification_coordinator_v2 import requalify_v1_as_global_coordinator
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repository_reader import RepositoryReader


class FolderBatchRequalificationError(ValueError):
    pass


def requalify_explicit_batch_as_global_coordinator(root, policy, *, selections):
    """Prepare independently reviewable proposals for explicit consumers.

    Every selected consumer, index and evidence input is checked against current
    ceilings before opening instruction chains. The selected chains then prove
    all mandatory references before any consumer, evidence or historic body is
    opened. Historical manifests are read by the underlying coordinator only
    after those checks; the
    caller's host must grant that access independently. The old Git ancestor and
    policy are not independent proof of historic approval. Dynamic queries,
    receipt conversion, writes and consumer discovery remain unavailable.
    """
    if getattr(policy, 'format_version', None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise FolderBatchRequalificationError('bound folder policy required')
    policy = policy.fresh()
    if not isinstance(selections, list) or not 1 <= len(selections) <= 16:
        raise FolderBatchRequalificationError('one to sixteen explicit selections required')
    if contains_access_secrets(selections):
        raise FolderBatchRequalificationError('secret detected in selection')
    try:
        if len(json.dumps(selections, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')) > 16_000_000:
            raise FolderBatchRequalificationError('selection byte limit exceeded')
        required = {'folder', 'index_path', 'consumer', 'requirement_index', 'packet', 'result', 'proposal_head'}
        seen = set()
        for selection in selections:
            if not isinstance(selection, dict) or set(selection) != required:
                raise FolderBatchRequalificationError('invalid explicit selection')
            folder = selection['folder']; index = selection['index_path']; consumer = safe_path(selection['consumer'])
            requirement_index = selection['requirement_index']; packet = selection['packet']; result = selection['result']
            if folder not in policy.folder_ids or type(requirement_index) is not int or requirement_index < 0:
                raise FolderBatchRequalificationError('selected context or requirement unavailable')
            if (not isinstance(packet, dict) or packet.get('schema_version') != 'wiki.task-context/v1'
                    or not isinstance(result, dict) or result.get('schema_version') != 'wiki.task-result/v1'):
                raise FolderBatchRequalificationError('v1 packet and result required')
            if packet.get('query_selections') or packet.get('query_fingerprint'):
                raise FolderBatchRequalificationError('dynamic query requalification unavailable')
            if packet.get('output') != consumer:
                raise FolderBatchRequalificationError('packet output not bound to consumer')
            if not isinstance(selection['proposal_head'], str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', selection['proposal_head']):
                raise FolderBatchRequalificationError('fixed proposal revision required')
            old_sha = packet.get('policy_revision'); content_sha = packet.get('content_revision')
            if not all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value)
                       for value in (old_sha, content_sha)):
                raise FolderBatchRequalificationError('fixed historical revisions required')
            _git(root, 'merge-base', '--is-ancestor', content_sha, old_sha)
            _git(root, 'merge-base', '--is-ancestor', old_sha, selection['proposal_head'])
            _git(root, 'merge-base', '--is-ancestor', selection['proposal_head'], policy.policy_revision)
            if type(packet.get('max_bytes')) is not int or not 1 <= packet['max_bytes'] <= 1_000_000:
                raise FolderBatchRequalificationError('invalid packet byte limit')
            if (not validate_result(result, packet) or result['status'] != 'completed'
                    or result['read_coverage']['observed_refs'] != packet['declared_read_set']
                    or not any(isinstance(change, dict) and change.get('path') == consumer
                               and change.get('action') in ('created', 'modified') for change in result['changes'])):
                raise FolderBatchRequalificationError('v1 result binding unavailable')
            key = (consumer, requirement_index)
            if key in seen:
                raise FolderBatchRequalificationError('duplicate selection')
            seen.add(key)
            context = policy.folder_ids[folder]
            preauthorize_index(policy, folder, index)
            if (policy.owner_of(consumer) != context or not policy.permits(context, 'read', consumer)
                    or not policy.permits(context, 'write', consumer)):
                raise FolderBatchRequalificationError('current consumer authority unavailable')
            rows = packet.get('inputs')
            if not isinstance(rows, list) or len(rows) > 1000:
                raise FolderBatchRequalificationError('invalid v1 packet inputs')
            for row in rows:
                if not isinstance(row, dict) or row.get('kind') not in ('mandatory', 'evidence') or 'query_id' in row:
                    raise FolderBatchRequalificationError('unsupported v1 input')
                path = safe_path(row['ref'])
                if any(within(path, scope) for scope in policy.effective[context]['deny']['read']):
                    raise FolderBatchRequalificationError('current input authority unavailable')
                if row['kind'] == 'evidence':
                    owner = policy.owner_of(path)
                    if policy.connection(owner, context, path, row['use'], row['classification'],
                                         section=row.get('section'), field=row.get('field')) != 'approved':
                        raise FolderBatchRequalificationError('current input authority unavailable')
        # AGENTS bodies are necessary to establish actual mandatory
        # declarations. Every index, evidence input and instruction-path deny
        # is checked before those bodies; no consumer/evidence/history body is
        # read until all selected chains have been verified.
        for selection in selections:
            context = policy.folder_ids[selection['folder']]
            for folder, instruction in policy.instruction_paths.items():
                if within(selection['folder'], folder) and any(
                        within(instruction, denied) for denied in policy.effective[context]['deny']['read']):
                    raise FolderBatchRequalificationError('current instruction authority unavailable')
        policy.fresh()
        reader = RepositoryReader(root, policy.policy_revision)
        accepted_by_selection = []
        for selection in selections:
            folder = selection['folder']
            chain = authorized_instruction_chain(policy, reader, folder, max_bytes=selection['packet']['max_bytes'])
            authorized_index(policy, folder, selection['index_path'], chain)
            accepted = {}
            for entry in chain:
                owner = policy.owner_of(entry['path'])
                accepted[entry['path']] = owner
                for ref in entry['declarations']['mandatory']:
                    accepted[ref] = owner
            for row in selection['packet']['inputs']:
                if row['kind'] == 'mandatory':
                    ref = safe_path(row['ref'])
                    if accepted.get(ref) != policy.owner_of(ref):
                        raise FolderBatchRequalificationError('current mandatory authority unavailable')
            accepted_by_selection.append(accepted)
        policy.fresh()
        # Check every relevant v1 policy for every item before the individual
        # coordinator can open even the first current consumer body. Global
        # manifest access remains a caller-trust host responsibility.
        historical_policies = {}
        def historical_at(sha):
            if sha not in historical_policies:
                historical_policies[sha] = _policy_at(Path(root), sha, 'context.yaml')
            return historical_policies[sha]
        for selection, accepted in zip(selections, accepted_by_selection):
            folder = selection['folder']; packet = selection['packet']
            old_id = packet['context_id']; consumer = selection['consumer']
            content_policy = historical_at(packet['content_revision'])
            packet_policy = historical_at(packet['policy_revision'])
            proposal_policy = historical_at(selection['proposal_head'])
            for historical in (content_policy, packet_policy, proposal_policy):
                if (old_id not in historical.contexts or historical.contexts[old_id]['root'] != folder
                        or historical.owner_of(consumer) != old_id
                        or not historical.permits(old_id, 'read', consumer)
                        or not historical.permits(old_id, 'write', consumer)):
                    raise FolderBatchRequalificationError('historical consumer authority unavailable')
            mandatory = []; seen_mandatory = set()
            for context in packet_policy.lineage(old_id):
                for category in ('instructions', 'skills', 'templates'):
                    for ref in context[category]:
                        if ref not in seen_mandatory:
                            mandatory.append((ref, context['id']))
                            seen_mandatory.add(ref)
            actual_mandatory = [(row['ref'], row['producer']) for row in packet['inputs'] if row['kind'] == 'mandatory']
            if actual_mandatory != mandatory:
                raise FolderBatchRequalificationError('historical mandatory readset differs')
            for ref, producer in mandatory:
                if (accepted.get(ref) != policy.owner_of(ref) or packet_policy.owner_of(ref) != producer
                        or any(within(ref, denied) for denied in packet_policy.effective[old_id]['deny']['read'])):
                    raise FolderBatchRequalificationError('historical mandatory authority unavailable')
            for row in packet['inputs']:
                ref = safe_path(row['ref']); producer = row['producer']
                if row['kind'] == 'mandatory':
                    if row['revision'] != packet['policy_revision']:
                        raise FolderBatchRequalificationError('historical mandatory authority unavailable')
                    continue
                if row['revision'] != packet['content_revision']:
                    raise FolderBatchRequalificationError('historical evidence revision unavailable')
                for historical in (content_policy, packet_policy, proposal_policy):
                    if (producer not in historical.contexts or historical.owner_of(ref) != producer
                            or historical.contexts[producer]['root'] != policy.contexts[policy.owner_of(ref)]['root']
                            or historical.connection(producer, old_id, ref, row['use'], row['classification'],
                                                     section=row.get('section'), field=row.get('field')) != 'approved'):
                        raise FolderBatchRequalificationError('historical evidence authority unavailable')
        policy.fresh()
        # Only after every selected chain passes may the trusted coordinator
        # open selected consumer/evidence and global historical manifests.
        proposals = []
        for selection in selections:
            proposal = requalify_v1_as_global_coordinator(root, policy, **selection)
            if (proposal.get('state') != 'review_pending' or proposal.get('write') != 'not_performed'
                    or proposal.get('authority') != 'caller_trust_not_verified'):
                raise FolderBatchRequalificationError('unexpected individual proposal')
            proposals.append(proposal)
        policy.fresh()
        output = {'schema_version':'wiki.explicit-requalification-batch/v2', 'state':'review_pending',
                  'policy_revision':policy.policy_revision, 'coverage':'explicit_selected_requirements_only',
                  'proposals':proposals, 'historic_approval':'not_independently_verified',
                  'host_authority':'caller_trust_not_verified', 'migration':'not_performed',
                  'read_verification':'reported_not_independently_verified', 'enforcement_claim':'none'}
        if contains_access_secrets(output):
            raise FolderBatchRequalificationError('secret detected in proposal')
        return output
    except (KeyError, TypeError, AttributeError, PolicyError) as exc:
        raise FolderBatchRequalificationError('selection or authority unavailable') from exc
    except ValueError as exc:
        if isinstance(exc, FolderBatchRequalificationError): raise
        raise FolderBatchRequalificationError('selection or authority unavailable') from exc
