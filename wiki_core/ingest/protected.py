"""Host-bound folder ingestion into a separately routed derived cache.

This is an application boundary, not an operating-system access control list.
Every selected file is checked against the pinned policy before it is opened.
"""
from __future__ import annotations

import hashlib
import datetime as dt
import json
import mimetypes
import re
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

import yaml

from wiki_core.chunking import chunk_text
from wiki_core.config import config_from_mapping
from wiki_core.context_packet import build_packet as context_packet, qualify_folder_context
from wiki_core.context_policy import git_file, safe_path
from wiki_core.coordination_context import _policy, ProtectedCoordinationError
from wiki_core.detectors import scan_text
from wiki_core.extractors.text import extract_captured
from wiki_core.llm import build_context_request
from wiki_core.llm.context_pass import (CONTEXT_PASS_SCHEMA_VERSION, canonical_request_text,
    enforce_request_budget, result_matches_request, request_limits, require_approved_prompt_version)
from wiki_core.paths import WikiPaths
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repo_host import (selected_repository, authorize_repository_event,
    authorize_repository_grant, _selection_ids)
from wiki_core.source_manifest import classify_source, source_id_for, source_origin, chunk_document
from wiki_core.traversal import (PROTECTED_ARTIFACT_COMPONENT, require_wiki_boundaries,
    require_wiki_path)
from wiki_core.git_env import local_git_environment, local_git_executable


class ProtectedPartialError(ValueError):
    """A failed operation may have retained some artifacts; inspect before retry."""


FOLDER_PROMPT_VERSION = 'v5'


def _format_omissions(source_ref):
    suffix = Path(source_ref).suffix.lower()
    limitations = {
        '.pdf': 'PDF images and scanned text were not inspected; OCR was not performed.',
        '.docx': 'Document headers, footers, images and embedded objects were not inspected.',
        '.xlsx': 'Spreadsheet drawings, embedded objects, macro behavior and formula recalculation were not inspected.',
        '.eml': 'Email visual rendering and external resources were not inspected.',
    }
    return [limitations[suffix]] if suffix in limitations else []


def _authority(root, binding, context_id, approved_revision, entry_folder, entry_index, budget,
               artifact_context=None):
    root = Path(root).resolve(strict=True)
    policy = _policy(root, binding, context_id, approved_revision)
    if getattr(policy, 'format_version', None) != 'folder':
        raise ProtectedCoordinationError('coordination_policy_unavailable')
    actor = context_id if artifact_context is None else artifact_context
    _policy(root, binding, actor, approved_revision)
    lineage = policy.lineage(context_id)
    if actor not in [row['id'] for row in lineage]:
        raise ValueError('integrator requires an authorized ancestor context')
    readers = () if actor == context_id else (actor,)
    qualify_folder_context(root, policy, context_id, entry_folder, entry_index, budget,
                           additional_readers=readers)
    raw = yaml.safe_load(git_file(root, policy.policy_revision, 'wiki.config.yaml'))
    config = config_from_mapping(raw)
    configured_prompts = (raw.get('llm') or {}).get('prompt_versions') or {}
    if 'context_deep_read' not in configured_prompts:
        config = replace(config, llm={**config.llm, 'prompt_versions': {
            **config.llm.get('prompt_versions', {}), 'context_deep_read': FOLDER_PROMPT_VERSION}})
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
        require_wiki_boundaries(root, files=(path,), allow_protected=True)
    except (ValueError, OSError, KeyError):
        raise ValueError('artifact unavailable') from None
    return path


def _source(root, policy, context_id, source_ref, artifact_context=None):
    ref = safe_path(source_ref)
    if contains_access_secrets(ref):
        raise ValueError('source unavailable')
    owner = policy.owner_of(ref)
    actor = context_id if artifact_context is None else artifact_context
    for reader in {context_id, actor}:
        if policy.connection(owner, reader, ref, 'interpretation', 'source') != 'approved':
            raise ValueError('source unavailable')
    path = require_wiki_path(root, ref)
    if not path.is_file():
        raise ValueError('source unavailable')
    if path.stat().st_size > 16_000_000:
        raise ValueError('source exceeds protected limit')
    return path


def _hash(path, policy):
    policy.fresh()
    digest = hashlib.sha256()
    total = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            total += len(block)
            if total > 16_000_000:
                raise ValueError('source exceeds protected limit')
            digest.update(block)
    policy.fresh()
    return digest.hexdigest()


