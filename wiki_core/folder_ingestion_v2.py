"""Explicit host-bound folder ingestion selection; request preparation only.

This module does not authenticate the caller, execute a model, or record a v2
result. The host must be authorized to read complete source and context blobs.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from wiki_core.context_policy import safe_path
from wiki_core.folder_coordination_v2 import (
    FolderHostBinding, _bound_policy, _output_authorized, prepare_folder_packet,
)
from wiki_core.folder_declarations_v2 import preauthorize_index
from wiki_core.repository_reader import RepositoryReader, canonical_path


@dataclass(frozen=True)
class FolderIngestionSelection:
    """Trusted host selection, never a capability inferred from source data."""
    host: FolderHostBinding
    folder: str
    index_path: str
    output_path: str


def _check_local_boundaries(root, ref):
    cursor = root
    for part in Path(ref).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError('symlink path is unsupported')
        if cursor.is_dir() and os.path.lexists(cursor / '.git'):
            raise ValueError('independent repository requires explicit selection')


def authorize_folder_ingestion_source(root, source, approved_revision, selection, *, context_max_bytes):
    """Check binding, destination and source before stat or reading source."""
    from wiki_core.llm.context_pass import ContextRequestBlocked
    if not isinstance(selection, FolderIngestionSelection):
        raise ContextRequestBlocked('folder_selection_required', 'A trusted folder selection is required.')
    try:
        policy = _bound_policy(root, selection.host, selection.folder, approved_revision)
        context = policy.folder_ids[selection.folder]
        output = canonical_path(safe_path(selection.output_path))
        output_parts = PurePosixPath(output).parts
        if (PurePosixPath(output).suffix != '.md'
                or output_parts[-1] in ('AGENTS.md', 'AGENTS.override.md', 'CLAUDE.md',
                                        'CLAUDE.local.md', 'SKILL.md', 'index.md', 'context.yaml')
                or any(part in ('.skills', 'skills', '.claude', '.codex') for part in output_parts)):
            raise ValueError('output requires a different review path')
        _output_authorized(policy, selection.folder, selection.output_path)
        preauthorize_index(policy, selection.folder, selection.index_path)
        root = Path(selection.host.root)
        reader = RepositoryReader(root, policy.policy_revision)
        _check_local_boundaries(root, output)
        if (output in reader.paths or any(output == path or output.startswith(path + '/')
                                          for path in reader.unsupported_paths)
                or os.path.lexists(root / output)):
            # Existing output requires a prior whole-output read and a result
            # contract that this request-only preview does not yet implement.
            raise ValueError('existing output requires a separate review path')
        candidate = Path(source).expanduser()
        if urlsplit(source).scheme and not candidate.is_absolute():
            raise ValueError('external source requires authorized staging')
        candidate = candidate if candidate.is_absolute() else root / candidate
        ref = canonical_path(candidate.relative_to(root).as_posix())
        if ref == output:
            raise ValueError('source cannot be its own output')
        producer = policy.owner_of(ref)
        if policy.connection(producer, context, ref, 'interpretation', 'source') != 'approved':
            raise ValueError('source is not authorized')
        # Qualify and read the approved instruction chain, mandatory references
        # and selected index before opening the staged source. The full task
        # packet is rebuilt later with its explicit context selections.
        preliminary = prepare_folder_packet(root, selection.host, {
            'folder': selection.folder, 'approved_revision': policy.policy_revision,
            'content_revision': policy.policy_revision,
            'task': {'index_path': selection.index_path, 'task_id': 'folder-source-preparation',
                     'goal': 'Qualify context before staged source reading',
                     'output': selection.output_path, 'integrator': 'Authorized local coordinator',
                     'max_bytes': context_max_bytes, 'evidence': []}})['packet']
        if any(row['path'] == output for row in preliminary['inputs']):
            raise ValueError('output is a mandatory input')
        _check_local_boundaries(root, ref)
        if not candidate.is_file():
            raise ValueError('source is unavailable')
        digest = hashlib.sha256()
        with candidate.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        policy.fresh()
        return {'root': root, 'path': candidate, 'ref': ref, 'policy': policy,
                'context': context, 'hash_sha256': digest.hexdigest(),
                'reader': reader,
                'folder_selection': selection,
                'context_max_bytes': context_max_bytes,
                'authorization': {'version': 'folder/v2', 'folder': selection.folder,
                    'ref': ref, 'producer': producer, 'context_id': context,
                    'policy_revision': policy.policy_revision, 'use': 'interpretation',
                    'classification': 'source'}}
    except (ValueError, OSError, TypeError, KeyError, AttributeError):
        raise ContextRequestBlocked('folder_source_unavailable',
            'Folder context, destination or source is unavailable or unauthorized, or the context budget is insufficient; no compatibility fallback was used.') from None


def folder_ingestion_context(root, guard, input_context, perspectives_required, *, task_id, max_bytes):
    """Prepare selected context for one concrete destination and trusted host."""
    if input_context.get('context_omissions'):
        # V2 does not yet encode v1's coverage/omission contract. Do not drop
        # a known missing input or make an incomplete task look complete.
        raise ValueError('folder context coverage is incomplete')
    selection = guard['folder_selection']
    policy = guard['policy'].fresh()
    context = guard['context']
    reader = guard['reader']
    if reader.revision != policy.policy_revision:
        raise ValueError('folder context revision changed')
    refs = [info['path'] for name in ('root_entity', 'input_channel', 'source_config')
            if (info := input_context.get(name) or {}).get('path')]
    for ref in perspectives_required:
        # Avoid a global or implicit catalog read in this preliminary route.
        # A page ID needs explicit resolution by an authorized coordinator.
        path = safe_path(ref)
        if path not in reader.paths or policy.owner_of(path) != context or not policy.permits(context, 'read', path):
            raise ValueError('required perspective unavailable or not an explicit path')
        refs.append(path)
    evidence = []
    for ref in dict.fromkeys(refs):
        ref = safe_path(ref)
        producer = policy.owner_of(ref)
        evidence.append({'path': ref, 'producer_folder': policy.contexts[producer]['root'],
            'reason': 'Required ingestion interpretation context', 'use': 'interpretation',
            'classification': 'context'})
    payload = {'folder': selection.folder, 'approved_revision': policy.policy_revision,
               'content_revision': reader.revision,
               'task': {'index_path': selection.index_path, 'task_id': task_id,
                        'goal': 'Deep contextual reading of the extracted source',
                        'output': selection.output_path,
                        'integrator': 'Operating agent under the repository PR review gate',
                        'max_bytes': max_bytes, 'evidence': evidence}}
    return prepare_folder_packet(root, selection.host, payload)['packet']
