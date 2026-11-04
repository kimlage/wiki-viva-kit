"""Fail-closed entry for historical v1 requirement requalification.

The v1 loader opens every context manifest, including unrelated owners. There is
no verified global-host capability or scoped historical loader in this interface;
therefore no historical replay or equivalence result is currently produced.
"""
from __future__ import annotations

from pathlib import Path

from wiki_core.context_policy import PolicyError, safe_path
from wiki_core.folder_declarations_v2 import authorized_index, authorized_instruction_chain, preauthorize_index
from wiki_core.folder_policy_v2 import FORMAT
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repository_reader import RepositoryReader


class RequalificationError(ValueError):
    pass


def requalify_explicit_v1_requirement(root, policy, *, folder, index_path, consumer, requirement_index,
                                      packet, result, proposal_head):
    """Check current context and report why historical requalification is blocked.

    No caller-supplied role, flag or adapter report can certify a global host
    capability. This entry does not open any historical policy or source body.
    """
    if getattr(policy, 'format_version', None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise RequalificationError('bound v2 policy required')
    policy = policy.fresh()
    if not isinstance(packet, dict) or packet.get('schema_version') != 'wiki.task-context/v1':
        raise RequalificationError('v1 packet required')
    if not isinstance(result, dict) or result.get('schema_version') != 'wiki.task-result/v1':
        raise RequalificationError('v1 result required')
    if packet.get('query_selections') or packet.get('query_fingerprint'):
        raise RequalificationError('dynamic v1 query requires independent v2 requalification')
    if contains_access_secrets(packet) or contains_access_secrets(result):
        raise RequalificationError('secret detected in receipt')
    try:
        consumer = safe_path(consumer)
        if folder not in policy.folder_ids or type(requirement_index) is not int or requirement_index < 0:
            raise RequalificationError('selected context or requirement unavailable')
        context = policy.folder_ids[folder]
        if policy.owner_of(consumer) != context or not policy.permits(context, 'read', consumer):
            raise RequalificationError('consumer outside current authority')
        preauthorize_index(policy, folder, index_path)
        current = RepositoryReader(root, policy.policy_revision)
        chain = authorized_instruction_chain(policy, current, folder, max_bytes=packet['max_bytes'])
        authorized_index(policy, folder, index_path, chain)
        consumer_now = current.read(consumer)
        if contains_access_secrets(consumer_now['text']):
            raise RequalificationError('secret detected in consumer')
        raw = consumer_now['frontmatter'].get('information_requirements')
        if not isinstance(raw, list) or requirement_index >= len(raw) or not isinstance(raw[requirement_index], dict):
            raise RequalificationError('canonical requirement unavailable')
        if 'query' in raw[requirement_index] or any(k in raw[requirement_index] for k in ('query_policy_revision','authority_digest','members_digest','selected_digest')):
            raise RequalificationError('dynamic v1 query requires independent v2 requalification')
        # The required historical loader is global and the host capability to
        # use it has not been established. Do not call _policy_at/build_packet.
        raise RequalificationError('historical v1 policy access unavailable; normative equivalence not assessed')
    except (PolicyError, KeyError, TypeError, AttributeError) as exc:
        raise RequalificationError('requirement or authority unavailable') from exc
    except ValueError as exc:
        if isinstance(exc, RequalificationError):
            raise
        raise RequalificationError('requirement source or revision unavailable') from exc