def _capture(root, policy, context_id, source_ref, source_context, config, artifact_context=None):
    if (not isinstance(source_context, str) or not source_context.strip() or len(source_context) > 1024
            or contains_access_secrets(source_context)):
        raise ValueError('source context unavailable')
    source = _source(root, policy, context_id, source_ref, artifact_context)
    source_type = classify_source(str(source))
    supported = {'.md', '.markdown', '.txt', '.csv', '.tsv', '.xlsx', '.docx', '.eml', '.pdf'}
    if source.suffix.lower() not in supported:
        raise ValueError('source format requires an authorized adapter')
    # Capture once into memory. Do not reopen the path inside format helpers:
    # the trusted ref may be revoked between separate reads.
    policy.fresh()
    with source.open('rb') as stream:
        data = stream.read(16_000_001)
    policy.fresh()
    if len(data) > 16_000_000:
        raise ValueError('source unavailable')
    digest = hashlib.sha256(data).hexdigest()
    extracted = extract_captured(str(source), source_type, data)
    policy.fresh()
    manifest = {'schema_version': 'wiki_source_manifest.v1', 'source_uri': str(source),
        'source_origin': source_origin(str(source), root), 'source_type': source_type,
        'context': source_context, 'captured_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'risk_level': 'medium' if source_type in {'pdf', 'spreadsheet', 'document', 'email'} else 'low', 'visibility_initial': 'private_self',
        'privacy_policy': 'extract_private_operational_context_without_access_secrets',
        'absolute_path': str(source), 'exists': True, 'mime_type': mimetypes.guess_type(str(source))[0],
        'source_id': source_id_for(str(source), digest, root=root), 'hash_sha256': digest, 'size_bytes': len(data),
        'extraction_limitations': _format_omissions(source_ref),
        'extraction_complete': not bool(_format_omissions(source_ref))}
    if any(f.category == 'secret' for f in scan_text(extracted.text)) \
            or contains_access_secrets([extracted.text, extracted.units]):
        raise ValueError('source unavailable')
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


def _validate_source_context(extracted, projected):
    if extracted.text.startswith('---\n') or extracted.text.startswith('---\r\n'):
        from wiki_core.context_selection import _metadata
        source_meta = _metadata({'text': extracted.text})
        for key, selected in (('config_ref', projected.get('source_config')),
                              ('input_channel_ref', projected.get('input_channel'))):
            declared = source_meta.get(key)
            if declared and (not selected or declared not in (selected.get('path'), selected.get('page_id'))):
                raise ValueError('source configuration requires explicit qualification')
        if source_meta.get('perspectives_required') and source_meta['perspectives_required'] != projected['perspectives_required']:
            raise ValueError('source perspectives require explicit qualification')


def _request_path(paths, source_id, request_id, repository_context=None):
    if not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,511}', source_id):
        raise ValueError('request unavailable')
    if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{64}', request_id):
        raise ValueError('request unavailable')
    source = hashlib.sha256(source_id.encode()).hexdigest()
    if repository_context is None:
        selection = ''
    elif isinstance(repository_context, list):
        selection = hashlib.sha256(canonical_request_text(
            [row['host_binding_digest'] for row in repository_context]).encode()).hexdigest() + '-'
    else:
        selection = repository_context['host_binding_digest'] + '-'
    return paths.extraction_events / f'protected-{source}-{selection}{request_id}-llm-context-request.json'


def _repository(binding, policy, context_id, actor, selection):
    if selection is None:
        return None
    ids = _selection_ids(selection)
    # Qualify every requested grant before opening any selected Git repository.
    for item in ids:
        authorize_repository_grant(binding, policy, context_id, actor, item)
    rows = [selected_repository(binding, policy, context_id, actor, item) for item in ids]
    return rows[0] if isinstance(selection, str) else rows


def _perspectives(policy, refs, required, optional):
    """Resolve explicit paths for configured lenses; paths alone grant nothing."""
    if (not isinstance(required, list) or not isinstance(optional, list)
            or any(not isinstance(item, str) or not item for item in required + optional)
            or len(set(required + optional)) != len(required + optional)):
        raise ValueError('perspective configuration unavailable')
    refs = {} if refs is None else refs
    if (not isinstance(refs, dict) or len(refs) > 128
            or set(refs) - set(required + optional) or set(required) - set(refs)):
        raise ValueError('perspective selection unavailable')
    paths = {name: safe_path(refs[name]) for name in sorted(refs)}
    if len(set(paths.values())) != len(paths) or contains_access_secrets(paths):
        raise ValueError('perspective selection unavailable')
    evidence = [{'ref': path, 'producer': policy.owner_of(path),
        'reason': 'Configured interpretation perspective', 'use': 'interpretation',
        'classification': 'context'} for path in paths.values()]
    return required, [name for name in optional if name in paths], paths, evidence


