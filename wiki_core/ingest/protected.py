"""Host-bound folder ingestion into a separately routed derived cache.

This is an application boundary, not an operating-system access control list.
Every selected file is checked against the pinned policy before it is opened.
"""
from __future__ import annotations

import hashlib
import datetime as dt
import json
import copy
import mimetypes
import re
import subprocess
import tempfile
from contextvars import ContextVar
from dataclasses import replace
from functools import wraps
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
    authorize_repository_grant, check_repository_storage, _selection_ids)
from wiki_core.source_manifest import classify_source, source_id_for, source_origin, chunk_document
from wiki_core.traversal import (PROTECTED_ARTIFACT_COMPONENT, require_wiki_boundaries,
    require_wiki_path)
from wiki_core.git_env import local_git_environment, local_git_executable


class ProtectedPartialError(ValueError):
    """A failed operation may have retained some artifacts; inspect before retry."""


class ProtectedResultBudgetError(ValueError):
    """Selected results exceed the aggregate review limit."""


FOLDER_PROMPT_VERSION = 'v5'
_STAGE_CACHE = ContextVar('wiki_protected_source_stage_cache', default=None)


def _scoped_stage(operation):
    @wraps(operation)
    def invoke(*args, **kwargs):
        from wiki_core.context_policy import policy_stage_cache
        if _STAGE_CACHE.get() is not None:
            return operation(*args, **kwargs)
        token = _STAGE_CACHE.set({'authorities': {}, 'packets': {}, 'repositories': {}, 'context_paths': {}, 'captures': {}})
        try:
            with policy_stage_cache():
                return operation(*args, **kwargs)
        finally:
            _STAGE_CACHE.reset(token)
    return invoke


def _csv_delimiter(source_ref, selection):
    if selection is not None and (Path(source_ref).suffix.lower() != '.csv'
            or not isinstance(selection, str) or selection not in {'comma', 'semicolon', 'tab'}):
        raise ValueError('CSV delimiter selection unavailable')
    return selection


def _format_omissions(source_ref, csv_delimiter=None):
    suffix = Path(source_ref).suffix.lower()
    csv_delimiter = _csv_delimiter(source_ref, csv_delimiter)
    csv_notice = ('CSV is parsed with the comma-delimited Python excel dialect; the source dialect is not inferred or verified. '
                  'A semicolon-delimited or differently quoted file can be misread; confirm the source format before relying on columns.')
    if csv_delimiter is not None:
        csv_notice = (f'CSV uses the explicitly selected {csv_delimiter} delimiter with Python excel quoting; '
                      'the source dialect is not independently verified. Confirm quoting and format before relying on columns.')
    limitations = {
        '.pdf': ('PDF images and scanned text were not inspected; OCR was not performed. '
                 'Extracted text and request chunks do not retain page numbers; consult the original PDF for page locations.'),
        '.csv': csv_notice,
        '.tsv': ('TSV is parsed with the tab-delimited Python excel-tab dialect; the source dialect is not inferred or verified. '
                 'A file using other separators or quoting can be misread; confirm the source format before relying on columns.'),
        '.docx': 'Document headers, footers, images, embedded objects, hyperlink destinations and comments were not inspected.',
        '.xlsx': 'Spreadsheet drawings, embedded objects, macro behavior and formula recalculation were not inspected.',
        '.eml': 'Email visual rendering and external resources were not inspected.',
    }
    return [limitations[suffix]] if suffix in limitations else []


def _authority(root, binding, context_id, approved_revision, entry_folder, entry_index, budget,
               artifact_context=None):
    root = Path(root).resolve(strict=True)
    cache = _STAGE_CACHE.get()
    key = (str(root), binding, context_id, approved_revision, entry_folder, entry_index, budget, artifact_context)
    if cache is not None and key in cache['authorities']:
        cached = cache['authorities'][key]
        cached[1].fresh()
        _check_physical_context(root, entry_folder, cache['context_paths'].get(str(root), (set(), set())))
        cached[1].fresh()
        return cached
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
    result = root, policy, config, WikiPaths(root, config)
    if cache is not None:
        cache['authorities'][key] = result
    return result


def _check_physical_context(root, folder, selected):
    folder_path = require_wiki_path(root, folder)
    if not folder_path.is_dir():
        raise ValueError('context folder unavailable')
    refs, required = selected
    require_wiki_boundaries(root, files=tuple(root / ref for ref in refs))
    if any(not (root / ref).is_file() for ref in required):
        raise ValueError('context boundary unavailable')


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


def _capture(root, policy, context_id, source_ref, source_context, config, artifact_context=None, *,
             expected_digest=None, csv_delimiter=None):
    if (not isinstance(source_context, str) or not source_context.strip() or len(source_context) > 1024
            or contains_access_secrets(source_context)):
        raise ValueError('source context unavailable')
    csv_delimiter = _csv_delimiter(source_ref, csv_delimiter)
    source = _source(root, policy, context_id, source_ref, artifact_context)
    cache = _STAGE_CACHE.get()
    key = ((str(root), policy.policy_revision, context_id, source_ref, source_context, artifact_context,
            config.llm.get('chunk_target_tokens', 1200), config.llm.get('chunk_overlap_tokens', 150), csv_delimiter)
           if cache is not None else None)
    if cache is not None and expected_digest is not None and key in cache['captures']:
        captured = cache['captures'][key]
        policy.fresh()
        if captured[1] != expected_digest or _hash(source, policy) != expected_digest:
            raise ValueError('source changed')
        return copy.deepcopy(captured)
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
    if expected_digest is not None and digest != expected_digest:
        raise ValueError('source changed')
    extracted = (extract_captured(str(source), source_type, data) if csv_delimiter is None else
                 extract_captured(str(source), source_type, data, csv_delimiter=csv_delimiter))
    policy.fresh()
    manifest = {'schema_version': 'wiki_source_manifest.v1', 'source_uri': str(source),
        'source_origin': source_origin(str(source), root), 'source_type': source_type,
        'context': source_context, 'captured_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'risk_level': 'medium' if source_type in {'pdf', 'spreadsheet', 'document', 'email'} else 'low', 'visibility_initial': 'private_self',
        'privacy_policy': 'extract_private_operational_context_without_access_secrets',
        'absolute_path': str(source), 'exists': True, 'mime_type': mimetypes.guess_type(str(source))[0],
        'source_id': source_id_for(str(source), digest, root=root), 'hash_sha256': digest, 'size_bytes': len(data),
        'extraction_limitations': _format_omissions(source_ref, csv_delimiter),
        'extraction_complete': not bool(_format_omissions(source_ref, csv_delimiter))}
    if csv_delimiter is not None:
        manifest['csv_delimiter'] = csv_delimiter
    # Enforce bounded atomic rows before scanning: a long unbroken row must
    # not spend unbounded time in text detectors and cannot be split safely.
    chunks = [{'chunk_id': c.chunk_id, 'ordinal': c.ordinal, 'hash_sha256': c.hash_sha256,
               'token_estimate': c.token_estimate, 'text': c.text}
              for c in chunk_text(str(manifest['source_id']), extracted.text,
                  int(config.llm.get('chunk_target_tokens', 1200)),
                  int(config.llm.get('chunk_overlap_tokens', 150)),
                  preserve_lines=source_type in {'table', 'spreadsheet'},
                  source_units=extracted.units if source_type == 'document' else None)]
    if any(f.category == 'secret' for f in scan_text(extracted.text)) \
            or contains_access_secrets([extracted.text, extracted.units]):
        raise ValueError('source unavailable')
    if not chunks:
        raise ValueError('empty source requires explicit review')
    result = source, digest, manifest, extracted, chunks
    if cache is not None:
        cache['captures'][key] = copy.deepcopy(result)
    return result


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
    # Validate every selected physical repository before opening any Git body.
    for item in ids:
        check_repository_storage(binding, policy, context_id, actor, item)
    cache = _STAGE_CACHE.get()
    rows = []
    for item in ids:
        key = (binding, policy.policy_revision, context_id, actor, item)
        if cache is not None and key in cache['repositories']:
            check_repository_storage(binding, policy, context_id, actor, item)
            row = copy.deepcopy(cache['repositories'][key])
        else:
            row = selected_repository(binding, policy, context_id, actor, item)
            if cache is not None:
                cache['repositories'][key] = copy.deepcopy(row)
        rows.append(row)
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
                     budget, task_id, selection, perspective_refs, source_ref, repository_selection,
                     csv_delimiter=None):
    from wiki_core.ingest.explicit_context import (explicit_ingestion_evidence,
        resolve_explicit_ingestion_context, _selection)
    selection = _selection(selection)
    repo_ids = [] if repository_selection is None else _selection_ids(repository_selection)
    if set(selection['repository_source_pages']) - set(repo_ids):
        raise ValueError('repository source selection unavailable')
    cache = _STAGE_CACHE.get()
    key = canonical_request_text({'root': str(root), 'revision': revision, 'context_id': context_id,
        'actor': actor, 'folder': folder, 'index': index, 'budget': budget, 'task_id': task_id,
        'selection': selection, 'perspective_refs': perspective_refs, 'source_ref': source_ref,
        'repository_selection': repo_ids, 'csv_delimiter': csv_delimiter})
    if cache is not None and key in cache['packets']:
        policy.fresh()
        _check_physical_context(root, folder, cache['context_paths'].get(str(root), (set(), set())))
        policy.fresh()
        return copy.deepcopy(cache['packets'][key])
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
    optional_gaps += ['Repository source page for ' + item + ' not selected; association unverified.'
                      for item in repo_ids if item not in selection['repository_source_pages']]
    format_gaps = _format_omissions(source_ref, csv_delimiter)
    if lenses:
        packet = build(evidence + lenses, projected['context_omissions'] + optional_gaps + format_gaps)
    else:
        from wiki_core.context_packet import _packet_with_omissions
        packet = _packet_with_omissions(preliminary, projected['context_omissions'] + optional_gaps + format_gaps, policy)
    projected = resolve_explicit_ingestion_context(packet, selection, config)
    projected['context_omissions'] += optional_gaps + format_gaps
    _check_perspective_packet(packet, paths)
    refs = {row['ref'] for row in packet['inputs']}
    required_paths = {row['ref'] for row in packet['inputs'] if row['kind'] == 'mandatory'}
    required_paths.add(packet['entry_index'])
    _check_physical_context(root, folder, (refs, required_paths))
    if cache is not None:
        existing_refs, existing_required = cache['context_paths'].setdefault(str(root), (set(), set()))
        existing_refs.update(refs)
        existing_required.update(required_paths)
    result = packet, projected, selection, required, optional, paths
    if cache is not None:
        cache['packets'][key] = copy.deepcopy(result)
    return result


