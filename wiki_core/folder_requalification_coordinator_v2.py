"""Trusted local coordinator-only v1 requalification, not an executor API.

The calling host must already authorize its coordinator to read all historical
v1 policy manifests. This function does not verify caller identity or provide
an ACL/sandbox; successful local reads prove availability only. It is not wired
to a CLI, server or protected-executor route. Unrelated policy bodies are never
returned; current authority is checked for every selected input before replay.
"""
from __future__ import annotations

import re
from pathlib import Path

from wiki_core.context_packet import build_packet, validate_result
from wiki_core.context_policy import PolicyError, _git, _policy_at, safe_path, within
from wiki_core.folder_declarations_v2 import authorized_index, authorized_instruction_chain, preauthorize_index
from wiki_core.folder_policy_v2 import FORMAT
from wiki_core.information_relations import information_requirements
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repository_reader import RepositoryReader


class CoordinatorRequalificationError(ValueError):
    pass


def _fixed(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value):
        raise CoordinatorRequalificationError('fixed revision required')
    return value


def _selector(value):
    if value == '*': return None, None
    if value.startswith('field:') and len(value) > 6: return None, value[6:]
    if value.startswith('section:') and len(value) > 8: return value[8:], None
    if re.fullmatch(r'[a-z][a-z0-9_]*', value): return None, value
    raise CoordinatorRequalificationError('requirement selector is not supported')