def _check_perspective_packet(packet, paths):
    from wiki_core.frontmatter import parse_frontmatter
    for name, path in paths.items():
        selected = [row for row in packet['inputs'] if row['ref'] == path]
        if not selected:
            raise ValueError('perspective unavailable')
        frontmatter, _ = parse_frontmatter(selected[-1]['text'])
        if frontmatter.get('page_id') != name or frontmatter.get('page_type') != 'perspective':
            raise ValueError('perspective unavailable')


def _selected_packet(root, policy, config, context_id, actor, revision, folder, index,
                     budget, task_id, selection, perspective_refs, source_ref):
    from wiki_core.ingest.explicit_context import (explicit_ingestion_evidence,
        resolve_explicit_ingestion_context, _selection)
    selection = _selection(selection)
    evidence = explicit_ingestion_evidence(policy, selection)
    def build(rows, omissions):
        return context_packet(root, policy, context_id, revision, rows, budget,
            task_id=task_id, goal='Interpret the authorized selected source',
            output='Contextual source interpretation', integrator=actor,
            entry_folder=folder, entry_index=index,
            additional_readers=() if actor == context_id else (actor,), omissions=omissions)
    preliminary = build(evidence, [])
    projected = resolve_explicit_ingestion_context(preliminary, selection, config)
    required, optional, paths, lenses = _perspectives(policy, perspective_refs,
        projected['perspectives_required'], projected['perspectives_optional'])
    optional_gaps = ['Optional perspective ' + item + ' not selected.'
                     for item in projected['perspectives_optional'] if item not in paths]
    format_gaps = _format_omissions(source_ref)
    packet = build(evidence + lenses, projected['context_omissions'] + optional_gaps + format_gaps)
    projected = resolve_explicit_ingestion_context(packet, selection, config)
    projected['context_omissions'] += optional_gaps + format_gaps
    _check_perspective_packet(packet, paths)
    return packet, projected, selection, required, optional, paths


def _read_json(root, policy, context_id, path, *, max_bytes=2_000_000):
    _allowed(root, policy, context_id, path, 'read')
    from wiki_core.context_selection import strict_json_loads
    policy.fresh()
    with path.open('rb') as stream:
        data = stream.read(max_bytes + 1)
    policy.fresh()
    if len(data) > max_bytes:
        raise ValueError('artifact unavailable')
    return strict_json_loads(data.decode('utf-8'))


def _source_page(root, policy, context_id, config, ref, *, selected_digest=None):
    """Read only an explicitly selected, authorized canonical source page."""
    from wiki_core.context_selection import _metadata
    ref = safe_path(ref)
    path = root / ref
    if (path.suffix.lower() != '.md' or not path.is_relative_to(root / config.paths['memory_root'])):
        raise ValueError('source page unavailable')
    _allowed(root, policy, context_id, path, 'read')
    require_wiki_path(root, ref)
    policy.fresh()
    with path.open('rb') as stream:
        raw = stream.read(1_000_001)
    policy.fresh()
    if len(raw) > 1_000_000:
        raise ValueError('source page unavailable')
    text = raw.decode('utf-8')
    if contains_access_secrets(text):
        raise ValueError('source page unavailable')
    meta = _metadata({'text': text})
    if (meta.get('page_type') != 'source' or not isinstance(meta.get('page_id'), str)
            or not meta['page_id'].strip()):
        raise ValueError('source page unavailable')
    digest = hashlib.sha256(raw).hexdigest()
    if selected_digest is not None and digest != selected_digest:
        raise ValueError('source page changed')
    if selected_digest is None and any(meta.get(key) for key in ('config_ref', 'input_channel_ref', 'perspectives_required')):
        raise ValueError('source configuration requires explicit qualification')
    return digest