def _check_repository_associations(projected, repository_context):
    from wiki_core.repo_read import remote_identity
    rows = repository_context if isinstance(repository_context, list) else ([] if repository_context is None else [repository_context])
    by_id = {row['selection_id']: row for row in rows}
    for key, page in projected['repository_sources'].items():
        locator = page['source_locator']
        identity, _ = remote_identity(locator if '://' in locator or '@' in locator else 'https://' + locator)
        if key not in by_id or identity != by_id[key]['repository_identity']:
            raise ValueError('repository source association unavailable')


def _check_repository_grant_associations(projected, binding, policy, context_id, actor, selection):
    ids = [] if selection is None else _selection_ids(selection)
    rows = [{'selection_id': item, 'repository_identity':
             authorize_repository_grant(binding, policy, context_id, actor, item).identity} for item in ids]
    _check_repository_associations(projected, rows)


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


def _requalification_guard(root, policy, current):
    cache = _STAGE_CACHE.get()
    folder = current.get('block_context_package', {}).get('entry_folder')
    selected = cache.get('candidate_guard') if cache is not None else None
    if (cache is None or not isinstance(folder, str) or not isinstance(selected, dict)
            or selected.get('request_id') != current.get('protected_request_id')):
        raise ValueError('reuse context unavailable')
    _check_physical_context(root, folder, cache['context_paths'].get(str(root), (set(), set())))
    auth = current['source_authorization']
    source = _source(root, policy, auth['context_id'], auth['ref'], auth['artifact_context'])
    _allowed(root, policy, auth['artifact_context'], selected['request_path'], 'read')
    if (_artifact_stamp(source) != selected['source_stamp']
            or _artifact_stamp(selected['request_path']) != selected['request_stamp']):
        raise ValueError('source or request changed')
    if _repository(selected['binding'], policy, auth['context_id'], auth['artifact_context'],
                   selected['repository_selection']) != current.get('repository_context'):
        raise ValueError('repository selection changed')
    policy.fresh()


def _previous_request(root, binding, policy, actor, paths, current, previous_id, previous_source_id=None):
    """Select one exact historical request; current policy remains the authority."""
    from wiki_core.context_policy import historical_policy
    from wiki_core.ingest.historical_candidates import comparable_request, selected_grants
    if (not isinstance(previous_id, str) or not re.fullmatch(r'[0-9a-f]{64}', previous_id)
            or previous_id == current.get('protected_request_id')):
        return None
    auth = current.get('source_authorization')
    if not isinstance(auth, dict) or binding is None:
        return None
    previous_source_id = current.get('source_id') if previous_source_id is None else previous_source_id
    matches = [grant for grant in binding.previous_request_grants
               if grant.executor == auth.get('context_id') and grant.integrator == actor
               and grant.source_ref == auth.get('ref') and grant.source_id == previous_source_id
               and grant.request_id == previous_id]
    if len(matches) != 1:
        return None
    grant = matches[0]
    _requalification_guard(root, policy, current)
    target = _request_path(paths, previous_source_id, previous_id, current.get('repository_context'))
    _allowed(root, policy, actor, target, 'read')
    def stamp(path):
        value = path.stat()
        return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    try:
        before = stamp(target)
        cache = _STAGE_CACHE.get()
        key = (str(root), policy.policy_revision, actor, current['protected_request_id'], previous_source_id, previous_id)
        proof = cache.setdefault('reuse_proofs', {}).get(key) if cache is not None else None
        if proof is not None:
            if before != proof[0]:
                raise ValueError('historical request changed')
            policy.fresh()
            return proof[1], proof[2]
        previous = _read_json(root, policy, actor, target)
        if stamp(target) != before:
            raise ValueError('historical request changed')
    except FileNotFoundError:
        return None
    try:
        if (not isinstance(previous, dict) or previous.get('protected_request_id') != previous_id
                or _request_identity(previous) != previous_id
                or previous.get('source_id') != previous_source_id
                or previous.get('source_authorization', {}).get('policy_revision') != grant.policy_revision
                or comparable_request(previous, source_may_differ=previous_source_id != current.get('source_id'))
                   != comparable_request(current, source_may_differ=previous_source_id != current.get('source_id'))):
            return None
        previous_revision = previous['source_authorization']['policy_revision']
        historical = historical_policy(policy, previous_revision, authority_format='folder')
        if selected_grants(historical, previous) != selected_grants(policy, current):
            return None
        # The retained packet is not itself proof that its selected bodies came
        # from the historical tree. Compare each selected Git blob identity to
        # the immutable approved ancestor without reading unselected bodies.
        from wiki_core.context_packet import guard_folder_blob
        from wiki_core.repository_reader import RepositoryReader
        reader = RepositoryReader(root, previous_revision, before_tree=policy.fresh)
        for item in previous['block_context_package']['inputs']:
            guard_folder_blob(root, policy, item['ref'])
            if reader._entries.get(item['ref']) != item['origin']['blob']:
                return None
        policy.fresh()
        if cache is not None:
            cache['reuse_proofs'][key] = (before, previous, historical)
        return previous, historical
    except (ValueError, KeyError, TypeError, AttributeError):
        policy.fresh()
        return None


