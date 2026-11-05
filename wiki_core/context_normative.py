"""Authority for explicitly declared, whole inherited normative inputs."""
from wiki_core.context_policy import PolicyError, historical_policy, safe_path, within


def normative_allowed(policy, context, ref):
    if getattr(policy, 'format_version', None):
        raise PolicyError('v2 normative checks require the versioned v2 interface')
    ref = safe_path(ref)
    if any(within(ref, scope) for scope in policy.effective[context]['deny']['read']):
        return False
    return any(ref in c[key] for c in policy.lineage(context)
               for key in ('instructions', 'skills', 'templates'))


def normative_history(policy, context, ref, revision, *, authority_format=None, entry_folder=None, entry_index=None):
    """Check current authority and approved ancestry before historical bodies."""
    try:
        if getattr(policy, 'format_version', None) == 'folder':
            if authority_format != 'folder' or not isinstance(entry_folder, str) or not isinstance(entry_index, str):
                return False
            from wiki_core.context_packet import qualify_folder_context, guard_folder_blob
            from wiki_core.context_selection import _equivalent_folder_chain
            from wiki_core.context_policy import is_context_instruction
            if not getattr(policy, '_binding', None) or not is_context_instruction(ref): return False
            key = (context, entry_folder, entry_index)
            qualified = getattr(policy, '_folder_qualifications', {}).get(key)
            if qualified is None:
                qualify_folder_context(policy._binding[0], policy, context, entry_folder, entry_index, 2_000_000)
                qualified = policy._folder_qualifications[key]
            else:
                from wiki_core.traversal import require_wiki_path
                require_wiki_path(policy._binding[0], entry_folder)
                for selected in qualified['refs']: guard_folder_blob(policy._binding[0], policy, selected)
            if ref not in qualified.get('refs', ()) or not qualified.get('nonempty', {}).get(ref): return False
            producer = policy.owner_of(ref)
            if policy.connection(producer, context, ref, 'interpretation', 'context') != 'approved': return False
            _equivalent_folder_chain(policy, context, revision, entry_folder, entry_index)
            return True
        if not normative_allowed(policy, context, ref):
            return False
        prior = historical_policy(policy, revision)
        return normative_allowed(prior, context, ref) and prior.owner_of(ref) == policy.owner_of(ref)
    except (PolicyError, KeyError, ValueError):
        return False