def _capture_matches(root, policy, context_id, paths, manifest, extracted, chunks):
    source_id = manifest['source_id']
    files = [paths.source_manifests / f'{source_id}.json', paths.source_text / f'{source_id}.json',
             paths.chunks / f'{source_id}.json']
    for path in files:
        _allowed(root, policy, context_id, path, 'read')
    present = [path.exists() for path in files]
    if not any(present):
        return False
    if not all(present):
        raise ValueError('existing source capture incomplete; preserved')
    old_manifest, old_text, old_chunks = [_read_json(root, policy, context_id, p, max_bytes=20_000_000) for p in files]
    limitations = _format_omissions(manifest['source_uri'])
    expected = chunk_document(manifest, chunks, warnings=limitations)
    expected['extraction_limitations'] = limitations
    if (not all(isinstance(item, dict) for item in (old_manifest, old_text, old_chunks))
            or any(old_manifest.get(k) != manifest.get(k) for k in
                   ('schema_version', 'source_id', 'source_origin', 'source_type', 'hash_sha256',
                    'extraction_complete', 'extraction_limitations'))
            or any(old_chunks.get(k) != expected.get(k) for k in
                   ('schema_version', 'source_id', 'source_hash_sha256', 'source_origin_id', 'extraction_complete',
                    'extraction_limitations', 'chunks'))
            or old_text.get('schema_version') != 'wiki_extracted_text.v1'
            or old_text.get('source_id') != source_id or old_text.get('source_type') != manifest.get('source_type')
            or old_text.get('warnings') != limitations or old_text.get('units') != extracted.units
            or old_text.get('text_characters') != len(extracted.text)):
        raise ValueError('existing source capture differs; preserved')
    return True


def _json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n'


def _write_once(root, policy, context_id, path, value, *, compact=False):
    _allowed(root, policy, context_id, path, 'write')
    _allowed(root, policy, context_id, path, 'read')
    payload = canonical_request_text(value) if compact else _json_text(value)
    policy.fresh()
    path.parent.mkdir(parents=True, exist_ok=True)
    policy.fresh()
    try:
        policy.fresh()
        with path.open('x', encoding='utf-8') as stream:
            stream.write(payload)
        policy.fresh()
    except FileExistsError:
        if path.is_symlink() or _read_json(root, policy, context_id, path,
                max_bytes=max(2_000_000, len(payload.encode('utf-8')))) != value:
            raise ValueError('existing artifact differs; preserved') from None