def requalify_v1_as_global_coordinator(root, policy, *, folder, index_path, consumer, requirement_index,
                                       packet, result, proposal_head):
    """Return one selected review proposal for a pre-authorized global caller.

    The caller-trust host is responsible for granting access to every v1 policy
    manifest before invoking this function. This is neither a proof of caller
    authorization nor an isolation boundary. Historical authority is checked
    at the content, policy and proposal revisions before historical bodies are
    opened. No write, conversion, execution, publication or approval occurs.
    Queries are refused and v1 data is retained.
    """
    if getattr(policy, 'format_version', None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise CoordinatorRequalificationError('bound v2 policy required')
    policy = policy.fresh()
    if not isinstance(packet, dict) or packet.get('schema_version') != 'wiki.task-context/v1':
        raise CoordinatorRequalificationError('v1 packet required')
    if not isinstance(result, dict) or result.get('schema_version') != 'wiki.task-result/v1':
        raise CoordinatorRequalificationError('v1 result required')
    if packet.get('query_selections') or packet.get('query_fingerprint'):
        raise CoordinatorRequalificationError('dynamic v1 query requires independent v2 requalification')
    if contains_access_secrets(packet) or contains_access_secrets(result):
        raise CoordinatorRequalificationError('secret detected in receipt')
    try:
        consumer = safe_path(consumer)
        if folder not in policy.folder_ids or type(requirement_index) is not int or requirement_index < 0:
            raise CoordinatorRequalificationError('selected context or requirement unavailable')
        if packet.get('output') != consumer:
            raise CoordinatorRequalificationError('v1 packet output is not bound to selected consumer')
        context = policy.folder_ids[folder]
        if (policy.owner_of(consumer) != context or not policy.permits(context, 'read', consumer)
                or not policy.permits(context, 'write', consumer)):
            raise CoordinatorRequalificationError('consumer outside current authority')
        preauthorize_index(policy, folder, index_path)
        current = RepositoryReader(root, policy.policy_revision)
        chain = authorized_instruction_chain(policy, current, folder, max_bytes=packet['max_bytes'])
        authorized_index(policy, folder, index_path, chain)
        consumer_now = current.read(consumer)
        if contains_access_secrets(consumer_now['text']):
            raise CoordinatorRequalificationError('secret detected in consumer')
        raw = consumer_now['frontmatter'].get('information_requirements')
        if not isinstance(raw, list) or requirement_index >= len(raw) or not isinstance(raw[requirement_index], dict):
            raise CoordinatorRequalificationError('canonical requirement unavailable')
        selected = raw[requirement_index]
        if 'query' in selected or any(k in selected for k in ('query_policy_revision','authority_digest','members_digest','selected_digest')):
            raise CoordinatorRequalificationError('dynamic v1 query requires independent v2 requalification')
        def resolve(ref):
            try:
                path = safe_path(ref)
                return [path] if '/' in path or path.endswith('.md') else []
            except PolicyError:
                return []
        requirements = information_requirements(consumer_now['frontmatter'], resolve)
        requirement = requirements[requirement_index]
        consumed = _fixed(requirement.get('consumed_revision'))
        source = requirement['target']
        old_sha = _fixed(packet.get('policy_revision')); content_sha = _fixed(packet.get('content_revision'))
        proposal_head = _fixed(proposal_head)
        _git(root, 'merge-base', '--is-ancestor', old_sha, policy.policy_revision)
        _git(root, 'merge-base', '--is-ancestor', content_sha, old_sha)
        _git(root, 'merge-base', '--is-ancestor', old_sha, proposal_head)
        _git(root, 'merge-base', '--is-ancestor', proposal_head, policy.policy_revision)
        accepted = {}; current_normative = []; seen = set()
        for entry in chain:
            if entry['path'] not in seen:
                current_normative.append(entry['path']); seen.add(entry['path'])
            try:
                owner = policy.owner_of(entry['path'])
            except PolicyError:
                if entry['declarations']['mandatory']: raise
                continue
            accepted[entry['path']] = owner
            for ref in entry['declarations']['mandatory']:
                accepted[ref] = owner
                if ref not in seen:
                    current_normative.append(ref); seen.add(ref)
        if not isinstance(packet.get('inputs'), list):
            raise CoordinatorRequalificationError('invalid v1 inputs')
        # First validate current authority for every selected path using only
        # current ownership. No historic context or source body is open yet.
        current_owners = []
        for row in packet['inputs']:
            if not isinstance(row, dict) or row.get('kind') not in ('mandatory', 'evidence') or 'query_id' in row:
                raise CoordinatorRequalificationError('v1 input or query is unsupported')
            ref = safe_path(row['ref']); owner = policy.owner_of(ref); current_owners.append(owner)
            if any(within(ref, scope) for scope in policy.effective[context]['deny']['read']):
                raise CoordinatorRequalificationError('current input authority unavailable')
            if row['kind'] == 'mandatory':
                if accepted.get(ref) != owner:
                    raise CoordinatorRequalificationError('mandatory authority changed; requalification required')
            elif policy.connection(owner, context, ref, row['use'], row['classification'],
                                   section=row.get('section'), field=row.get('field')) != 'approved':
                raise CoordinatorRequalificationError('current input authority unavailable')
        if not validate_result(result, packet) or result['status'] != 'completed':
            raise CoordinatorRequalificationError('historical v1 receipt invalid')
        if result['read_coverage']['observed_refs'] != packet['declared_read_set']:
            raise CoordinatorRequalificationError('historical reads are incomplete')
        if not any(c.get('path') == consumer and c.get('action') in ('created','modified') for c in result['changes']):
            raise CoordinatorRequalificationError('consumer not reported in v1 result')
        changed = _git(root, '--literal-pathspecs', 'diff', '--no-renames', '--name-only', '-z', old_sha, proposal_head, '--', consumer)
        if changed != consumer.encode('utf-8') + b'\0':
            raise CoordinatorRequalificationError('proposal does not change consumer')
        # Global v1 policy read belongs solely to the host-authorized caller.
        # A failure is opaque and never exposes other owners' metadata.
        historical_policies = {sha: _policy_at(Path(root), sha, 'context.yaml')
                               for sha in dict.fromkeys((content_sha, old_sha, proposal_head))}
        old = historical_policies[old_sha]
        old_context = packet['context_id']
        for historical in historical_policies.values():
            if (old_context not in historical.contexts or historical.contexts[old_context]['root'] != folder
                    or historical.owner_of(consumer) != old_context or not historical.permits(old_context,'read',consumer)
                    or not historical.permits(old_context,'write',consumer)):
                raise CoordinatorRequalificationError('historical consumer owner or authority unavailable')
        mandatory = []; seen_mandatory = set()
        for ancestor in old.lineage(old_context):
            for category in ('instructions', 'skills', 'templates'):
                for ref in ancestor[category]:
                    if ref not in seen_mandatory:
                        mandatory.append((ref, ancestor['id']))
                        seen_mandatory.add(ref)
        if [(row['ref'], row['producer']) for row in packet['inputs'] if row['kind'] == 'mandatory'] != mandatory:
            raise CoordinatorRequalificationError('historical mandatory readset differs')
        evidence = []
        for row, owner in zip(packet['inputs'], current_owners):
            producer = row['producer']; ref = row['ref']
            if producer not in old.contexts or old.owner_of(ref) != producer:
                raise CoordinatorRequalificationError('historical input owner unavailable')
            if old.contexts[producer]['root'] != policy.contexts[owner]['root']:
                raise CoordinatorRequalificationError('input owner changed; explicit migration required')
            if row['kind'] == 'mandatory' and row['revision'] != old_sha:
                raise CoordinatorRequalificationError('historical mandatory revision unavailable')
            if row['kind'] == 'mandatory' and any(within(ref, denied) for denied in old.effective[old_context]['deny']['read']):
                raise CoordinatorRequalificationError('historical mandatory authority unavailable')
            if row['kind'] == 'evidence':
                if row['revision'] != content_sha:
                    raise CoordinatorRequalificationError('historical evidence revision unavailable')
                for historical in historical_policies.values():
                    if (producer not in historical.contexts or historical.owner_of(ref) != producer
                            or historical.contexts[producer]['root'] != policy.contexts[owner]['root']
                            or historical.connection(producer, old_context, ref, row['use'], row['classification'],
                                                     section=row.get('section'), field=row.get('field')) != 'approved'):
                        raise CoordinatorRequalificationError('historical evidence authority unavailable')
                item = {k:row[k] for k in ('ref','producer','reason','use','classification')}
                for key in ('section','field'):
                    if row.get(key) is not None: item[key] = row[key]
                evidence.append(item)
        proposed = RepositoryReader(root, proposal_head).read(consumer)
        if proposed['content_sha256'] != consumer_now['content_sha256']:
            raise CoordinatorRequalificationError('approved consumer differs from proposal')
        old._binding = (str(Path(root).resolve()), old_sha, 'context.yaml')
        rebuilt = build_packet(root, old, old_context, content_sha, evidence, packet['max_bytes'],
                     adapter_report=packet['capability_evidence'], required_capabilities=packet['required_capabilities'],
                     omissions=packet['coverage']['missing'], task_id=packet['task_id'], goal=packet['goal'],
                     output=packet['output'], integrator=packet['integrator'])
        if rebuilt != packet:
            raise CoordinatorRequalificationError('historical packet cannot be reproduced exactly')
        # Compare every previously consumed mandatory body; changed instructions
        # remain a pending normative review even if factual bytes are unchanged.
        historical_normative = [row['ref'] for row in packet['inputs'] if row['kind'] == 'mandatory']
        normative_equal = historical_normative == current_normative
        for row in packet['inputs']:
            if row['kind'] == 'mandatory':
                current_item = current.read(row['ref'])
                if contains_access_secrets(current_item['text']):
                    raise CoordinatorRequalificationError('secret detected in current normative content')
                normative_equal = normative_equal and current_item['content_digest'] == row['sha256']
        comparisons = []
        for selector in requirement['fields']:
            section, field = _selector(selector)
            matches = []
            for row in packet['inputs']:
                if row['ref'] != source or row['revision'] != consumed: continue
                if requirement.get('source_kind') == 'mandatory':
                    if row['kind'] == 'mandatory' and section is None and field is None: matches.append(row)
                elif (row['kind'] == 'evidence' and row.get('section') == section and row.get('field') == field
                      and row.get('use') == requirement.get('use','interpret')
                      and row.get('classification') == requirement.get('classification','internal')):
                    matches.append(row)
            if len(matches) != 1:
                raise CoordinatorRequalificationError('v1 selection does not match canonical requirement')
            current_source = current.read(source, section=section, field=field)
            if contains_access_secrets(current_source['text']):
                raise CoordinatorRequalificationError('secret detected in current source')
            comparisons.append({'selector':selector,'consumed_digest':matches[0]['sha256'],
                                'current_digest':current_source['content_digest'],
                                'bytes_equivalent':matches[0]['sha256']==current_source['content_digest']})
        out = {'schema_version':'wiki.requirement-requalification/v2','state':'review_pending',
               'consumer':consumer,'source':source,'context_id':context,'consumed_revision':consumed,
               'v1_policy_revision':old_sha,'v1_packet_digest':packet['packet_digest'],'proposal_head':proposal_head,
               'current_policy_revision':policy.policy_revision,'selectors':comparisons,
               'normative_bytes':'equivalent' if normative_equal else 'changed_review_required',
               'normative_coverage':'current_chain_and_v1_inputs_compared' if historical_normative == current_normative else 'new_or_reordered_rules_require_review',
               'original_requirement_preserved':True,'write':'not_performed','review':'not_performed',
               'freshness':'not_assessed','read_verification':'reported_not_independently_verified',
               'authority':'caller_trust_not_verified','historical_authority':'ancestor_only_not_independent_approval_proof'}
        if contains_access_secrets(out):
            raise CoordinatorRequalificationError('secret detected in requalification metadata')
        policy.fresh()
        return out
    except (PolicyError, KeyError, TypeError, AttributeError, IndexError) as exc:
        raise CoordinatorRequalificationError('requirement or authority unavailable') from exc
    except ValueError as exc:
        if isinstance(exc, CoordinatorRequalificationError): raise
        raise CoordinatorRequalificationError('requirement source or revision unavailable') from exc
