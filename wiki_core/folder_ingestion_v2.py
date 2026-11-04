"""Explicit host-bound folder ingestion selection and capture revalidation.

This module does not authenticate the caller or execute a model. The host must
be authorized to read complete source and context blobs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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
    source_ref: str | None = None
    independent_repo: tuple[str, str, str, str] | None = None


def selection_from_host_environment(folder, index_path, output_path, source_ref=None, env=None, *, independent_repo=None):
    """Use host startup configuration; the request cannot widen its allowlist."""
    env = os.environ if env is None else env
    host_root = env.get('WIKI_FOLDER_INGEST_HOST_ROOT', '').strip()
    allowlist = env.get('WIKI_FOLDER_INGEST_HOST_FOLDERS', '').strip()
    if not host_root or not allowlist:
        raise ValueError('host binding unavailable')
    try:
        configured = json.loads(env.get('WIKI_FOLDER_INGEST_HOST_REPOSITORIES', '[]'))
        if not isinstance(configured, list):
            raise ValueError('invalid repository bindings')
        repos = tuple(tuple(row) for row in configured)
        host = FolderHostBinding(Path(host_root), tuple(part.strip() for part in allowlist.split(',')), repos)
    except (ValueError, TypeError):
        raise ValueError('invalid repository bindings') from None
    return FolderIngestionSelection(host, folder, index_path, output_path, source_ref, independent_repo)


def independent_repo_selection_for_request(host, folder, authorization):
    """Resolve an explicit request selection only through the current trusted host."""
    receipt = authorization.get('independent_repo_read') if isinstance(authorization, dict) else None
    if receipt is None:
        return None
    if not isinstance(host, FolderHostBinding) or not isinstance(receipt, dict):
        raise ValueError('repository binding unavailable')
    repository = receipt.get('repository')
    if not isinstance(repository, dict):
        raise ValueError('repository binding unavailable')
    identity, path, revision = repository.get('identity'), receipt.get('path'), receipt.get('revision')
    if (not isinstance(identity, str) or not isinstance(path, str)
            or not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision)):
        raise ValueError('repository binding unavailable')
    matches = [repo_root for f, repo_root, repo_identity, repo_path in host.independent_repos
               if f == folder and repo_identity == identity and repo_path == path]
    if len(matches) != 1:
        raise ValueError('repository binding unavailable')
    return (str(matches[0]), identity, revision, path)


def _check_local_boundaries(root, ref):
    ref = safe_path(ref)
    cursor = root
    for part in Path(ref).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError('symlink path is unsupported')
        if cursor.is_dir() and os.path.lexists(cursor / '.git'):
            raise ValueError('independent repository requires explicit selection')


def validate_folder_artifact_paths(root, paths, source_id, *, stream=False, score=False):
    """Fence the existing pipeline's fixed local artifacts before reads/writes."""
    if not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9._-]+', source_id):
        raise ValueError('invalid source artifact identity')
    root = Path(root).resolve()
    folders = [paths.source_manifests, paths.source_text, paths.chunks, paths.indexes,
               paths.extraction_events, paths.llm_cache, paths.coverage, paths.input_stage]
    files = [paths.source_manifests / f'{source_id}.json', paths.source_text / f'{source_id}.json',
             paths.chunks / f'{source_id}.json', paths.extraction_events / f'{source_id}-llm-context-request.json',
             *(paths.indexes / name for name in ('wiki.sqlite', 'wiki.sqlite-wal', 'wiki.sqlite-shm', 'wiki.sqlite-journal'))]
    if stream:
        folders.append(paths.source_state)
        files.append(paths.source_state / f'{source_id}.json')
    if score:
        files.append(paths.derived_root / 'score-events.jsonl')
    for path in (*folders, *files):
        relative = safe_path(Path(path).relative_to(root).as_posix())
        _check_local_boundaries(root, relative)


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
        tracked = ref in reader.paths
        if tracked:
            if selection.source_ref is not None and selection.source_ref != ref:
                raise ValueError('tracked source reference is ambiguous')
            canonical_ref = ref
        else:
            if not selection.source_ref:
                raise ContextRequestBlocked('folder_source_revision_unavailable',
                    'Staged RAW requires an explicitly selected approved source page; no Git revision is inferred.')
            canonical_ref = canonical_path(safe_path(selection.source_ref))
            if canonical_ref not in reader.paths or canonical_ref == ref:
                raise ValueError('canonical source page unavailable')
        canonical_producer = policy.owner_of(canonical_ref)
        if policy.connection(canonical_producer, context, canonical_ref, 'interpretation', 'source') != 'approved':
            raise ValueError('canonical source page unauthorized')
        # Qualify and read the approved instruction chain, mandatory references
        # and selected index before opening the staged source. The full task
        # packet is rebuilt later with its explicit context selections.
        preliminary = prepare_folder_packet(root, selection.host, {
            'folder': selection.folder, 'approved_revision': policy.policy_revision,
            'content_revision': policy.policy_revision,
            'task': {'index_path': selection.index_path, 'task_id': 'folder-source-preparation',
                     'goal': 'Qualify context before staged source reading',
                     'output': selection.output_path, 'integrator': 'Authorized local coordinator',
                     'max_bytes': context_max_bytes, 'evidence': [{
                         'path': canonical_ref, 'producer_folder': policy.contexts[canonical_producer]['root'],
                         'reason': 'Selected approved source reference', 'use': 'interpretation',
                         'classification': 'source'}]}})['packet']
        if any(row['path'] == output for row in preliminary['inputs']):
            raise ValueError('output is a mandatory input')
        canonical_document = reader.read(canonical_ref)
        if not tracked:
            fm = canonical_document.get('frontmatter') or {}
            if (fm.get('page_type') != 'source' or not isinstance(fm.get('platform'), str)
                    or not fm['platform'].strip() or not isinstance(fm.get('source_locator'), str)
                    or not fm['source_locator'].strip()):
                raise ValueError('canonical source page lacks platform or locator')
        _check_local_boundaries(root, ref)
        if not candidate.is_file():
            raise ValueError('source is unavailable')
        digest = hashlib.sha256()
        with candidate.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        source_sha = digest.hexdigest()
        if tracked and canonical_document['content_sha256'] != source_sha:
            raise ContextRequestBlocked('folder_source_revision_changed',
                'The staged source differs from its approved Git version; requalify the source before preparing a request.')
        repo_read = None
        if selection.independent_repo is not None:
            from wiki_core.repo_read import read_independent_repo, remote_identity
            chosen = selection.independent_repo
            if (not tracked or not isinstance(chosen, tuple) or len(chosen) != 4
                    or any(not isinstance(item, str) for item in chosen)):
                raise ValueError('invalid repository selection')
            repo_root, identity, revision, repo_path = chosen
            if (not Path(repo_root).is_absolute() or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision)
                    or (selection.folder, Path(repo_root).resolve(), identity, safe_path(repo_path))
                    not in selection.host.independent_repos):
                raise ValueError('repository not bound to this folder')
            fm = canonical_document.get('frontmatter') or {}
            locator = fm.get('source_locator')
            if (fm.get('page_type') != 'source' or fm.get('platform') != 'repo'
                    or not isinstance(locator, str)
                    or (locator if locator == identity else remote_identity(locator)[0]) != identity):
                raise ValueError('repository source page mismatch')
            repo_read = read_independent_repo(Path(repo_root), identity, revision, repo_path)
        from wiki_core.source_manifest import source_origin
        origin = source_origin(str(candidate), root)
        policy.fresh()
        result = {'root': root, 'path': candidate, 'ref': ref, 'policy': policy,
                'context': context, 'hash_sha256': source_sha,
                'reader': reader,
                'folder_selection': selection,
                'context_max_bytes': context_max_bytes,
                'canonical_source_ref': canonical_ref if not tracked else None,
                'packet_source_ref': canonical_ref,
                'authorization': {'version': 'folder/v2', 'folder': selection.folder,
                    'ref': ref, 'producer': producer, 'context_id': context,
                    'policy_revision': policy.policy_revision, 'use': 'interpretation',
                    'classification': 'source', 'source_kind': 'git' if tracked else 'staged_raw',
                    'source_revision': reader.revision if tracked else None,
                    'source_sha256': source_sha, 'source_origin': origin,
                    'canonical_ref': canonical_ref, 'canonical_revision': reader.revision,
                    'canonical_sha256': canonical_document['content_sha256'],
                    'canonical_producer': canonical_producer,
                    'association': 'git_blob_verified' if tracked else 'caller_selected_unverified',
                    'external_origin_verification': 'not_verified', 'external_freshness': 'not_verified'}}
        if repo_read is not None:
            result['independent_repo_content'] = repo_read['text']
            result['authorization']['independent_repo_read'] = {k: v for k, v in repo_read.items() if k != 'text'}
        return result
    except ContextRequestBlocked:
        raise
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
    source_ref = guard['packet_source_ref']
    source_producer = policy.owner_of(source_ref)
    evidence = [{'path': source_ref, 'producer_folder': policy.contexts[source_producer]['root'],
                 'reason': 'Approved source for contextual interpretation', 'use': 'interpretation',
                 'classification': 'source'}]
    for ref in dict.fromkeys(refs):
        ref = safe_path(ref)
        producer = policy.owner_of(ref)
        if ref == source_ref:
            continue
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


def revalidate_folder_capture(guard, manifest, chunks, config):
    """Recompute the deterministic capture before accepting a reported result."""
    from wiki_core.chunking import chunk_text
    from wiki_core.extractors import extract_source
    auth = guard['authorization']
    if (manifest.get('hash_sha256') != auth['source_sha256']
            or manifest.get('source_origin') != auth['source_origin']):
        raise ValueError('folder source identity changed')
    extracted = extract_source(str(guard['path']), str(manifest['source_type']))
    if extracted.warnings:
        raise ValueError('folder source capture incomplete')
    expected = chunk_text(str(manifest['source_id']), extracted.text,
                          int(config.llm.get('chunk_target_tokens', 1200)),
                          int(config.llm.get('chunk_overlap_tokens', 150)))
    keys = ('chunk_id', 'ordinal', 'hash_sha256', 'token_estimate', 'text')
    actual = [tuple(row.get(key) for key in keys) for row in chunks]
    wanted = [tuple(getattr(row, key) for key in keys) for row in expected]
    if actual != wanted:
        raise ValueError('folder capture differs from current source')