def _historical_capture(root, policy, actor, paths, current, previous, historical):
    """Cross-check one retained capture once per stage; it is not the raw source."""
    cache = _STAGE_CACHE.get()
    proofs = cache.setdefault('candidate_captures', {}) if cache is not None else {}
    key = (previous['protected_request_id'], previous['source_id'])
    if key in proofs:
        origin, chunks, dependencies = proofs[key]
        _check_reuse_dependencies(root, policy, actor, dependencies, current=current)
        return origin, chunks, dependencies
    manifest_path = paths.source_manifests / (previous['source_id'] + '.json')
    chunks_path = paths.chunks / (previous['source_id'] + '.json')
    _requalification_guard(root, policy, current)
    for path in (manifest_path, chunks_path):
        ref = path.relative_to(root).as_posix()
        owner = historical.owner_of(ref)
        if historical._connection(owner, actor, ref, 'interpretation', 'artifact', qualified=False) != 'approved':
            return None
        _allowed(root, policy, actor, path, 'read')
    try:
        dependencies = tuple((path, _artifact_stamp(path)) for path in (manifest_path, chunks_path))
        old_manifest = _read_json(root, policy, actor, manifest_path, max_bytes=20_000_000)
        _requalification_guard(root, policy, current)
        old_chunks = _read_json(root, policy, actor, chunks_path, max_bytes=20_000_000)
    except FileNotFoundError:
        return None
    _check_reuse_dependencies(root, policy, actor, dependencies, current=current)
    origin = old_manifest.get('source_origin') if isinstance(old_manifest, dict) else None
    if (not isinstance(origin, dict) or origin.get('kind') != 'repository_path'
            or origin.get('locator') != current['source_authorization']['ref']
            or old_manifest.get('source_id') != previous['source_id']
            or old_manifest.get('hash_sha256') != previous.get('source_hash_sha256')
            or source_id_for(str(root / origin['locator']), old_manifest['hash_sha256'], root=root) != previous['source_id']
            or not isinstance(old_chunks, dict) or old_chunks.get('source_id') != previous['source_id']
            or old_chunks.get('source_hash_sha256') != previous.get('source_hash_sha256')
            or old_chunks.get('source_origin_id') != origin.get('id')
            or not isinstance(old_chunks.get('chunks'), list)):
        return None
    by_id = {}
    for item in old_chunks['chunks']:
        if not isinstance(item, dict) or not isinstance(item.get('chunk_id'), str):
            return None
        chunk_id = item['chunk_id']
        by_id[chunk_id] = item if chunk_id not in by_id else None
    if cache is not None:
        proofs[key] = (origin, by_id, dependencies)
    return origin, by_id, dependencies


def _historical_candidate(root, policy, actor, paths, current, row, previous, historical):
    """Read one exact earlier result as historical review material only."""
    cache = _STAGE_CACHE.get()
    indexes = cache.setdefault('candidate_rows', {}) if cache is not None else {}
    key = previous['protected_request_id']
    if key not in indexes:
        by_id = {}
        for item in previous['chunks']:
            provenance = item.get('provenance')
            if not isinstance(provenance, dict) or not isinstance(provenance.get('origin_id'), str):
                continue
            identity = (item.get('chunk_hash_sha256'), canonical_request_text(provenance))
            by_id[identity] = item if identity not in by_id else None
        indexes[key] = by_id
    provenance = row.get('provenance')
    if not isinstance(provenance, dict) or not isinstance(provenance.get('origin_id'), str):
        return None, ()
    old_row = indexes[key].get((row.get('chunk_hash_sha256'), canonical_request_text(provenance)))
    if (old_row is None or old_row.get('text') != row.get('text')
            or not isinstance(row.get('text'), str)
            or hashlib.sha256(row['text'].encode('utf-8')).hexdigest() != row.get('chunk_hash_sha256')):
        return None, ()
    capture = _historical_capture(root, policy, actor, paths, current, previous, historical)
    if capture is None:
        return None, ()
    origin, captured_rows, capture_dependencies = capture
    captured = captured_rows.get(old_row.get('chunk_id'))
    if (origin.get('id') != provenance['origin_id'] or captured is None
            or captured.get('hash_sha256') != old_row['chunk_hash_sha256']
            or captured.get('text') != old_row['text']):
        return None, ()
    old_key = old_row.get('cache_key')
    if not isinstance(old_key, str) or not re.fullmatch(r'[0-9a-f]{64}', old_key):
        return None, ()
    prior_request = _request_path(paths, previous['source_id'], previous['protected_request_id'],
                                  current.get('repository_context'))
    old_target = paths.llm_cache / (old_key + '.json')
    ref = old_target.relative_to(root).as_posix()
    owner = historical.owner_of(ref)
    if historical._connection(owner, actor, ref, 'interpretation', 'artifact', qualified=False) != 'approved':
        return None, ()
    _requalification_guard(root, policy, current)
    for path in (prior_request, old_target):
        _allowed(root, policy, actor, path, 'read')
    try:
        before = capture_dependencies + tuple((path, _artifact_stamp(path)) for path in (prior_request, old_target))
        old_result = _read_json(root, policy, actor, old_target)
    except FileNotFoundError:
        return None, ()
    if (contains_access_secrets(old_result) or not result_matches_request(old_result, previous, old_row)
            or old_result.get('source_id') != previous['source_id'] or old_result.get('chunk_id') != old_row['chunk_id']
            or 'protected_reuse_origin' in old_result):
        return None, ()
    _check_reuse_dependencies(root, policy, actor, before, current=current)
    origin = {'request_id': previous['protected_request_id'],
              'policy_revision': previous['source_authorization']['policy_revision'],
              'packet_digest': previous['block_context_package']['packet_digest'],
              'source_id': previous['source_id'], 'source_hash_sha256': previous['source_hash_sha256'],
              'chunk_id': old_row['chunk_id'], 'chunk_hash_sha256': old_row['chunk_hash_sha256'],
              'source_proof': 'retained_capture_not_raw_source',
              'cache_key': old_key, 'context_sha256': old_row['context_sha256'],
              'result_sha256': hashlib.sha256(canonical_request_text(old_result).encode('utf-8')).hexdigest()}
    return {'chunk_id': row['chunk_id'], 'status': 'review_needed', 'origin': origin,
            'result': old_result}, before