def prepare(root, binding, *, context_id, approved_revision, entry_folder, entry_index,
            source_ref, source_context, context_max_bytes=100_000, request_max_bytes=1_000_000,
            artifact_context=None, perspective_refs=None, context_selection=None, repository_selection=None):
    """Capture one authorized source and emit its bound contextual request."""
    request_limits(context_max_bytes, request_max_bytes)
    actor = context_id if artifact_context is None else artifact_context
    root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
        entry_folder, entry_index, context_max_bytes, actor)
    prompt = str(config.llm.get('prompt_versions', {}).get('context_deep_read', FOLDER_PROMPT_VERSION))
    require_approved_prompt_version(prompt, folder=True)
    _, projected, selection, required, optional, selected_perspectives = _selected_packet(
        root, policy, config, context_id, actor, approved_revision, entry_folder, entry_index,
        context_max_bytes, 'source-selection-preflight', context_selection, perspective_refs, source_ref)
    repository_context = _repository(binding, policy, context_id, actor, repository_selection)
    source, source_digest, manifest, extracted, chunks = _capture(root, policy, context_id,
        source_ref, source_context, config, actor)
    _validate_source_context(extracted, projected)
    packet, projected, selection, required, optional, selected_perspectives = _selected_packet(
        root, policy, config, context_id, actor, approved_revision, entry_folder, entry_index,
        context_max_bytes, str(manifest['source_id']), context_selection, perspective_refs, source_ref)
    auth = {'ref': source_ref, 'producer': policy.owner_of(source_ref), 'context_id': context_id,
        'policy_revision': approved_revision, 'use': 'interpretation', 'classification': 'source',
        'artifact_context': actor, 'context_selection': selection,
        'context_associations': {key: projected[key] for key in ('source_page_association',
            'source_config_association', 'input_channel_association')}}
    if selected_perspectives:
        auth['perspective_refs'] = selected_perspectives
    profile = str(config.llm.get('default_model_profile', 'deep_context'))
    # An empty temporary cache avoids opening any stored cache before the exact
    # keys have been checked against the policy.
    with tempfile.TemporaryDirectory(prefix='wiki-protected-empty-') as empty:
        request = build_context_request(manifest, chunks, Path(empty), prompt,
            CONTEXT_PASS_SCHEMA_VERSION, profile, block_context_package=packet,
            perspectives_required=required, perspectives_optional=optional,
            **{key: projected[key] for key in ('root_entity', 'input_channel', 'quadrant_map',
               'quadrant_semantics', 'quadrant_boundary_rule', 'target_pages', 'input_stage_status')},
            context_max_bytes=context_max_bytes, request_max_bytes=request_max_bytes,
            source_authorization=auth, repository_context=repository_context)
    request_id = _request_identity(request)
    request['protected_request_id'] = request_id
    enforce_request_budget(request, context_max_bytes=context_max_bytes, request_max_bytes=request_max_bytes)
    if len(canonical_request_text(request).encode('utf-8')) > 2_000_000:
        raise ValueError('request exceeds protected retention limit')
    source_id = str(manifest['source_id'])
    limitations = _format_omissions(source_ref)
    text_document = {'schema_version': 'wiki_extracted_text.v1', 'source_id': source_id, 'source_uri': str(source),
        'source_type': manifest['source_type'], 'context': source_context, 'warnings': limitations + list(extracted.warnings),
        'text_characters': len(extracted.text), 'units': extracted.units}
    chunks_document = chunk_document(manifest, chunks, warnings=limitations + list(extracted.warnings))
    chunks_document['extraction_limitations'] = limitations
    if any(len(_json_text(value).encode('utf-8')) > 20_000_000
           for value in (manifest, text_document, chunks_document)):
        raise ValueError('capture exceeds protected retention limit')
    artifact_paths = [paths.source_manifests / f'{source_id}.json', paths.source_text / f'{source_id}.json',
        paths.chunks / f'{source_id}.json', _request_path(paths, source_id, request_id, repository_context)]
    for path in artifact_paths:
        _allowed(root, policy, actor, path, 'read')
        _allowed(root, policy, actor, path, 'write')
    for row in request['chunks']:
        path = paths.llm_cache / (row['cache_key'] + '.json')
        _allowed(root, policy, actor, path, 'read')
        _allowed(root, policy, actor, path, 'write')
    # Revalidate the current authority and source before the first side effect.
    root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
        entry_folder, entry_index, context_max_bytes, actor)
    if _hash(_source(root, policy, context_id, source_ref, actor), policy) != source_digest:
        raise ValueError('source changed')
    if _repository(binding, policy, context_id, actor, repository_selection) != repository_context:
        raise ValueError('repository selection changed')
    capture = _capture_matches(root, policy, actor, paths, manifest, extracted, chunks)
    def revalidate(path):
        current_root, current_policy, _config, _paths = _authority(root, binding, context_id,
            approved_revision, entry_folder, entry_index, context_max_bytes, actor)
        if _hash(_source(current_root, current_policy, context_id, source_ref, actor), current_policy) != source_digest:
            raise ValueError('source changed')
        if _repository(binding, current_policy, context_id, actor, repository_selection) != repository_context:
            raise ValueError('repository selection changed')
        _allowed(current_root, current_policy, actor, path, 'read')
        _allowed(current_root, current_policy, actor, path, 'write')
    try:
        if not capture:
            revalidate(artifact_paths[0])
            _write_once(root, policy, actor, artifact_paths[0], manifest)
            revalidate(artifact_paths[1])
            _write_once(root, policy, actor, artifact_paths[1], text_document)
            revalidate(artifact_paths[2])
            _write_once(root, policy, actor, artifact_paths[2], chunks_document)
        revalidate(artifact_paths[3])
        _write_once(root, policy, actor, _request_path(paths, source_id, request_id, repository_context), request, compact=True)
        revalidate(artifact_paths[3])
        root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
            entry_folder, entry_index, context_max_bytes, actor)
        if not _capture_matches(root, policy, actor, paths, manifest, extracted, chunks):
            raise ValueError('capture unavailable after write')
        if _read_json(root, policy, actor, _request_path(paths, source_id, request_id, repository_context)) != request:
            raise ValueError('request differs after write')
    except (ValueError, OSError) as exc:
        raise ProtectedPartialError('partial effects may exist; inspect before retry') from exc
    return {'source_id': source_id, 'request_id': request_id, 'request': request,
            'coverage': projected['context_omissions'],
            'legacy_coverage': 'shared legacy artifacts not inspected; requalification required'}


