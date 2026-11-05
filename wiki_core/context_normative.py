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
                if not require_wiki_path(policy._binding[0], entry_folder).is_dir(): return False
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


def folder_normative_changed(policy, context, ref, revision, *, entry_folder, entry_index):
    """Identify a changed consumed instruction without granting historical access.

    This reports only a proved change to an instruction that is in the current
    qualified physical chain and was authorized at both revisions. Ambiguous
    historical override precedence, changed owners or missing evidence remain
    unqualified; they do not become a change claim.
    """
    from pathlib import Path, PurePosixPath
    from wiki_core.context_packet import guarded_context_read
    from wiki_core.context_policy import is_context_instruction
    from wiki_core.detectors import scan_text
    from wiki_core.repository_reader import RepositoryReader
    try:
        if (getattr(policy, 'format_version', None) != 'folder' or not getattr(policy, '_binding', None)
                or not is_context_instruction(ref)):
            return False
        selected = policy._folder_qualifications.get((context, entry_folder, entry_index))
        if not selected or ref not in selected['refs'] or not selected['nonempty'].get(ref): return False
        prior = historical_policy(policy, revision, authority_format='folder')
        if (context not in prior.contexts or
                [c['id'] for c in prior.lineage(context)] != [c['id'] for c in policy.lineage(context)] or
                (entry_folder != '.' and prior.owner_of(entry_folder) != context) or
                entry_index not in prior._folder_names):
            return False
        producer = policy.owner_of(ref)
        if (prior.owner_of(ref) != producer or
                prior.contexts[producer]['owner'] != policy.contexts[producer]['owner'] or
                policy.connection(producer, context, ref, 'interpretation', 'context') != 'approved' or
                prior._connection(producer, context, ref, 'interpretation', 'context', qualified=False) != 'approved'):
            return False
        parent = str(PurePosixPath(ref).parent)
        if parent != '.' and not within(entry_folder, parent): return False
        # A historical nonempty override could have displaced the ordinary
        # instruction. Do not guess which text was actually consumed.
        override = ('AGENTS.override.md' if parent == '.' else parent + '/AGENTS.override.md')
        if PurePosixPath(ref).name == 'AGENTS.md' and override in prior._folder_names: return False
        root = Path(policy._binding[0])
        old_reader = RepositoryReader(root, revision)
        new_reader = RepositoryReader(root, policy.policy_revision)
        if ref not in old_reader._entries or ref not in new_reader._entries: return False
        if old_reader._entries[ref] == new_reader._entries[ref]: return False
        old_text = guarded_context_read(old_reader, policy, ref)['text']
        if not old_text.strip() or any(item.category == 'secret' for item in scan_text(old_text)):
            return False
        policy.fresh()
        return True
    except (PolicyError, KeyError, ValueError, OSError, TypeError):
        return False
