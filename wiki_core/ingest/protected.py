"""Host-bound folder ingestion into a separately routed derived cache.

This is an application boundary, not an operating-system access control list.
Every selected file is checked against the pinned policy before it is opened.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

import yaml

from wiki_core.chunking import chunk_text
from wiki_core.config import config_from_mapping, DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION
from wiki_core.context_packet import build_packet as context_packet, qualify_folder_context
from wiki_core.context_policy import git_file, safe_path
from wiki_core.coordination_context import _policy, ProtectedCoordinationError
from wiki_core.detectors import scan_file, scan_text
from wiki_core.extractors import extract_source
from wiki_core.llm import build_context_request, write_result
from wiki_core.llm.context_pass import (CONTEXT_PASS_SCHEMA_VERSION, canonical_request_text,
    read_matching_result, result_matches_request, request_limits)
from wiki_core.paths import WikiPaths
from wiki_core.repo_read import contains_access_secrets
from wiki_core.source_manifest import (build_manifest, chunk_document, reusable_capture,
    write_manifest, write_source_artifact)
from wiki_core.traversal import (PROTECTED_ARTIFACT_COMPONENT, require_wiki_boundaries,
    require_wiki_path)
from wiki_core.git_env import local_git_environment, local_git_executable


class ProtectedPartialError(ValueError):
    """A failed operation may have retained some artifacts; inspect before retry."""


def _authority(root, binding, context_id, approved_revision, entry_folder, entry_index, budget):
    root = Path(root).resolve(strict=True)
    policy = _policy(root, binding, context_id, approved_revision)
    if getattr(policy, 'format_version', None) != 'folder':
        raise ProtectedCoordinationError('coordination_policy_unavailable')
    qualify_folder_context(root, policy, context_id, entry_folder, entry_index, budget)
    raw = yaml.safe_load(git_file(root, policy.policy_revision, 'wiki.config.yaml'))
    config = config_from_mapping(raw)
    configured = safe_path(config.paths['derived_root'])
    from wiki_core.traversal import is_protected_artifact
    if is_protected_artifact(Path(configured)):
        raise ValueError('invalid protected cache configuration')
    config = replace(config, paths={**config.paths,
        'derived_root': configured + '/' + PROTECTED_ARTIFACT_COMPONENT})
    ignored = subprocess.run([local_git_executable(), '-C', str(root), 'check-ignore',
        '--no-index', '-q', '--', config.paths['derived_root'] + '/_probe_'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=local_git_environment())
    if ignored.returncode != 0:
        raise ValueError('protected cache must be excluded from Git')
    return root, policy, config, WikiPaths(root, config)


def _allowed(root, policy, context_id, path, action):
    path = Path(path)
    try:
        ref = safe_path(path.relative_to(root).as_posix())
        owner = policy.owner_of(ref)
        if action == 'write':
            allowed = owner == context_id and policy.permits(context_id, 'write', ref)
        else:
            allowed = policy.connection(owner, context_id, ref, 'interpretation', 'artifact') == 'approved'
        if not allowed:
            raise ValueError('artifact unavailable')
        require_wiki_boundaries(root, files=(path,))
    except (ValueError, OSError, KeyError):
        raise ValueError('artifact unavailable') from None
    return path


def _source(root, policy, context_id, source_ref):
    ref = safe_path(source_ref)
    if contains_access_secrets(ref):
        raise ValueError('source unavailable')
    owner = policy.owner_of(ref)
    if policy.connection(owner, context_id, ref, 'interpretation', 'source') != 'approved':
        raise ValueError('source unavailable')
    path = require_wiki_path(root, ref)
    if not path.is_file():
        raise ValueError('source unavailable')
    if path.stat().st_size > 16_000_000:
        raise ValueError('source exceeds protected limit')
    return path


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _capture(root, policy, context_id, source_ref, source_context, config):
    if not isinstance(source_context, str) or contains_access_secrets(source_context):
        raise ValueError('source context unavailable')
    source = _source(root, policy, context_id, source_ref)
    digest = _hash(source)
    manifest = build_manifest(str(source), source_context, root=root)
    if manifest.get('hash_sha256') != digest:
        raise ValueError('source changed')
    extracted = extract_source(str(source), str(manifest['source_type']))
    if extracted.warnings:
        raise ValueError('source extraction requires review')
    if any(f.category == 'secret' for f in [*scan_file(source), *scan_text(extracted.text)]) \
            or contains_access_secrets([extracted.text, extracted.units]):
        raise ValueError('source unavailable')
    if _hash(_source(root, policy, context_id, source_ref)) != digest:
        raise ValueError('source changed')
    chunks = [{'chunk_id': c.chunk_id, 'ordinal': c.ordinal, 'hash_sha256': c.hash_sha256,
               'token_estimate': c.token_estimate, 'text': c.text}
              for c in chunk_text(str(manifest['source_id']), extracted.text,
                  int(config.llm.get('chunk_target_tokens', 1200)),
                  int(config.llm.get('chunk_overlap_tokens', 150)))]
    if not chunks:
        raise ValueError('empty source requires explicit review')
    return source, digest, manifest, extracted, chunks


def _request_identity(request):
    rows = request.get('chunks')
    if not isinstance(rows, list) or not rows or any(not isinstance(x, dict) for x in rows):
        raise ValueError('request unavailable')
    envelope = {k: v for k, v in request.items() if k not in
        ('protected_request_id', 'byte_accounting', 'pending_llm_calls', 'cached_calls', 'chunks')}
    envelope['chunks'] = [{k: v for k, v in row.items() if k not in
        ('result_exists', 'result_source_id', 'result_chunk_id')} for row in rows]
    return hashlib.sha256(canonical_request_text(envelope).encode()).hexdigest()


def _request_path(paths, source_id, request_id):
    if not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,511}', source_id):
        raise ValueError('request unavailable')
    if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{64}', request_id):
        raise ValueError('request unavailable')
    source = hashlib.sha256(source_id.encode()).hexdigest()
    return paths.extraction_events / f'protected-{source}-{request_id}-llm-context-request.json'


def _read_json(root, policy, context_id, path):
    _allowed(root, policy, context_id, path, 'read')
    from wiki_core.context_selection import strict_json_loads
    with path.open('rb') as stream:
        data = stream.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError('artifact unavailable')
    return strict_json_loads(data.decode('utf-8'))


def _write_once(root, policy, context_id, path, value):
    _allowed(root, policy, context_id, path, 'write')
    _allowed(root, policy, context_id, path, 'read')
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='utf-8') as stream:
            stream.write(payload)
    except FileExistsError:
        if path.is_symlink() or _read_json(root, policy, context_id, path) != value:
            raise ValueError('existing artifact differs; preserved') from None


def prepare(root, binding, *, context_id, approved_revision, entry_folder, entry_index,
            source_ref, source_context, context_max_bytes=100_000, request_max_bytes=1_000_000):
    """Capture one authorized source and emit its bound contextual request."""
    request_limits(context_max_bytes, request_max_bytes)
    root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
        entry_folder, entry_index, context_max_bytes)
    source, source_digest, manifest, extracted, chunks = _capture(root, policy, context_id,
        source_ref, source_context, config)
    packet = context_packet(root, policy, context_id, approved_revision, [], context_max_bytes,
        task_id=str(manifest['source_id']), goal='Interpret the authorized selected source',
        output='Contextual source interpretation', integrator=context_id,
        entry_folder=entry_folder, entry_index=entry_index,
        omissions=['linked sources not inspected'])
    auth = {'ref': source_ref, 'producer': policy.owner_of(source_ref), 'context_id': context_id,
        'policy_revision': approved_revision, 'use': 'interpretation', 'classification': 'source'}
    prompt = str(config.llm.get('prompt_versions', {}).get('context_deep_read', DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION))
    profile = str(config.llm.get('default_model_profile', 'deep_context'))
    # An empty temporary cache avoids opening any stored cache before the exact
    # keys have been checked against the policy.
    with tempfile.TemporaryDirectory(prefix='wiki-protected-empty-') as empty:
        request = build_context_request(manifest, chunks, Path(empty), prompt,
            CONTEXT_PASS_SCHEMA_VERSION, profile, block_context_package=packet,
            context_max_bytes=context_max_bytes, request_max_bytes=request_max_bytes,
            source_authorization=auth)
    request_id = _request_identity(request)
    request['protected_request_id'] = request_id
    source_id = str(manifest['source_id'])
    artifact_paths = [paths.source_manifests / f'{source_id}.json', paths.source_text / f'{source_id}.json',
        paths.chunks / f'{source_id}.json', _request_path(paths, source_id, request_id)]
    for path in artifact_paths:
        _allowed(root, policy, context_id, path, 'read')
        _allowed(root, policy, context_id, path, 'write')
    for row in request['chunks']:
        path = paths.llm_cache / (row['cache_key'] + '.json')
        _allowed(root, policy, context_id, path, 'read')
        _allowed(root, policy, context_id, path, 'write')
    # Revalidate the current authority and source before the first side effect.
    root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
        entry_folder, entry_index, context_max_bytes)
    if _hash(_source(root, policy, context_id, source_ref)) != source_digest:
        raise ValueError('source changed')
    capture = reusable_capture(paths, manifest, extracted, chunks, list(extracted.warnings),
                               max_bytes=request_max_bytes * 4 + 65536, allow_protected=True)
    def revalidate(path):
        current_root, current_policy, _config, _paths = _authority(root, binding, context_id,
            approved_revision, entry_folder, entry_index, context_max_bytes)
        if _hash(_source(current_root, current_policy, context_id, source_ref)) != source_digest:
            raise ValueError('source changed')
        _allowed(current_root, current_policy, context_id, path, 'read')
        _allowed(current_root, current_policy, context_id, path, 'write')
    try:
        if not capture:
            for directory in (paths.source_manifests, paths.source_text, paths.chunks):
                directory.mkdir(parents=True, exist_ok=True)
            revalidate(artifact_paths[0])
            write_manifest(manifest, paths.source_manifests, preserve_existing=True)
            revalidate(artifact_paths[1])
            write_source_artifact(paths.source_text / f'{source_id}.json', {
                'schema_version': 'wiki_extracted_text.v1', 'source_id': source_id, 'source_uri': str(source),
                'source_type': manifest['source_type'], 'context': source_context, 'warnings': list(extracted.warnings),
                'text_characters': len(extracted.text), 'units': extracted.units}, preserve_existing=True)
            revalidate(artifact_paths[2])
            write_source_artifact(paths.chunks / f'{source_id}.json',
                chunk_document(manifest, chunks, warnings=list(extracted.warnings)), preserve_existing=True)
        revalidate(artifact_paths[3])
        _write_once(root, policy, context_id, _request_path(paths, source_id, request_id), request)
    except (ValueError, OSError) as exc:
        raise ProtectedPartialError('partial effects may exist; inspect before retry') from exc
    return {'source_id': source_id, 'request_id': request_id, 'request': request,
            'coverage': 'selected source only; linked sources not inspected'}


def _open_bound(root, binding, *, context_id, approved_revision, entry_folder, entry_index,
                source_ref, source_id, request_id, context_max_bytes, request_max_bytes):
    root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
        entry_folder, entry_index, context_max_bytes)
    source = _source(root, policy, context_id, source_ref)
    digest = _hash(source)
    path = _request_path(paths, source_id, request_id)
    request = _read_json(root, policy, context_id, path)
    if (not isinstance(request, dict) or request.get('source_id') != source_id
            or request.get('protected_request_id') != request_id
            or _request_identity(request) != request_id
            or request.get('source_hash_sha256') != digest
            or request.get('request_limits') != request_limits(context_max_bytes, request_max_bytes)):
        raise ValueError('request unavailable')
    auth = request.get('source_authorization')
    if auth != {'ref': source_ref, 'producer': policy.owner_of(source_ref), 'context_id': context_id,
                'policy_revision': approved_revision, 'use': 'interpretation', 'classification': 'source'}:
        raise ValueError('request unavailable')
    packet = request.get('block_context_package')
    if not isinstance(packet, dict):
        raise ValueError('request unavailable')
    current = context_packet(root, policy, context_id, approved_revision, [], context_max_bytes,
        task_id=source_id, goal='Interpret the authorized selected source',
        output='Contextual source interpretation', integrator=context_id,
        entry_folder=entry_folder, entry_index=entry_index,
        omissions=['linked sources not inspected'])
    if current != packet:
        raise ValueError('request authority changed')
    # A request filename and digest bind bytes; they do not prove that those
    # chunks came from the selected source. Reconstruct the selected capture.
    _source_path, observed_hash, manifest, _extracted, chunks = _capture(root, policy, context_id,
        source_ref, request.get('source_context'), config)
    if observed_hash != digest or manifest.get('source_id') != source_id:
        raise ValueError('request source changed')
    prompt = str(config.llm.get('prompt_versions', {}).get('context_deep_read', DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION))
    profile = str(config.llm.get('default_model_profile', 'deep_context'))
    with tempfile.TemporaryDirectory(prefix='wiki-protected-empty-') as empty:
        rebuilt = build_context_request(manifest, chunks, Path(empty), prompt,
            CONTEXT_PASS_SCHEMA_VERSION, profile, block_context_package=current,
            context_max_bytes=context_max_bytes, request_max_bytes=request_max_bytes,
            source_authorization=auth)
    if _request_identity(rebuilt) != request_id:
        raise ValueError('request source changed')
    return root, policy, config, paths, request, digest


def record(root, binding, *, context_id, approved_revision, entry_folder, entry_index,
           source_ref, source_id, request_id, results,
           context_max_bytes=100_000, request_max_bytes=1_000_000):
    """Record host-supplied result objects against the exact retained request."""
    options = dict(context_id=context_id, approved_revision=approved_revision,
        entry_folder=entry_folder, entry_index=entry_index, source_ref=source_ref,
        source_id=source_id, request_id=request_id, context_max_bytes=context_max_bytes,
        request_max_bytes=request_max_bytes)
    root, policy, config, paths, request, digest = _open_bound(root, binding, **options)
    if not isinstance(results, list) or not results or contains_access_secrets(results):
        raise ValueError('result unavailable')
    rows = request['chunks']
    keys = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError('result unavailable')
        matches = [row for row in rows if result_matches_request(result, request, row, recording=True)]
        if len(matches) != 1 or result.get('cache_key') in keys:
            raise ValueError('result unavailable')
        key = result['cache_key']
        keys.append(key)
        target = paths.llm_cache / (key + '.json')
        _allowed(root, policy, context_id, target, 'read')
        _allowed(root, policy, context_id, target, 'write')
    from wiki_core.llm.context_pass import validate_result
    if any(validate_result(result) for result in results):
        raise ValueError('result unavailable')
    written = []
    for result in results:
        try:
            root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
            if current != request or current_digest != digest:
                raise ValueError('request authority changed')
            target = paths.llm_cache / (result['cache_key'] + '.json')
            _allowed(root, policy, context_id, target, 'read')
            _allowed(root, policy, context_id, target, 'write')
            written.append(write_result(paths.llm_cache, result, preserve_existing=True))
        except (ValueError, OSError) as exc:
            raise ProtectedPartialError('partial effects may exist; inspect before retry') from exc
    return {'recorded': len(written), 'request_id': request_id}


def consolidate(root, binding, *, context_id, approved_revision, entry_folder, entry_index,
                source_ref, source_id, request_id, source_page, event_target, date,
                candidates=(), context_max_bytes=100_000, request_max_bytes=1_000_000):
    """Prepare an event and packet; incorporation and review remain separate."""
    from wiki_core.consolidate import aggregate_results, build_event_markdown, build_packet
    options = dict(context_id=context_id, approved_revision=approved_revision,
        entry_folder=entry_folder, entry_index=entry_index, source_ref=source_ref,
        source_id=source_id, request_id=request_id, context_max_bytes=context_max_bytes,
        request_max_bytes=request_max_bytes)
    root, policy, config, paths, request, digest = _open_bound(root, binding, **options)
    refs = [safe_path(x) for x in candidates]
    if len(refs) != len(set(refs)) or len(refs) > 128:
        raise ValueError('candidate unavailable')
    source_page = safe_path(source_page)
    event_target = safe_path(event_target)
    if contains_access_secrets([source_page, event_target, refs]):
        raise ValueError('output unavailable')
    if not (root / event_target).is_relative_to(root / config.paths['memory_root']) or not event_target.endswith('.md'):
        raise ValueError('event target unavailable')
    for ref in [source_page, *refs]:
        _allowed(root, policy, context_id, root / ref, 'read')
    target = _allowed(root, policy, context_id, root / event_target, 'write')
    _allowed(root, policy, context_id, target, 'read')
    packet_path = paths.extraction_events / f'protected-{hashlib.sha256(source_id.encode()).hexdigest()}-{request_id}-integration-packet.json'
    _allowed(root, policy, context_id, packet_path, 'read')
    _allowed(root, policy, context_id, packet_path, 'write')
    for row in request['chunks']:
        cache_path = paths.llm_cache / (row['cache_key'] + '.json')
        _allowed(root, policy, context_id, cache_path, 'read')
        if read_matching_result(paths.llm_cache, request, row, root=root) is None:
            raise ValueError('result unavailable')
    aggregated = aggregate_results(request, paths.llm_cache, root=root)
    aggregated['folder_request_id'] = request_id
    aggregated['source_hash_sha256'] = digest
    packet = build_packet(aggregated, root, config, paths, candidates=refs)
    markdown = build_event_markdown(aggregated, config=config, context=request['source_context'],
        date=date, source_page=source_page, event_dir=target.parent, root=root,
        impact=dict(packet.get('impact') or {}))
    if contains_access_secrets([packet, markdown]):
        raise ValueError('output unavailable')
    root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
    if current != request or current_digest != digest:
        raise ValueError('request authority changed')
    _allowed(root, policy, context_id, target, 'write')
    _allowed(root, policy, context_id, target, 'read')
    if target.exists():
        raise ValueError('event already exists; preserved')
    try:
        _write_once(root, policy, context_id, packet_path, packet)
        root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
        if current != request or current_digest != digest:
            raise ValueError('request authority changed')
        _allowed(root, policy, context_id, target, 'write')
        _allowed(root, policy, context_id, target, 'read')
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as stream:
            stream.write(markdown)
    except (ValueError, OSError) as exc:
        raise ProtectedPartialError('partial effects may exist; inspect before retry') from exc
    return {'event': event_target, 'request_id': request_id,
            'coverage': 'explicit candidates only; linked sources not inspected',
            'integration': 'pending review and incorporation'}