def _open_bound(root, binding, *, context_id, approved_revision, entry_folder, entry_index,
                source_ref, source_id, request_id, context_max_bytes, request_max_bytes,
                artifact_context=None, perspective_refs=None, context_selection=None, repository_selection=None):
    actor = context_id if artifact_context is None else artifact_context
    root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
        entry_folder, entry_index, context_max_bytes, actor)
    current, projected, selection, required, optional, selected_perspectives = _selected_packet(
        root, policy, config, context_id, actor, approved_revision, entry_folder, entry_index,
        context_max_bytes, source_id, context_selection, perspective_refs, source_ref)
    repository_context = _repository(binding, policy, context_id, actor, repository_selection)
    source = _source(root, policy, context_id, source_ref, actor)
    digest = _hash(source, policy)
    path = _request_path(paths, source_id, request_id, repository_context)
    request = _read_json(root, policy, actor, path)
    if (not isinstance(request, dict) or request.get('source_id') != source_id
            or request.get('protected_request_id') != request_id
            or _request_identity(request) != request_id
            or request.get('repository_context') != repository_context
            or request.get('source_hash_sha256') != digest
            or request.get('request_limits') != request_limits(context_max_bytes, request_max_bytes)):
        raise ValueError('request unavailable')
    checked = dict(request)
    enforce_request_budget(checked, context_max_bytes=context_max_bytes, request_max_bytes=request_max_bytes)
    if (checked.get('byte_accounting') != request.get('byte_accounting')
            or len(canonical_request_text(request).encode('utf-8')) > 2_000_000):
        raise ValueError('request unavailable')
    auth = request.get('source_authorization')
    expected_auth = {'ref': source_ref, 'producer': policy.owner_of(source_ref), 'context_id': context_id,
                'policy_revision': approved_revision, 'use': 'interpretation', 'classification': 'source',
                'artifact_context': actor, 'context_selection': selection,
                'context_associations': {key: projected[key] for key in ('source_page_association',
                    'source_config_association', 'input_channel_association')}}
    if selected_perspectives:
        expected_auth['perspective_refs'] = selected_perspectives
    if auth != expected_auth:
        raise ValueError('request unavailable')
    packet = request.get('block_context_package')
    if not isinstance(packet, dict):
        raise ValueError('request unavailable')
    if current != packet:
        raise ValueError('request authority changed')
    # A request filename and digest bind bytes; they do not prove that those
    # chunks came from the selected source. Reconstruct the selected capture.
    _source_path, observed_hash, manifest, extracted, chunks = _capture(root, policy, context_id,
        source_ref, request.get('source_context'), config, actor)
    _validate_source_context(extracted, projected)
    if observed_hash != digest or manifest.get('source_id') != source_id:
        raise ValueError('request source changed')
    prompt = str(config.llm.get('prompt_versions', {}).get('context_deep_read', FOLDER_PROMPT_VERSION))
    profile = str(config.llm.get('default_model_profile', 'deep_context'))
    with tempfile.TemporaryDirectory(prefix='wiki-protected-empty-') as empty:
        rebuilt = build_context_request(manifest, chunks, Path(empty), prompt,
            CONTEXT_PASS_SCHEMA_VERSION, profile, block_context_package=current,
            perspectives_required=required, perspectives_optional=optional,
            **{key: projected[key] for key in ('root_entity', 'input_channel', 'quadrant_map',
               'quadrant_semantics', 'quadrant_boundary_rule', 'target_pages', 'input_stage_status')},
            context_max_bytes=context_max_bytes, request_max_bytes=request_max_bytes,
            source_authorization=auth, repository_context=repository_context)
    if _request_identity(rebuilt) != request_id:
        raise ValueError('request source changed')
    return root, policy, config, paths, request, digest


