"""Narrow v1 packet replay without reading other owners' manifest bodies.

Experimental internal proof only: supports a historical tree containing exactly
one root context.yaml, an explicitly selected current root context and no query
receipts. Multi-context histories remain blocked, rather than projected.
"""
from __future__ import annotations

import re
from pathlib import Path

from wiki_core.context_packet import build_packet, validate_result
from wiki_core.context_policy import PolicyError, _git, _policy_at, safe_path, within
from wiki_core.folder_declarations_v2 import authorized_index, authorized_instruction_chain, preauthorize_index
from wiki_core.folder_policy_v2 import FORMAT
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repository_reader import RepositoryReader


class ScopedReplayError(ValueError):
    pass


def _fixed(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value):
        raise ScopedReplayError('fixed historical revision required')
    return value


def replay_root_only_v1(root, policy, *, index_path, packet, result):
    """Reproduce exact v1 bytes only after current authority for every input.

    A one-manifest tree is proved from Git metadata before the old root manifest
    body is opened. No caller label or boolean is used as capability evidence.
    This routine does not prove review, execution, freshness or isolation.
    """
    if getattr(policy, 'format_version', None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise ScopedReplayError('bound v2 policy required')
    policy = policy.fresh()
    if not isinstance(packet, dict) or packet.get('schema_version') != 'wiki.task-context/v1':
        raise ScopedReplayError('v1 packet required')
    if not isinstance(result, dict) or result.get('schema_version') != 'wiki.task-result/v1':
        raise ScopedReplayError('v1 result required')
    if packet.get('query_selections') or packet.get('query_fingerprint'):
        raise ScopedReplayError('dynamic v1 query requires independent v2 requalification')
    if contains_access_secrets(packet) or contains_access_secrets(result):
        raise ScopedReplayError('secret detected in receipt')
    try:
        context = policy.folder_ids['.']
        preauthorize_index(policy, '.', index_path)
        current = RepositoryReader(root, policy.policy_revision)
        chain = authorized_instruction_chain(policy, current, '.', max_bytes=packet['max_bytes'])
        authorized_index(policy, '.', index_path, chain)
        accepted = {}
        for entry in chain:
            owner = policy.owner_of(entry['path'])
            accepted[entry['path']] = owner
            for ref in entry['declarations']['mandatory']:
                accepted[ref] = owner
        if not isinstance(packet.get('inputs'), list):
            raise ScopedReplayError('invalid v1 inputs')
        evidence = []
        # Authorize every path now, before opening any historical body. The
        # original producer ID is checked by exact packet reconstruction later.
        for row in packet['inputs']:
            if not isinstance(row, dict) or row.get('kind') not in ('mandatory', 'evidence') or 'query_id' in row:
                raise ScopedReplayError('v1 input or query is unsupported')
            ref = safe_path(row['ref'])
            if policy.owner_of(ref) != context:
                raise ScopedReplayError('cross-owner input requires scoped history support')
            if any(within(ref, scope) for scope in policy.effective[context]['deny']['read']):
                raise ScopedReplayError('current input authority unavailable')
            if row['kind'] == 'mandatory':
                if accepted.get(ref) != context:
                    raise ScopedReplayError('current normative authority unavailable')
            else:
                if policy.connection(context, context, ref, row['use'], row['classification'],
                                     section=row.get('section'), field=row.get('field')) != 'approved':
                    raise ScopedReplayError('current input authority unavailable')
                entry = {key:row[key] for key in ('ref','producer','reason','use','classification')}
                for key in ('section','field'):
                    if row.get(key) is not None: entry[key] = row[key]
                evidence.append(entry)
        # The control file itself is also an authorized selected-owner read.
        if policy.owner_of('context.yaml') != context or not policy.permits(context, 'read', 'context.yaml'):
            raise ScopedReplayError('historical root policy read is not authorized')
        old_sha = _fixed(packet.get('policy_revision')); content_sha = _fixed(packet.get('content_revision'))
        _git(root, 'merge-base', '--is-ancestor', old_sha, policy.policy_revision)
        _git(root, 'merge-base', '--is-ancestor', content_sha, old_sha)
        if not validate_result(result, packet) or result['status'] != 'completed':
            raise ScopedReplayError('invalid v1 result')
        if result['read_coverage']['observed_refs'] != packet['declared_read_set']:
            raise ScopedReplayError('v1 reported reads are incomplete')
        for sha in {old_sha, content_sha}:
            listing = _git(root, 'ls-tree', '-r', '-z', '--name-only', sha).split(b'\0')
            manifests = {p for p in listing if p and (p == b'context.yaml' or p.endswith(b'/context.yaml'))}
            if manifests != {b'context.yaml'}:
                raise ScopedReplayError('historical multi-context projection unavailable')
        # Both trees must have exactly one currently authorized manifest before
        # either historical policy body is loaded. The root-only policy at the
        # content revision then governs each historical selection.
        old = _policy_at(Path(root), old_sha, 'context.yaml')
        old._binding = (str(Path(root).resolve()), old_sha, 'context.yaml')
        if packet['context_id'] not in old.contexts or old.contexts[packet['context_id']]['root'] != '.':
            raise ScopedReplayError('historical root identity unavailable')
        content_policy = old if content_sha == old_sha else _policy_at(Path(root), content_sha, 'context.yaml')
        old_context = packet['context_id']
        if old_context not in content_policy.contexts or content_policy.contexts[old_context]['root'] != '.':
            raise ScopedReplayError('historical content root identity unavailable')
        mandatory = []
        seen_mandatory = set()
        for ancestor in old.lineage(old_context):
            for category in ('instructions', 'skills', 'templates'):
                for ref in ancestor[category]:
                    if ref not in seen_mandatory:
                        mandatory.append((ref, ancestor['id']))
                        seen_mandatory.add(ref)
        actual_mandatory = [(row['ref'], row.get('producer')) for row in packet['inputs'] if row['kind'] == 'mandatory']
        if actual_mandatory != mandatory:
            raise ScopedReplayError('historical mandatory readset differs')
        for ref, producer in mandatory:
            if (accepted.get(ref) != context or old.owner_of(ref) != producer
                    or any(within(ref, denied) for denied in old.effective[old_context]['deny']['read'])):
                raise ScopedReplayError('historical mandatory authority unavailable')
        for row in packet['inputs']:
            ref = safe_path(row['ref'])
            if (row['kind'] == 'mandatory' and (row.get('revision') != old_sha
                    or row.get('section') is not None or row.get('field') is not None)):
                raise ScopedReplayError('historical mandatory authority unavailable')
            if row['kind'] == 'evidence' and row.get('revision') != content_sha:
                raise ScopedReplayError('historical evidence revision unavailable')
            if (row.get('producer') != old_context or content_policy.owner_of(ref) != old_context
                    or not content_policy.permits(old_context, 'read', ref)):
                raise ScopedReplayError('historical content authority unavailable')
            if row['kind'] == 'evidence' and content_policy.connection(
                    old_context, old_context, ref, row['use'], row['classification'],
                    section=row.get('section'), field=row.get('field')) != 'approved':
                raise ScopedReplayError('historical content authority unavailable')
        rebuilt = build_packet(root, old, packet['context_id'], content_sha, evidence, packet['max_bytes'],
                    adapter_report=packet['capability_evidence'], required_capabilities=packet['required_capabilities'],
                    omissions=packet['coverage']['missing'], task_id=packet['task_id'], goal=packet['goal'],
                    output=packet['output'], integrator=packet['integrator'])
        if rebuilt != packet:
            raise ScopedReplayError('historical packet cannot be reproduced exactly')
        policy.fresh()
        return {'schema_version':'wiki.scoped-v1-replay/v2','state':'reproduced',
                'packet_digest':packet['packet_digest'],'historical_policy_revision':old_sha,
                'content_revision':content_sha,'current_policy_revision':policy.policy_revision,
                'projection':'single_root_manifest_only','read_verification':'reported_not_independently_verified',
                'review':'not_performed','freshness':'not_assessed','normative_equivalence':'not_assessed',
                'execution':'not_proved'}
    except (PolicyError, KeyError, TypeError, AttributeError) as exc:
        raise ScopedReplayError('historical policy or current authority unavailable') from exc
    except ValueError as exc:
        if isinstance(exc, ScopedReplayError):
            raise
        raise ScopedReplayError('historical replay unavailable') from exc
