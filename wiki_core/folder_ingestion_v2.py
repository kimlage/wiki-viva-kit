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
    additional_repos: tuple[tuple[str, str, str, str], ...] = ()
    existing_output_sha256: str | None = None


def ingestion_binding_for_authorization(authorization):
    """Bind a source authorization into the packet before any result exists."""
    if (not isinstance(authorization, dict) or authorization.get('version') != 'folder/v2'
            or authorization.get('source_kind') not in ('git', 'staged_raw')):
        raise ValueError('invalid ingestion authorization')
    encoded = json.dumps(authorization, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return {'version': 'folder-ingestion/v2', 'source_kind': authorization['source_kind'],
            'source_authorization_sha256': hashlib.sha256(encoded).hexdigest()}


def host_binding_from_environment(env=None):
    """Load the trusted local host binding independently of an output selection."""
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
    return host


def selection_from_host_environment(folder, index_path, output_path, source_ref=None, env=None, *, independent_repo=None, additional_repos=(), existing_output_sha256=None):
    """Use host startup configuration; the request cannot widen its allowlist."""
    host = host_binding_from_environment(env)
    return FolderIngestionSelection(host, folder, index_path, output_path, source_ref, independent_repo, additional_repos, existing_output_sha256)


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


def additional_repo_selections_for_request(host, folder, authorization):
    """Resolve every additional explicit selection through the trusted host."""
    receipts = authorization.get('independent_repo_additional_reads', []) if isinstance(authorization, dict) else []
    if not isinstance(receipts, list) or len(receipts) > 15:
        raise ValueError('repository binding unavailable')
    return tuple(independent_repo_selection_for_request(host, folder, {'independent_repo_read': row}) for row in receipts)


def _check_local_boundaries(root, ref):
    ref = safe_path(ref)
    cursor = root
    for part in Path(ref).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError('symlink path is unsupported')
        if cursor.is_dir() and os.path.lexists(cursor / '.git'):
            raise ValueError('independent repository requires explicit selection')


def validate_folder_artifact_paths(root, paths, source_id, *, stream=False, score=False, request=None):
    """Fence the existing pipeline's fixed local artifacts before reads/writes."""
    from wiki_core.paths import FolderWikiPaths
    if not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9._-]+', source_id):
        raise ValueError('invalid source artifact identity')
    root = Path(root).resolve()
    if not isinstance(paths, FolderWikiPaths) or paths.root.resolve() != root:
        raise ValueError('folder-scoped artifact namespace required')
    folders = [paths.source_manifests, paths.source_text, paths.chunks,
               paths.extraction_events, paths.llm_cache]
    files = [paths.source_manifests / f'{source_id}.json', paths.source_text / f'{source_id}.json',
             paths.chunks / f'{source_id}.json']
    if request is not None:
        from wiki_core.folder_request_identity_v2 import folder_request_path
        files.append(folder_request_path(paths, request))
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
        existing_hash = selection.existing_output_sha256
        if existing_hash is not None:
            if (not isinstance(existing_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', existing_hash)
                    or output not in reader.paths or reader.blob_size(output) > context_max_bytes):
                raise ValueError('explicit existing output unavailable')
            # Only after the owner/write checks, compare the selected approved
            # complete blob and working copy. Do not discard local edits.
            previous = reader.read(output)
            if (previous['content_sha256'] != existing_hash or not (root / output).is_file()
                    or (root / output).stat().st_size != reader.blob_size(output)
                    or previous['frontmatter'].get('page_type') != 'claim'):
                raise ValueError('existing output differs from selected base')
            with (root / output).open('rb') as stream:
                local_output = stream.read(context_max_bytes + 1)
            if len(local_output) > context_max_bytes or hashlib.sha256(local_output).hexdigest() != existing_hash:
                raise ValueError('existing output differs from selected base')
        elif (output in reader.paths or any(output == path or output.startswith(path + '/')
                                           for path in reader.unsupported_paths)
                or os.path.lexists(root / output)):
            raise ValueError('existing output requires explicit base hash')
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
        repo_reads = []
        if not isinstance(selection.additional_repos, tuple) or len(selection.additional_repos) > 15:
            raise ValueError('invalid repository selections')
        if selection.independent_repo is None and selection.additional_repos:
            raise ValueError('repository selection unavailable')
        if selection.independent_repo is not None:
            from wiki_core.repo_read import read_independent_repo
            from wiki_core.folder_reassessment_v2 import _repository_node_matches
            qualified = []
            for chosen in (selection.independent_repo, *selection.additional_repos):
                if (not tracked or not isinstance(chosen, tuple) or len(chosen) != 4
                        or any(not isinstance(item, str) for item in chosen)):
                    raise ValueError('invalid repository selection')
                repo_root, identity, revision, repo_path = chosen
                resolved_repo_root = Path(repo_root).resolve()
                if (not Path(repo_root).is_absolute() or resolved_repo_root == root
                        or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision)
                        or (selection.folder, resolved_repo_root, identity, safe_path(repo_path))
                        not in selection.host.independent_repos):
                    raise ValueError('repository not bound to this folder')
                if not _repository_node_matches(canonical_document['text'], identity):
                    raise ValueError('repository source page mismatch')
                item = (resolved_repo_root, identity, revision, repo_path)
                if qualified and (item[:3] != qualified[0][:3] or repo_path in [q[3] for q in qualified]):
                    raise ValueError('repository selections must share identity and revision with unique paths')
                qualified.append(item)
            # Qualify every path before reading any independent repository body.
            repo_reads = [read_independent_repo(*item) for item in qualified]
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
        if existing_hash is not None:
            result['authorization']['existing_output_sha256'] = existing_hash
        if repo_reads:
            result['independent_repo_content'] = repo_reads[0]['text']
            result['authorization']['independent_repo_read'] = {k: v for k, v in repo_reads[0].items() if k != 'text'}
            if len(repo_reads) > 1:
                result['independent_repo_additional_content'] = [row['text'] for row in repo_reads[1:]]
                result['authorization']['independent_repo_additional_reads'] = [
                    {k: v for k, v in row.items() if k != 'text'} for row in repo_reads[1:]]
        return result
    except ContextRequestBlocked:
        raise
    except (ValueError, OSError, RuntimeError, TypeError, KeyError, AttributeError):
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
    if selection.existing_output_sha256 is not None:
        evidence.append({'path': selection.output_path, 'producer_folder': selection.folder,
            'reason': 'Explicit whole prior output for review', 'use': 'context',
            'classification': 'context'})
    for ref in dict.fromkeys(refs):
        ref = safe_path(ref)
        producer = policy.owner_of(ref)
        if ref == source_ref or ref == selection.output_path:
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
                        'max_bytes': max_bytes, 'evidence': evidence,
                        'ingestion_binding': ingestion_binding_for_authorization(guard['authorization'])}}
    return prepare_folder_packet(root, selection.host, payload)['packet']


def load_folder_queries(path):
    """Read an explicitly selected bounded JSON query list, without expanding access."""
    from wiki_core.context_selection import strict_json_loads
    with Path(path).open('rb') as stream:
        raw = stream.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('query selection exceeds byte limit')
    queries = strict_json_loads(raw.decode('utf-8'))
    if not isinstance(queries, list) or not 1 <= len(queries) <= 8:
        raise ValueError('one to eight folder queries required')
    return queries


def folder_ingestion_queries(root, guard, packet, queries):
    """Select queries under the same host and current approved folder policy."""
    if queries is None:
        return None
    from wiki_core.folder_coordination_v2 import _bound_policy
    from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2
    selection = guard['folder_selection']
    policy = _bound_policy(root, selection.host, selection.folder, guard['policy'].policy_revision)
    return build_folder_query_packet_v2(root, policy, base_packet=packet, queries=queries)


def revalidate_folder_ingestion_queries(root, guard, packet, queries, expected):
    """Reproduce the complete selection before a persistence boundary."""
    if folder_ingestion_queries(root, guard, packet, queries) != expected:
        raise ValueError('folder query selection changed')


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