def _artifact_stamp(path):
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _check_reuse_dependencies(root, policy, actor, dependencies, *, current=None):
    if not dependencies:
        return
    if current is not None:
        _requalification_guard(root, policy, current)
    for path, identity in dependencies:
        _allowed(root, policy, actor, path, 'read')
        if _artifact_stamp(path) != identity:
            raise ValueError('reuse provenance changed')
    policy.fresh()


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
    limitations = _format_omissions(manifest['source_uri'], manifest.get('csv_delimiter'))
    expected = chunk_document(manifest, chunks, warnings=limitations)
    expected['extraction_limitations'] = limitations
    if (not all(isinstance(item, dict) for item in (old_manifest, old_text, old_chunks))
            or any(old_manifest.get(k) != manifest.get(k) for k in
                   ('schema_version', 'source_id', 'source_origin', 'source_type', 'hash_sha256', 'csv_delimiter',
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
            artifact_context=None, perspective_refs=None, context_selection=None, repository_selection=None,
            csv_delimiter=None, previous_request_id=None, previous_source_id=None, candidate_chunk_ids=None):
    """Capture one authorized source and emit its bound contextual request."""
    request_limits(context_max_bytes, request_max_bytes)
    csv_delimiter = _csv_delimiter(source_ref, csv_delimiter)
    if previous_request_id is None:
        if candidate_chunk_ids is not None or previous_source_id is not None:
            raise ValueError('historical candidate selection unavailable')
    elif (not isinstance(previous_request_id, str) or not re.fullmatch(r'[0-9a-f]{64}', previous_request_id)
            or not isinstance(candidate_chunk_ids, list) or not 1 <= len(candidate_chunk_ids) <= 32
            or any(not isinstance(item, str) or not 1 <= len(item) <= 1024 for item in candidate_chunk_ids)
            or len(candidate_chunk_ids) != len(set(candidate_chunk_ids))
            or (previous_source_id is not None and (not isinstance(previous_source_id, str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,511}', previous_source_id)))
            or contains_access_secrets(candidate_chunk_ids)):
        raise ValueError('historical candidate selection unavailable')
    actor = context_id if artifact_context is None else artifact_context
    root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
        entry_folder, entry_index, context_max_bytes, actor)
    prompt = str(config.llm.get('prompt_versions', {}).get('context_deep_read', FOLDER_PROMPT_VERSION))
    require_approved_prompt_version(prompt, folder=True)
    _, projected, selection, required, optional, selected_perspectives = _selected_packet(
        root, policy, config, context_id, actor, approved_revision, entry_folder, entry_index,
        context_max_bytes, 'source-selection-preflight', context_selection, perspective_refs, source_ref, repository_selection,
        csv_delimiter)
    _check_repository_grant_associations(projected, binding, policy, context_id, actor, repository_selection)
    repository_context = _repository(binding, policy, context_id, actor, repository_selection)
    _check_repository_associations(projected, repository_context)
    source, source_digest, manifest, extracted, chunks = _capture(root, policy, context_id,
        source_ref, source_context, config, actor, csv_delimiter=csv_delimiter)
    _validate_source_context(extracted, projected)
    packet, projected, selection, required, optional, selected_perspectives = _selected_packet(
        root, policy, config, context_id, actor, approved_revision, entry_folder, entry_index,
        context_max_bytes, str(manifest['source_id']), context_selection, perspective_refs, source_ref, repository_selection,
        csv_delimiter)
    auth = {'ref': source_ref, 'producer': policy.owner_of(source_ref), 'context_id': context_id,
        'policy_revision': approved_revision, 'use': 'interpretation', 'classification': 'source',
        'artifact_context': actor, 'context_selection': selection,
        'context_associations': {key: projected[key] for key in ('source_page_association',
            'source_config_association', 'input_channel_association')}}
    if selected_perspectives:
        auth['perspective_refs'] = selected_perspectives
    if csv_delimiter is not None:
        auth['csv_delimiter'] = csv_delimiter
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
    selected_candidates = []
    candidate_selection_valid = True
    if previous_request_id is not None:
        by_id = {}
        for row in request['chunks']:
            chunk_id = row['chunk_id']
            by_id[chunk_id] = row if chunk_id not in by_id else None
        candidate_selection_valid = all(by_id.get(chunk_id) is not None for chunk_id in candidate_chunk_ids)
        if candidate_selection_valid:
            selected_candidates = [by_id[chunk_id] for chunk_id in candidate_chunk_ids]
    request_id = _request_identity(request)
    request['protected_request_id'] = request_id
    enforce_request_budget(request, context_max_bytes=context_max_bytes, request_max_bytes=request_max_bytes)
    if len(canonical_request_text(request).encode('utf-8')) > 2_000_000:
        raise ValueError('request exceeds protected retention limit')
    source_id = str(manifest['source_id'])
    limitations = _format_omissions(source_ref, csv_delimiter)
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
    # The retained request is immutable.  Project only exact authorized cache
    # keys into the response. Revalidate authority and physical identities on
    # each open and hash/reconstruct the source and request around the batch.
    # A corrupt result is not evidence of a cache miss.
    options = dict(context_id=context_id, approved_revision=approved_revision,
        entry_folder=entry_folder, entry_index=entry_index, source_ref=source_ref,
        source_id=source_id, request_id=request_id, context_max_bytes=context_max_bytes,
        request_max_bytes=request_max_bytes, artifact_context=artifact_context,
        perspective_refs=perspective_refs, context_selection=context_selection,
        repository_selection=repository_selection, csv_delimiter=csv_delimiter)
    prior_review = None
    prior_dependencies = []
    if previous_request_id is not None:
        try:
            root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
                entry_folder, entry_index, context_max_bytes, actor)
            source_path = _source(root, policy, context_id, source_ref, actor)
            request_path = _request_path(paths, source_id, request_id, repository_context)
            _allowed(root, policy, actor, request_path, 'read')
            policy.fresh()
            source_stamp, request_stamp = _artifact_stamp(source_path), _artifact_stamp(request_path)
            policy.fresh()
            root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
            if (current != request or current_digest != source_digest or _artifact_stamp(source_path) != source_stamp
                    or _artifact_stamp(request_path) != request_stamp):
                raise ValueError('request authority changed')
            cache = _STAGE_CACHE.get()
            if cache is None:
                raise ValueError('stage unavailable')
            cache['candidate_guard'] = {'request_id': request_id, 'binding': binding,
                'source_stamp': source_stamp, 'request_path': request_path, 'request_stamp': request_stamp,
                'repository_selection': repository_selection}
            prior_review = {'status': 'unavailable', 'previous_request_id': previous_request_id,
                            'selected_chunk_ids': list(candidate_chunk_ids),
                            'coverage': 'explicit historical candidates only; no current result inferred'}
            if not candidate_selection_valid:
                prior_review['reason'] = 'candidate_selection_changed'
            selected = (_previous_request(root, binding, policy, actor, paths, request, previous_request_id, previous_source_id)
                        if candidate_selection_valid else None)
            if selected is not None:
                candidates = []
                candidate_bytes = 0
                for row in selected_candidates:
                    selected_now = _previous_request(root, binding, policy, actor, paths, request, previous_request_id, previous_source_id)
                    if selected_now is None:
                        break
                    candidate, dependencies = _historical_candidate(root, policy, actor, paths, request, row, *selected_now)
                    if candidate is not None:
                        candidate_bytes += len(canonical_request_text(candidate).encode('utf-8'))
                        if candidate_bytes > 2_000_000:
                            candidates = []
                            prior_dependencies = []
                            prior_review['reason'] = 'candidate_response_budget_exceeded'
                            break
                        candidates.append(candidate)
                        prior_dependencies.extend(dependencies)
                if candidates:
                    found = {item['chunk_id'] for item in candidates}
                    prior_review.update(status='review_needed', candidates=candidates,
                        unavailable_chunk_ids=[chunk_id for chunk_id in candidate_chunk_ids if chunk_id not in found])
            root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
            if current != request or current_digest != source_digest:
                raise ValueError('request authority changed')
            _check_reuse_dependencies(root, policy, actor, prior_dependencies, current=request)
        except (ValueError, OSError):
            # A missing, corrupt or changed historical candidate must not
            # block the current request. Still fail if its live authority,
            # source or selected context changed during the attempt.
            try:
                root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
                if current != request or current_digest != source_digest:
                    raise ValueError('request authority changed')
            except (ValueError, OSError) as current_exc:
                raise ProtectedPartialError('current request unavailable; partial effects may exist; inspect before retry') from current_exc
            prior_review = {'status': 'unavailable', 'previous_request_id': previous_request_id,
                            'selected_chunk_ids': list(candidate_chunk_ids),
                            'coverage': 'historical candidate unavailable; current request unchanged'}
            prior_dependencies = []
    response_request = copy.deepcopy(request)
    try:
        from wiki_core.llm.context_pass import validate_result
        missing = object()
        def stamp(path):
            value = path.stat()
            return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                    value.st_mtime_ns, value.st_ctime_ns)
        root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
            entry_folder, entry_index, context_max_bytes, actor)
        source_path = _source(root, policy, context_id, source_ref, actor)
        request_path = _request_path(paths, source_id, request_id, repository_context)
        _allowed(root, policy, actor, request_path, 'read')
        policy.fresh()
        source_stamp, request_stamp = stamp(source_path), stamp(request_path)
        policy.fresh()
        root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
        if (current != request or current_digest != source_digest or stamp(source_path) != source_stamp
                or stamp(request_path) != request_stamp):
            raise ValueError('request authority changed')
        def guard_cache(path):
            nonlocal root, policy, config, paths
            root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
                entry_folder, entry_index, context_max_bytes, actor)
            current_source = _source(root, policy, context_id, source_ref, actor)
            current_request = _request_path(paths, source_id, request_id, repository_context)
            _allowed(root, policy, actor, current_request, 'read')
            if stamp(current_source) != source_stamp or stamp(current_request) != request_stamp:
                raise ValueError('source or request changed')
            if _repository(binding, policy, context_id, actor, repository_selection) != repository_context:
                raise ValueError('repository selection changed')
            _allowed(root, policy, actor, path, 'read')
            policy.fresh()
        snapshots = []
        cached_result_bytes = 0
        def checked_result(row):
            target = paths.llm_cache / (row['cache_key'] + '.json')
            guard_cache(target)
            try:
                before = stamp(target)
            except FileNotFoundError:
                before = None
            try:
                value = _read_json(root, policy, actor, target)
            except FileNotFoundError:
                value = missing
            guard_cache(target)
            try:
                after = stamp(target)
            except FileNotFoundError:
                after = None
            if before != after or ((value is missing) != (after is None)):
                raise ValueError('cache changed during readback')
            return value, after
        for row in response_request['chunks']:
            result, identity = checked_result(row)
            if result is not missing:
                if (contains_access_secrets(result) or validate_result(result)
                        or not result_matches_request(result, request, row)):
                    raise ValueError('recorded result unavailable')
                row['result_exists'] = True
                row['result_source_id'] = result.get('source_id')
                row['result_chunk_id'] = result.get('chunk_id')
                response_request['cached_calls'] += 1
                response_request['pending_llm_calls'] -= 1
                result_bytes = _json_text(result).encode('utf-8')
                cached_result_bytes += len(result_bytes)
                fingerprint = hashlib.sha256(result_bytes).hexdigest()
            else:
                fingerprint = None
            snapshots.append((row, identity, fingerprint))
        enforce_request_budget(response_request, context_max_bytes=context_max_bytes,
                               request_max_bytes=request_max_bytes)
        if len(canonical_request_text(response_request).encode('utf-8')) > 2_000_000:
            raise ValueError('request exceeds protected response limit')
        root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
        if current != request or current_digest != source_digest:
            raise ValueError('request authority changed')
        for row, identity, fingerprint in snapshots:
            current_result, current_identity = checked_result(row)
            current_fingerprint = (None if current_result is missing else
                hashlib.sha256(_json_text(current_result).encode('utf-8')).hexdigest())
            if current_identity != identity or current_fingerprint != fingerprint:
                raise ValueError('cache changed before delivery')
        # Recheck all identities once more: a result read early in the final
        # pass may have changed while later selected results were inspected.
        for row, identity, _ in snapshots:
            target = paths.llm_cache / (row['cache_key'] + '.json')
            _allowed(root, policy, actor, target, 'read')
            try:
                current_identity = stamp(target)
            except FileNotFoundError:
                current_identity = None
            if current_identity != identity:
                raise ValueError('cache changed before delivery')
        if (stamp(_source(root, policy, context_id, source_ref, actor)) != source_stamp
                or stamp(request_path) != request_stamp):
            raise ValueError('source or request changed')
        try:
            _check_reuse_dependencies(root, policy, actor, prior_dependencies, current=request)
        except (ValueError, OSError):
            # Historical review is optional. Recheck the live request before
            # dropping the candidate, so authority changes still fail closed.
            root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
            if current != request or current_digest != source_digest:
                raise ValueError('request authority changed')
            prior_review = {'status': 'unavailable', 'previous_request_id': previous_request_id,
                            'selected_chunk_ids': list(candidate_chunk_ids),
                            'coverage': 'historical candidate changed; current request unchanged'}
        policy.fresh()
    except (ValueError, OSError, UnicodeError) as exc:
        raise ProtectedPartialError('cache readback unavailable; partial effects may exist; inspect before retry') from exc
    if (prior_review is not None and len(canonical_request_text(
            {'request': response_request, 'historical_review': prior_review}).encode('utf-8')) > 2_000_000):
        prior_review = {'status': 'unavailable', 'previous_request_id': previous_request_id,
                        'selected_chunk_ids': list(candidate_chunk_ids),
                        'reason': 'candidate_response_budget_exceeded',
                        'coverage': 'no historical candidate bodies returned'}
    return {'source_id': source_id, 'request_id': request_id, 'request': response_request,
            **({'historical_review': prior_review} if prior_review is not None else {}),
            'cache_readback': 'exact authorized keys rechecked before response; retained request is unchanged',
            'result_budget': {'max_combined_result_bytes': 2_000_000, 'cached_result_bytes': cached_result_bytes,
                'status': 'exceeded' if cached_result_bytes > 2_000_000 else 'within_limit',
                'coverage': 'selected cached results only; future results not counted'},
            'coverage': projected['context_omissions'],
            'legacy_coverage': 'shared legacy artifacts not inspected; requalification required'}


