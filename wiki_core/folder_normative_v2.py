"""Versioned checks of folder instructions, not v1 receipt migration."""
from __future__ import annotations

import re
from pathlib import Path

from wiki_core.context_policy import PolicyError, _git, safe_path, within
from wiki_core.folder_policy_v2 import FORMAT, _at_revision
from wiki_core.folder_declarations_v2 import authorized_index, authorized_instruction_chain, preauthorize_index
from wiki_core.repository_reader import RepositoryReader
from wiki_core.folder_auxiliary_v2 import qualify_auxiliary


def folder_normative_allowed_v2(policy, folder, ref, *, index_path, max_bytes=32768, start_folder=None):
    """Check a selected physical instruction without reading the rule body."""
    if getattr(policy, 'format_version', None) != FORMAT:
        raise PolicyError('explicit v2 policy required')
    ref = safe_path(ref)
    if folder not in policy.folder_ids:
        return False
    context = policy.folder_ids[folder]
    try:
        preauthorize_index(policy, folder, index_path)
        reader = RepositoryReader(policy._inspection_root, policy.policy_revision)
        if start_folder is not None:
            if not policy.permits(context, 'read', ref):
                return False
            policy = qualify_auxiliary(policy, reader, folder, start_folder, max_bytes=max_bytes)
        chain = authorized_instruction_chain(policy, reader, folder, max_bytes=max_bytes, start_folder=start_folder)
        index = authorized_index(policy, folder, index_path, chain)
        if reader.blob_size(index) > max_bytes or not reader.read(index)['text'].strip():
            return False
    except (PolicyError, ValueError):
        return False
    if any(within(ref, scope) for scope in policy.effective[context]['deny']['read']):
        return False
    allowed = {entry['path'] for entry in chain}
    allowed.update(path for entry in chain for path in entry['declarations']['mandatory'])
    return ref in allowed


def folder_normative_history_v2(policy, folder, ref, consumed_revision, *, index_path, max_bytes=32768, start_folder=None):
    """Compare relevant v2 instruction membership at current and ancestor SHA.

    Both states must have mechanically permitted selected indexes. This says
    nothing about content equivalence; callers must compare the selected bytes.
    A historical v1 receipt is not accepted as proof by this function.
    """
    if getattr(policy, 'format_version', None) != FORMAT or not policy._binding:
        raise PolicyError('bound v2 policy required')
    policy = policy.fresh()
    if not isinstance(consumed_revision, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', consumed_revision):
        raise PolicyError('fixed consumed revision required')
    root, _, controls = policy._binding
    try:
        _git(Path(root), 'merge-base', '--is-ancestor', consumed_revision, policy.policy_revision)
        old = _at_revision(Path(root), consumed_revision, controls)
        return (folder_normative_allowed_v2(policy, folder, ref, index_path=index_path, max_bytes=max_bytes, start_folder=start_folder)
                and folder_normative_allowed_v2(old, folder, ref, index_path=index_path, max_bytes=max_bytes, start_folder=start_folder))
    except (PolicyError, ValueError, KeyError):
        return False