def record(root, binding, *, context_id, approved_revision, entry_folder, entry_index,
           source_ref, source_id, request_id, results,
           context_max_bytes=100_000, request_max_bytes=1_000_000, artifact_context=None, perspective_refs=None,
           context_selection=None, repository_selection=None):
    """Record host-supplied result objects against the exact retained request."""
    options = dict(context_id=context_id, approved_revision=approved_revision,
        entry_folder=entry_folder, entry_index=entry_index, source_ref=source_ref,
        source_id=source_id, request_id=request_id, context_max_bytes=context_max_bytes,
        request_max_bytes=request_max_bytes, artifact_context=artifact_context, perspective_refs=perspective_refs,
        context_selection=context_selection, repository_selection=repository_selection)
    actor = context_id if artifact_context is None else artifact_context
    root, policy, config, paths, request, digest = _open_bound(root, binding, **options)
    if (not isinstance(results, list) or not results or len(results) > 1000
            or len(_json_text(results).encode('utf-8')) > 2_000_000 or contains_access_secrets(results)):
        raise ValueError('result unavailable')
    rows = request['chunks']
    keys = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError('result unavailable')
        if len(_json_text(result).encode('utf-8')) > 2_000_000:
            raise ValueError('result exceeds protected retention limit')
        matches = [row for row in rows if result_matches_request(result, request, row, recording=True)]
        if len(matches) != 1 or result.get('cache_key') in keys:
            raise ValueError('result unavailable')
        key = result['cache_key']
        keys.append(key)
        target = paths.llm_cache / (key + '.json')
        _allowed(root, policy, actor, target, 'read')
        _allowed(root, policy, actor, target, 'write')
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
            _allowed(root, policy, actor, target, 'read')
            _allowed(root, policy, actor, target, 'write')
            _write_once(root, policy, actor, target, result)
            root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
            if current != request or current_digest != digest or _read_json(root, policy, actor, target) != result:
                raise ValueError('result differs after write')
            written.append(target)
        except (ValueError, OSError) as exc:
            raise ProtectedPartialError('partial effects may exist; inspect before retry') from exc
    return {'recorded': len(written), 'request_id': request_id,
            'legacy_coverage': 'shared legacy artifacts not inspected; requalification required'}