def _open_bound(root, binding, *, context_id, approved_revision, entry_folder, entry_index,
                source_ref, source_id, request_id, context_max_bytes, request_max_bytes,
                artifact_context=None, perspective_refs=None, context_selection=None, repository_selection=None,
                csv_delimiter=None):
    csv_delimiter = _csv_delimiter(source_ref, csv_delimiter)
    actor = context_id if artifact_context is None else artifact_context
    root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
        entry_folder, entry_index, context_max_bytes, actor)
    current, projected, selection, required, optional, selected_perspectives = _selected_packet(
        root, policy, config, context_id, actor, approved_revision, entry_folder, entry_index,
        context_max_bytes, source_id, context_selection, perspective_refs, source_ref, repository_selection,
        csv_delimiter)
    _check_repository_grant_associations(projected, binding, policy, context_id, actor, repository_selection)
    repository_context = _repository(binding, policy, context_id, actor, repository_selection)
    _check_repository_associations(projected, repository_context)
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
    if csv_delimiter is not None:
        expected_auth['csv_delimiter'] = csv_delimiter
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
        source_ref, request.get('source_context'), config, actor, expected_digest=digest,
        csv_delimiter=csv_delimiter)
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
           context_selection=None, repository_selection=None, csv_delimiter=None):
    """Record host-supplied result objects against the exact retained request."""
    options = dict(context_id=context_id, approved_revision=approved_revision,
        entry_folder=entry_folder, entry_index=entry_index, source_ref=source_ref,
        source_id=source_id, request_id=request_id, context_max_bytes=context_max_bytes,
        request_max_bytes=request_max_bytes, artifact_context=artifact_context, perspective_refs=perspective_refs,
        context_selection=context_selection, repository_selection=repository_selection, csv_delimiter=csv_delimiter)
    actor = context_id if artifact_context is None else artifact_context
    # Qualify the explicit selection and associations before opening any
    # independent repository; its retained context also determines the path.
    root, policy, config, paths, first_request, first_digest = _open_bound(root, binding, **options)
    repository_context = first_request.get('repository_context')
    source_path = _source(root, policy, context_id, source_ref, actor)
    request_path = _request_path(paths, source_id, request_id, repository_context)
    _allowed(root, policy, actor, request_path, 'read')
    def stamp(path):
        value = path.stat()
        return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                value.st_mtime_ns, value.st_ctime_ns)
    policy.fresh()
    source_stamp, request_stamp = stamp(source_path), stamp(request_path)
    policy.fresh()
    root, policy, config, paths, request, digest = _open_bound(root, binding, **options)
    if (request != first_request or digest != first_digest or stamp(source_path) != source_stamp
            or stamp(request_path) != request_stamp):
        raise ValueError('request authority changed')
    if (not isinstance(results, list) or not results or len(results) > 1000
            or len(_json_text(results).encode('utf-8')) > 2_000_000 or contains_access_secrets(results)):
        raise ValueError('result unavailable')
    rows = request['chunks']
    keys = set()
    rows_by_key = {}
    for row in rows:
        rows_by_key.setdefault(row['cache_key'], []).append(row)
    batch_result_bytes = 0
    for result in results:
        if not isinstance(result, dict):
            raise ValueError('result unavailable')
        result_bytes = len(_json_text(result).encode('utf-8'))
        batch_result_bytes += result_bytes
        if result_bytes > 2_000_000:
            raise ValueError('result exceeds protected retention limit')
        key = result.get('cache_key')
        if not isinstance(key, str):
            raise ValueError('result unavailable')
        matches = [row for row in rows_by_key.get(key, ())
                   if result_matches_request(result, request, row, recording=True)]
        if len(matches) != 1 or key in keys:
            raise ValueError('result unavailable')
        keys.add(key)
        target = paths.llm_cache / (key + '.json')
        _allowed(root, policy, actor, target, 'read')
        _allowed(root, policy, actor, target, 'write')
    from wiki_core.llm.context_pass import validate_result
    if any(validate_result(result) for result in results):
        raise ValueError('result unavailable')
    def guard(target):
        nonlocal root, policy, config, paths
        root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
            entry_folder, entry_index, context_max_bytes, actor)
        current_source = _source(root, policy, context_id, source_ref, actor)
        current_request = _request_path(paths, source_id, request_id, repository_context)
        _allowed(root, policy, actor, current_request, 'read')
        if stamp(current_source) != source_stamp or stamp(current_request) != request_stamp:
            raise ValueError('source or request changed')
        if _repository(binding, policy, context_id, actor, repository_selection) != repository_context:
            raise ValueError('repository selection changed')
        _allowed(root, policy, actor, target, 'read')
        _allowed(root, policy, actor, target, 'write')
        policy.fresh()
    written = []
    try:
        for result in results:
            target = paths.llm_cache / (result['cache_key'] + '.json')
            guard(target)
            _write_once(root, policy, actor, target, result)
            guard(target)
            written_stamp = stamp(target)
            if _read_json(root, policy, actor, target) != result:
                raise ValueError('result differs after write')
            guard(target)
            if stamp(target) != written_stamp:
                raise ValueError('result changed after write')
            written.append((target, written_stamp))
        root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
        if current != request or current_digest != digest:
            raise ValueError('request authority changed')
        for target, written_stamp in written:
            guard(target)
            if stamp(target) != written_stamp:
                raise ValueError('result changed after write')
        if (stamp(_source(root, policy, context_id, source_ref, actor)) != source_stamp
                or stamp(request_path) != request_stamp):
            raise ValueError('source or request changed')
        policy.fresh()
    except (ValueError, OSError) as exc:
        raise ProtectedPartialError('partial effects may exist; inspect before retry') from exc
    return {'recorded': len(written), 'request_id': request_id,
            'result_budget': {'max_combined_result_bytes': 2_000_000,
                'batch_result_bytes': batch_result_bytes,
                'status': 'aggregate_not_checked',
                'coverage': 'submitted batch only; use prepare for current selected aggregate'},
            'legacy_coverage': 'shared legacy artifacts not inspected; requalification required'}


def compare_repositories(root, binding, *, context_id, approved_revision, entry_folder, entry_index,
                         source_ref, source_id, request_id, repository_selection,
                         previous_repository_selection, current_repository_selection, source_page, candidates,
                         context_selection=None, perspective_refs=None, artifact_context=None,
                         context_max_bytes=100_000, request_max_bytes=1_000_000, csv_delimiter=None):
    """Compare explicitly authorized revisions; report suggestions, never effects or consumption."""
    from wiki_core.consolidate import compare_repository_candidates
    from wiki_core.context_selection import _metadata
    from wiki_core.context_packet import guarded_context_read, guard_folder_blob
    from wiki_core.llm.context_pass import validate_result
    from wiki_core.repo_read import remote_identity
    from wiki_core.repository_reader import RepositoryReader
    actor = context_id if artifact_context is None else artifact_context
    root, policy, config, paths = _authority(root, binding, context_id, approved_revision,
        entry_folder, entry_index, context_max_bytes, actor)
    ids = _selection_ids(repository_selection)
    if previous_repository_selection not in ids or not isinstance(current_repository_selection, str):
        raise ValueError('repository comparison unavailable')
    grants = {item: authorize_repository_grant(binding, policy, context_id, actor, item)
              for item in dict.fromkeys(ids + [current_repository_selection])}
    previous_grant, current_grant = grants[previous_repository_selection], grants[current_repository_selection]
    if (previous_grant.root != current_grant.root
            or (previous_grant._physical_root is not None and current_grant._physical_root is not None
                and previous_grant._physical_root != current_grant._physical_root)
            or (previous_grant._physical_storage is not None and current_grant._physical_storage is not None
                and previous_grant._physical_storage != current_grant._physical_storage)
            or previous_grant.identity != current_grant.identity or previous_grant.path != current_grant.path):
        raise ValueError('repository comparison unavailable')
    if (not isinstance(candidates, list) or not 1 <= len(candidates) <= 128
            or any(not isinstance(ref, str) for ref in candidates)):
        raise ValueError('repository comparison unavailable')
    source_page = safe_path(source_page)
    refs = [safe_path(ref) for ref in candidates]
    if len(set([source_page, *refs])) != len(refs) + 1 or contains_access_secrets([source_page, refs]):
        raise ValueError('repository comparison unavailable')
    if not isinstance(context_selection, dict):
        raise ValueError('repository comparison requires the selected source page')
    repository_pages = context_selection.get('repository_source_pages', {})
    if not isinstance(repository_pages, dict):
        raise ValueError('repository comparison requires the selected source page')
    mapped_page = repository_pages.get(previous_repository_selection)
    if (mapped_page if mapped_page is not None else context_selection.get('source_page')) != source_page:
        raise ValueError('repository comparison requires the selected source page')
    source_reason = ('Explicit ingestion repository_source_page:' + previous_repository_selection
                     if mapped_page is not None else 'Explicit ingestion source_page')
    for ref in [source_page, *refs]:
        if not ref.endswith('.md'):
            raise ValueError('repository comparison unavailable')
        _allowed(root, policy, context_id, root / ref, 'read')
        _allowed(root, policy, actor, root / ref, 'read')
    options = dict(context_id=context_id, approved_revision=approved_revision, entry_folder=entry_folder,
        entry_index=entry_index, source_ref=source_ref, source_id=source_id, request_id=request_id,
        context_max_bytes=context_max_bytes, request_max_bytes=request_max_bytes, artifact_context=artifact_context,
        perspective_refs=perspective_refs, context_selection=context_selection, repository_selection=repository_selection,
        csv_delimiter=csv_delimiter)
    root, policy, config, paths, request, digest = _open_bound(root, binding, **options)
    retained = request.get('repository_context')
    rows = retained if isinstance(retained, list) else [retained]
    old = [row for row in rows if isinstance(row, dict) and row.get('selection_id') == previous_repository_selection]
    if len(old) != 1: raise ValueError('repository comparison unavailable')
    old = old[0]
    current = selected_repository(binding, policy, context_id, actor, current_repository_selection)
    if ((old['repository_identity'], old['path']) != (current['repository_identity'], current['path'])
            or previous_grant._physical_root != current_grant._physical_root
            or previous_grant._physical_storage != current_grant._physical_storage):
        raise ValueError('repository comparison unavailable')
    for row in request['chunks']:
        result = _read_json(root, policy, actor, paths.llm_cache / (row['cache_key'] + '.json'))
        if contains_access_secrets(result) or validate_result(result) or not result_matches_request(result, request, row):
            raise ValueError('recorded result unavailable')
    metadata = []
    page_hashes = []
    remaining = 1_000_000
    reader = RepositoryReader(root, approved_revision)
    for ref in [source_page, *refs]:
        _allowed(root, policy, context_id, root / ref, 'read')
        _allowed(root, policy, actor, root / ref, 'read')
        guard_folder_blob(root, policy, ref)
        size = reader.blob_size(ref)
        if size > remaining: raise ValueError('repository comparison unavailable')
        remaining -= size
    remaining = 1_000_000
    for ref in [source_page, *refs]:
        _allowed(root, policy, context_id, root / ref, 'read')
        _allowed(root, policy, actor, root / ref, 'read')
        document = guarded_context_read(reader, policy, ref)
        raw = document['text'].encode('utf-8')
        if len(raw) > remaining: raise ValueError('repository comparison unavailable')
        remaining -= len(raw)
        page_hashes.append(document['content_sha256'])
        metadata.append(_metadata(document))
    selected_pages = [row for row in request['block_context_package']['inputs']
                      if row.get('ref') == source_page and row.get('reason') == source_reason]
    if len(selected_pages) != 1 or selected_pages[0]['document_sha256'] != page_hashes[0]:
        raise ValueError('repository source association changed')
    source = metadata[0]
    locator = source.get('source_locator')
    if (source.get('page_type') != 'source' or source.get('platform') != 'repo' or not isinstance(locator, str)
            or remote_identity(locator if '://' in locator or '@' in locator else 'https://' + locator)[0] != old['repository_identity']):
        raise ValueError('repository source association unavailable')
    changed = old['content_sha256'] != current['content_sha256']
    result = compare_repository_candidates(source_page, refs, metadata[1:], changed)
    _, policy, _, _, again, repeated_digest = _open_bound(root, binding, **options)
    if (again != request or repeated_digest != digest
            or selected_repository(binding, policy, context_id, actor, current_repository_selection) != current):
        raise ValueError('repository comparison changed')
    for ref in [source_page, *refs]:
        _allowed(root, policy, context_id, root / ref, 'read')
        _allowed(root, policy, actor, root / ref, 'read')
    policy.fresh()
    return {'repository_comparison': {'identity': old['repository_identity'], 'path': old['path'],
        'before_revision': old['revision'], 'after_revision': current['revision'],
        'before_digest': old['content_sha256'], 'after_digest': current['content_sha256'], 'changed': changed},
        'source_page': source_page, 'candidates': result,
        'coverage': 'explicit_candidates_only; selected_repository_only; file_consumption_unknown',
        'effect': 'manual_suggestion_only; no_gate_effect', 'review': 'not_performed', 'write': 'not_performed'}