def consolidate(root, binding, *, context_id, approved_revision, entry_folder, entry_index,
                source_ref, source_id, request_id, source_page, event_target, date,
                candidates=(), context_max_bytes=100_000, request_max_bytes=1_000_000,
                artifact_context=None, perspective_refs=None, context_selection=None, repository_selection=None):
    """Prepare an event and packet; incorporation and review remain separate."""
    from wiki_core.consolidate import aggregate_results, build_event_markdown, build_packet
    options = dict(context_id=context_id, approved_revision=approved_revision,
        entry_folder=entry_folder, entry_index=entry_index, source_ref=source_ref,
        source_id=source_id, request_id=request_id, context_max_bytes=context_max_bytes,
        request_max_bytes=request_max_bytes, artifact_context=artifact_context, perspective_refs=perspective_refs,
        context_selection=context_selection, repository_selection=repository_selection)
    actor = context_id if artifact_context is None else artifact_context
    if repository_selection is not None:
        _, authority, _, _ = _authority(root, binding, context_id, approved_revision,
            entry_folder, entry_index, context_max_bytes, actor)
        authorize_repository_event(binding, authority, context_id, actor, repository_selection, safe_path(event_target))
    root, policy, config, paths, request, digest = _open_bound(root, binding, **options)
    if (not isinstance(candidates, (list, tuple)) or len(candidates) > 128
            or any(not isinstance(x, str) for x in candidates)):
        raise ValueError('candidate unavailable')
    refs = [safe_path(x) for x in candidates]
    if len(refs) != len(set(refs)) or len(refs) > 128:
        raise ValueError('candidate unavailable')
    source_page = safe_path(source_page)
    selected_source = context_selection.get('source_page')
    if selected_source is not None and selected_source != source_page:
        raise ValueError('source page selection changed')
    selected_digest = None
    if selected_source is not None:
        matches = [row for row in request['block_context_package']['inputs']
                   if row.get('ref') == selected_source and row.get('reason') == 'Explicit ingestion source_page']
        if len(matches) != 1:
            raise ValueError('source page selection unavailable')
        selected_digest = matches[0]['document_sha256']
    event_target = safe_path(event_target)
    if contains_access_secrets([source_page, event_target, refs]):
        raise ValueError('output unavailable')
    if not isinstance(date, dt.date) or isinstance(date, dt.datetime):
        raise ValueError('event target unavailable')
    expected = paths.ingest_events_dir / (f'{date.isoformat()}-'
        f'{hashlib.sha256(source_id.encode()).hexdigest()}-{request_id}.md')
    if root / event_target != expected:
        raise ValueError('event target unavailable')
    authorize_repository_event(binding, policy, context_id, actor, repository_selection, event_target)
    _allowed(root, policy, context_id, root / source_page, 'read')
    source_page_digest = _source_page(root, policy, actor, config, source_page, selected_digest=selected_digest)
    for ref in refs:
        _allowed(root, policy, context_id, root / ref, 'read')
        _allowed(root, policy, actor, root / ref, 'read')
    target = _allowed(root, policy, actor, root / event_target, 'write')
    _allowed(root, policy, actor, target, 'read')
    packet_path = paths.extraction_events / f'protected-{hashlib.sha256(source_id.encode()).hexdigest()}-{request_id}-integration-packet.json'
    _allowed(root, policy, actor, packet_path, 'read')
    _allowed(root, policy, actor, packet_path, 'write')
    for row in request['chunks']:
        cache_path = paths.llm_cache / (row['cache_key'] + '.json')
        _allowed(root, policy, actor, cache_path, 'read')
    def read_bound_result(row):
        from wiki_core.llm.context_pass import validate_result
        cache_path = paths.llm_cache / (row['cache_key'] + '.json')
        result = _read_json(root, policy, actor, cache_path)
        if (contains_access_secrets(result) or validate_result(result)
                or not result_matches_request(result, request, row)):
            raise ValueError('result unavailable')
        return result
    aggregated = aggregate_results(request, paths.llm_cache, root=root, result_reader=read_bound_result)
    aggregated['folder_request_id'] = request_id
    aggregated['source_hash_sha256'] = digest
    if request.get('repository_context') is not None:
        selected = request['repository_context']
        rows = selected if isinstance(selected, list) else [selected]
        aggregated['independent_git_sources'] = [{key: row[key] for key in
            ('selection_id', 'repository_identity', 'host_binding_digest', 'revision', 'path', 'blob',
             'document_sha256', 'content_sha256')} for row in rows]
    packet = build_packet(aggregated, root, config, paths, candidates=refs)
    markdown = build_event_markdown(aggregated, config=config, context=request['source_context'],
        date=date, source_page=source_page, source_type=classify_source(source_ref),
        event_dir=target.parent, root=root, yaml_safe=True,
        protected_provenance={'source_locator': source_ref, 'policy_revision': approved_revision,
            'executor_context': context_id, 'integrator_context': actor,
            'source_page_association': 'operator_selected_unverified',
            'extraction_limitations': _format_omissions(source_ref)},
        impact=dict(packet.get('impact') or {}))
    if contains_access_secrets([packet, markdown]):
        raise ValueError('output unavailable')
    if len(_json_text(packet).encode('utf-8')) > 2_000_000 or len(markdown.encode('utf-8')) > 2_000_000:
        raise ValueError('output exceeds protected retention limit')
    root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
    if current != request or current_digest != digest:
        raise ValueError('request authority changed')
    authorize_repository_event(binding, policy, context_id, actor, repository_selection, event_target)
    _allowed(root, policy, context_id, root / source_page, 'read')
    if _source_page(root, policy, actor, config, source_page, selected_digest=selected_digest) != source_page_digest:
        raise ValueError('source page changed')
    _allowed(root, policy, actor, target, 'write')
    _allowed(root, policy, actor, target, 'read')
    if target.exists():
        raise ValueError('event already exists; preserved')
    try:
        _write_once(root, policy, actor, packet_path, packet)
        root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
        if current != request or current_digest != digest:
            raise ValueError('request authority changed')
        authorize_repository_event(binding, policy, context_id, actor, repository_selection, event_target)
        _allowed(root, policy, context_id, root / source_page, 'read')
        if _source_page(root, policy, actor, config, source_page, selected_digest=selected_digest) != source_page_digest:
            raise ValueError('source page changed')
        _allowed(root, policy, actor, target, 'write')
        _allowed(root, policy, actor, target, 'read')
        policy.fresh()
        target.parent.mkdir(parents=True, exist_ok=True)
        policy.fresh()
        with target.open('x', encoding='utf-8') as stream:
            stream.write(markdown)
        policy.fresh()
        root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
        if current != request or current_digest != digest:
            raise ValueError('request authority changed')
        authorize_repository_event(binding, policy, context_id, actor, repository_selection, event_target)
        _allowed(root, policy, context_id, root / source_page, 'read')
        if _source_page(root, policy, actor, config, source_page, selected_digest=selected_digest) != source_page_digest:
            raise ValueError('source page changed')
        _allowed(root, policy, actor, target, 'read')
        policy.fresh()
        with target.open('rb') as stream:
            event_bytes = stream.read(2_000_001)
        policy.fresh()
        if event_bytes != markdown.encode('utf-8'):
            raise ValueError('event differs after write')
        if _read_json(root, policy, actor, packet_path) != packet:
            raise ValueError('packet differs after write')
    except (ValueError, OSError) as exc:
        raise ProtectedPartialError('partial effects may exist; inspect before retry') from exc
    return {'event': event_target, 'request_id': request_id,
            'coverage': 'explicit candidates only; linked sources not inspected',
            'integration': 'pending review and incorporation',
            'legacy_coverage': 'shared legacy artifacts not inspected; requalification required'}