def _approved_candidate_documents(root, policy, context_id, actor, revision, refs):
    """Open only selected, authorized candidates at the pinned approved commit."""
    if not refs:
        policy.fresh()
        return {}
    from wiki_core.context_packet import guard_folder_blob, guarded_context_read
    from wiki_core.repository_reader import RepositoryReader
    reader = RepositoryReader(root, revision)
    remaining = 1_000_000
    for ref in refs:
        if not ref.endswith('.md'):
            raise ValueError('candidate unavailable')
        _allowed(root, policy, context_id, root / ref, 'read')
        _allowed(root, policy, actor, root / ref, 'read')
        guard_folder_blob(root, policy, ref)
        size = reader.blob_size(ref)
        policy.fresh()
        if size > remaining:
            raise ValueError('candidate budget exceeded')
        remaining -= size
    documents = {}
    for ref in refs:
        _allowed(root, policy, context_id, root / ref, 'read')
        _allowed(root, policy, actor, root / ref, 'read')
        document = guarded_context_read(reader, policy, ref)
        if document['revision'] != revision or contains_access_secrets(document['text']):
            raise ValueError('candidate unavailable')
        documents[ref] = document
    policy.fresh()
    return documents


def _revalidate_candidate_scopes(root, policy, context_id, actor, refs):
    for ref in refs:
        _allowed(root, policy, context_id, root / ref, 'read')
        _allowed(root, policy, actor, root / ref, 'read')
    policy.fresh()


def consolidate(root, binding, *, context_id, approved_revision, entry_folder, entry_index,
                source_ref, source_id, request_id, source_page, event_target, date,
                candidates=(), context_max_bytes=100_000, request_max_bytes=1_000_000,
                artifact_context=None, perspective_refs=None, context_selection=None, repository_selection=None,
                csv_delimiter=None):
    """Prepare an event and packet; incorporation and review remain separate."""
    from wiki_core.consolidate import aggregate_results, build_event_markdown, build_packet
    options = dict(context_id=context_id, approved_revision=approved_revision,
        entry_folder=entry_folder, entry_index=entry_index, source_ref=source_ref,
        source_id=source_id, request_id=request_id, context_max_bytes=context_max_bytes,
        request_max_bytes=request_max_bytes, artifact_context=artifact_context, perspective_refs=perspective_refs,
        context_selection=context_selection, repository_selection=repository_selection, csv_delimiter=csv_delimiter)
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
    result_bytes = 0
    def read_bound_result(row):
        nonlocal result_bytes
        from wiki_core.llm.context_pass import validate_result
        cache_path = paths.llm_cache / (row['cache_key'] + '.json')
        result = _read_json(root, policy, actor, cache_path)
        if (contains_access_secrets(result) or validate_result(result)
                or not result_matches_request(result, request, row)):
            raise ValueError('result unavailable')
        result_bytes += len(_json_text(result).encode('utf-8'))
        if result_bytes > 2_000_000:
            raise ProtectedResultBudgetError('combined results exceed 2 MB review limit')
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
    candidate_documents = _approved_candidate_documents(root, policy, context_id, actor, approved_revision, refs)
    packet = build_packet(aggregated, root, config, paths, candidates=refs, candidate_documents=candidate_documents)
    review_output = {'view': 'integration', 'source_id': source_id, 'request_id': request_id,
                     'packet': packet, 'event_status': 'not checked', 'integration': 'not assessed'}
    if len(canonical_request_text(review_output).encode('utf-8')) > 2_000_000:
        raise ProtectedResultBudgetError('integration review output exceeds 2 MB limit')
    markdown = build_event_markdown(aggregated, config=config, context=request['source_context'],
        date=date, source_page=source_page, source_type=classify_source(source_ref),
        event_dir=target.parent, root=root, yaml_safe=True,
        protected_provenance={'source_locator': source_ref, 'policy_revision': approved_revision,
            'executor_context': context_id, 'integrator_context': actor,
            'source_page_association': 'operator_selected_unverified',
            'extraction_limitations': _format_omissions(source_ref, csv_delimiter),
            **({'csv_delimiter': csv_delimiter} if csv_delimiter is not None else {})},
        impact=dict(packet.get('impact') or {}))
    if contains_access_secrets([packet, markdown]):
        raise ValueError('output unavailable')
    if len(_json_text(packet).encode('utf-8')) > 2_000_000 or len(markdown.encode('utf-8')) > 2_000_000:
        raise ValueError('output exceeds protected retention limit')
    root, policy, config, paths, current, current_digest = _open_bound(root, binding, **options)
    if current != request or current_digest != digest:
        raise ValueError('request authority changed')
    _revalidate_candidate_scopes(root, policy, context_id, actor, refs)
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
        _revalidate_candidate_scopes(root, policy, context_id, actor, refs)
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
        _revalidate_candidate_scopes(root, policy, context_id, actor, refs)
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
        _revalidate_candidate_scopes(root, policy, context_id, actor, refs)
    except (ValueError, OSError) as exc:
        raise ProtectedPartialError('partial effects may exist; inspect before retry') from exc
    return {'event': event_target, 'request_id': request_id,
            'coverage': 'explicit candidates only; linked sources not inspected',
            'integration': 'pending review and incorporation',
            'legacy_coverage': 'shared legacy artifacts not inspected; requalification required'}


def inspect(root, binding, *, context_id, approved_revision, entry_folder, entry_index,
            source_ref, source_id, request_id, view, chunk_ids=None, candidates=None,
            max_output_bytes=1_000_000, context_max_bytes=100_000, request_max_bytes=1_000_000,
            artifact_context=None, perspective_refs=None, context_selection=None, repository_selection=None,
            csv_delimiter=None):
    """Read explicitly selected, requalified protected results or a retained proposal."""
    from wiki_core.consolidate import aggregate_results, build_packet
    from wiki_core.llm.context_pass import validate_result

    if (type(max_output_bytes) is not int or not 1 <= max_output_bytes <= 2_000_000
            or view not in ('results', 'integration')):
        raise ValueError('inspection unavailable')
    if view == 'results':
        if (candidates is not None or not isinstance(chunk_ids, list) or not chunk_ids
                or len(chunk_ids) > 32 or any(not isinstance(x, str) for x in chunk_ids)
                or len(set(chunk_ids)) != len(chunk_ids)):
            raise ValueError('inspection selection unavailable')
        refs = []
    else:
        if (chunk_ids is not None or not isinstance(candidates, list) or len(candidates) > 128
                or any(not isinstance(x, str) for x in candidates)):
            raise ValueError('inspection selection unavailable')
        refs = [safe_path(x) for x in candidates]
        if len(refs) != len(set(refs)) or contains_access_secrets(refs):
            raise ValueError('inspection selection unavailable')
    options = dict(context_id=context_id, approved_revision=approved_revision,
        entry_folder=entry_folder, entry_index=entry_index, source_ref=source_ref,
        source_id=source_id, request_id=request_id, context_max_bytes=context_max_bytes,
        request_max_bytes=request_max_bytes, artifact_context=artifact_context, perspective_refs=perspective_refs,
        context_selection=context_selection, repository_selection=repository_selection, csv_delimiter=csv_delimiter)
    actor = context_id if artifact_context is None else artifact_context
    root, policy, config, paths, request, digest = _open_bound(root, binding, **options)
    repository_context = request.get('repository_context')
    def stamp(path):
        value = path.stat()
        return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                value.st_mtime_ns, value.st_ctime_ns)
    source_path = _source(root, policy, context_id, source_ref, actor)
    request_path = _request_path(paths, source_id, request_id, repository_context)
    _allowed(root, policy, actor, request_path, 'read')
    policy.fresh()
    source_stamp, request_stamp = stamp(source_path), stamp(request_path)
    policy.fresh()
    def refresh():
        current = _open_bound(root, binding, **options)
        if (current[4] != request or current[5] != digest or stamp(source_path) != source_stamp
                or stamp(request_path) != request_stamp):
            raise ValueError('request authority changed')
        return current
    root, policy, config, paths, _, _ = refresh()
    def guard(path, *, next_is_read=False):
        # The policy and actors were qualified at batch entry. Check the
        # selected physical boundaries here; _read_json checks the trusted ref
        # immediately before and after every body read.
        cache = _STAGE_CACHE.get()
        if cache is None:
            raise ValueError('stage unavailable')
        _check_physical_context(root, entry_folder, cache['context_paths'].get(str(root), (set(), set())))
        current_source = _source(root, policy, context_id, source_ref, actor)
        current_request = _request_path(paths, source_id, request_id, repository_context)
        _allowed(root, policy, actor, current_request, 'read')
        if stamp(current_source) != source_stamp or stamp(current_request) != request_stamp:
            raise ValueError('source or request changed')
        if _repository(binding, policy, context_id, actor, repository_selection) != repository_context:
            raise ValueError('repository selection changed')
        _allowed(root, policy, actor, path, 'read')
        if not next_is_read:
            policy.fresh()

    rows = request['chunks']
    if view == 'results':
        by_id = {row['chunk_id']: row for row in rows}
        if len(by_id) != len(rows) or any(item not in by_id for item in chunk_ids):
            raise ValueError('inspection selection unavailable')
        selected = [by_id[item] for item in chunk_ids]
    else:
        selected = rows
        _revalidate_candidate_scopes(root, policy, context_id, actor, refs)
    for row in selected:
        _allowed(root, policy, actor, paths.llm_cache / (row['cache_key'] + '.json'), 'read')

    total = 0
    result_fingerprints = {}
    def read_result(row):
        nonlocal total
        target = paths.llm_cache / (row['cache_key'] + '.json')
        guard(target, next_is_read=True)
        initial_stamp = stamp(target)
        remaining = 2_000_000 - total
        if remaining <= 0:
            raise ProtectedResultBudgetError('combined results exceed 2 MB review limit')
        result = _read_json(root, policy, actor, target)
        if (contains_access_secrets(result) or validate_result(result)
                or not result_matches_request(result, request, row)):
            raise ValueError('result unavailable')
        total += len(_json_text(result).encode('utf-8'))
        if total > 2_000_000:
            raise ProtectedResultBudgetError('combined results exceed 2 MB review limit')
        fingerprint = hashlib.sha256(canonical_request_text(result).encode('utf-8')).digest()
        guard(target)
        if stamp(target) != initial_stamp:
            raise ValueError('result changed')
        previous = result_fingerprints.setdefault(row['cache_key'], (initial_stamp, fingerprint))
        if previous != (initial_stamp, fingerprint):
            raise ValueError('result changed')
        return result

    if view == 'results':
        output = {'view': view, 'source_id': source_id, 'request_id': request_id,
                  'results': [{'chunk_id': row['chunk_id'], 'result': read_result(row)} for row in selected]}
    else:
        aggregated = aggregate_results(request, paths.llm_cache, root=root, result_reader=read_result)
        aggregated['folder_request_id'] = request_id
        aggregated['source_hash_sha256'] = digest
        if request.get('repository_context') is not None:
            selected_repos = request['repository_context']
            repo_rows = selected_repos if isinstance(selected_repos, list) else [selected_repos]
            aggregated['independent_git_sources'] = [{key: row[key] for key in
                ('selection_id', 'repository_identity', 'host_binding_digest', 'revision', 'path', 'blob',
                 'document_sha256', 'content_sha256')} for row in repo_rows]
        guard(paths.extraction_events / f'protected-{hashlib.sha256(source_id.encode()).hexdigest()}-{request_id}-integration-packet.json')
        documents = _approved_candidate_documents(root, policy, context_id, actor, approved_revision, refs)
        expected = build_packet(aggregated, root, config, paths, candidates=refs, candidate_documents=documents)
        _revalidate_candidate_scopes(root, policy, context_id, actor, refs)
        packet_path = paths.extraction_events / f'protected-{hashlib.sha256(source_id.encode()).hexdigest()}-{request_id}-integration-packet.json'
        guard(packet_path, next_is_read=True)
        packet_stamp = stamp(packet_path)
        retained = _read_json(root, policy, actor, packet_path)
        if retained != expected or contains_access_secrets(retained):
            raise ValueError('integration packet unavailable')
        guard(packet_path)
        if stamp(packet_path) != packet_stamp:
            raise ValueError('integration packet changed')
        output = {'view': view, 'source_id': source_id, 'request_id': request_id, 'packet': retained,
                  'event_status': 'not checked', 'integration': 'not assessed'}
    if len(canonical_request_text(output).encode('utf-8')) > max_output_bytes:
        raise ValueError('inspection output budget exceeded')
    root, policy, _, paths, _, _ = refresh()
    _revalidate_candidate_scopes(root, policy, context_id, actor, refs)
    for key, (initial_stamp, fingerprint) in result_fingerprints.items():
        target = paths.llm_cache / (key + '.json')
        guard(target, next_is_read=True)
        if stamp(target) != initial_stamp:
            raise ValueError('result changed')
        readback = _read_json(root, policy, actor, target)
        if hashlib.sha256(canonical_request_text(readback).encode('utf-8')).digest() != fingerprint:
            raise ValueError('result changed')
        guard(target)
        if stamp(target) != initial_stamp:
            raise ValueError('result changed')
    if view == 'integration':
        guard(packet_path, next_is_read=True)
        if _read_json(root, policy, actor, packet_path) != retained:
            raise ValueError('integration packet changed')
        guard(packet_path)
        if stamp(packet_path) != packet_stamp:
            raise ValueError('integration packet changed')
    for key, (initial_stamp, _fingerprint) in result_fingerprints.items():
        target = paths.llm_cache / (key + '.json')
        _allowed(root, policy, actor, target, 'read')
        if stamp(target) != initial_stamp:
            raise ValueError('result changed')
    if view == 'integration' and stamp(packet_path) != packet_stamp:
        raise ValueError('integration packet changed')
    _revalidate_candidate_scopes(root, policy, context_id, actor, refs)
    cache = _STAGE_CACHE.get()
    if cache is None:
        raise ValueError('stage unavailable')
    _check_physical_context(root, entry_folder, cache['context_paths'].get(str(root), (set(), set())))
    if stamp(_source(root, policy, context_id, source_ref, actor)) != source_stamp or stamp(request_path) != request_stamp:
        raise ValueError('source or request changed')
    policy.fresh()
    return output


# Cache is scoped to one operation, never shared across requests or threads.
prepare = _scoped_stage(prepare)
record = _scoped_stage(record)
consolidate = _scoped_stage(consolidate)
compare_repositories = _scoped_stage(compare_repositories)
inspect = _scoped_stage(inspect)
