"""Source-specific claim projections; no catalogue, migration or access grant."""
from __future__ import annotations

import re

from wiki_core.context_policy import safe_path
from wiki_core.repo_read import contains_access_secrets

FIELD = 'folder_source_provenance'
VERSION = 'wiki.folder-source-provenance/v2'
SINGLETON = ('source_authorization', 'independent_repo_read',
             'independent_repo_additional_reads', 'independent_repo_source_ref')


def _repository_valid(row):
    if (not isinstance(row, dict) or set(row) != {'identity', 'revision', 'path', 'blob',
            'document_sha256', 'content_sha256', 'section', 'field'}
            or not isinstance(row['identity'], str) or not row['identity']
            or any(not isinstance(row[k], str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', row[k])
                   for k in ('revision', 'blob'))
            or any(not isinstance(row[k], str) or not re.fullmatch(r'[0-9a-f]{64}', row[k])
                   for k in ('document_sha256', 'content_sha256'))
            or row['section'] is not None or row['field'] is not None):
        return False
    safe_path(row['path'])
    return True


def _repository_set(primary, additional):
    if not _repository_valid(primary):
        raise ValueError('repository projection unavailable')
    if additional is not None:
        if (not isinstance(additional, list) or not 1 <= len(additional) <= 15
                or any(not _repository_valid(row) or row['identity'] != primary['identity']
                       or row['revision'] != primary['revision'] for row in additional)
                or len({row['path'] for row in [primary, *additional]}) != len(additional) + 1):
            raise ValueError('repository projection unavailable')


def _capture_valid(capture):
    from wiki_core.folder_capture_v2 import CAPTURE_KEYS
    if (not isinstance(capture, dict) or set(capture) != CAPTURE_KEYS
            or capture.get('source_kind') != 'staged_raw' or capture.get('source_revision') is not None
            or capture.get('association') != 'caller_selected_unverified'
            or capture.get('external_origin_verification') != 'not_verified'
            or capture.get('external_freshness') != 'not_verified'
            or not isinstance(capture.get('source_origin'), dict)
            or not isinstance(capture.get('canonical_revision'), str)
            or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', capture['canonical_revision'])
            or any(not isinstance(capture.get(k), str) or not re.fullmatch(r'[0-9a-f]{64}', capture[k])
                   for k in ('source_sha256', 'canonical_sha256'))):
        raise ValueError('raw capture projection unavailable')
    safe_path(capture['ref']); safe_path(capture['canonical_ref'])


def _has_requirement(metadata, source, revision):
    requirements = metadata.get('information_requirements', [])
    if not isinstance(requirements, list) or len(requirements) > 64:
        raise ValueError('requirements unavailable')
    source_requirements = [r for r in requirements if isinstance(r, dict) and r.get('target') == source and 'query' not in r]
    matches = [r for r in source_requirements
               if r.get('consumed_revision') == revision and r.get('fields') == ['*']
               and r.get('temporal') == 'current' and r.get('use') == 'interpretation'
               and r.get('classification') == 'source' and 'query' not in r]
    if len(source_requirements) != 1 or len(matches) != 1:
        raise ValueError('source requirement unavailable')


def _entries(metadata, *, adding=False):
    if not isinstance(metadata, dict) or contains_access_secrets(metadata):
        raise ValueError('source projections unavailable')
    singleton = {}
    capture = metadata.get('source_authorization')
    repo = metadata.get('independent_repo_read')
    extra = metadata.get('independent_repo_additional_reads')
    repo_ref = metadata.get('independent_repo_source_ref')
    if capture is not None and any(value is not None for value in (repo, extra, repo_ref)):
        raise ValueError('ambiguous singular source projections')
    if capture is not None:
        _capture_valid(capture)
        singleton = {'source_authorization':capture}
        singleton_ref = capture['canonical_ref']
    elif repo is not None:
        _repository_set(repo, extra)
        if repo_ref is not None:
            singleton_ref = safe_path(repo_ref)
        elif adding or FIELD in metadata:
            raise ValueError('legacy repository source association unavailable')
        else:
            singleton_ref = None
        singleton = {'independent_repo_read':repo}
        if extra is not None: singleton['independent_repo_additional_reads'] = extra
        if repo_ref is not None: singleton['independent_repo_source_ref'] = repo_ref
    else:
        if repo_ref is not None or extra is not None:
            raise ValueError('repository projection unavailable')
        singleton_ref = None

    if adding and singleton_ref is not None:
        requirements = metadata.get('information_requirements', [])
        matches = [r for r in requirements if isinstance(r, dict) and r.get('target') == singleton_ref
                   and r.get('fields') == ['*'] and r.get('temporal') == 'current'
                   and r.get('use') == 'interpretation' and r.get('classification') == 'source'
                   and 'query' not in r and isinstance(r.get('consumed_revision'), str)
                   and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', r['consumed_revision'])] if isinstance(requirements, list) else []
        if len(matches) != 1 or (capture is not None and matches[0]['consumed_revision'] != capture['canonical_revision']):
            raise ValueError('prior source requirement unavailable')
        _has_requirement(metadata, singleton_ref, matches[0]['consumed_revision'])

    if FIELD not in metadata:
        return singleton_ref, singleton, []
    value = metadata[FIELD]
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'entries'}
            or value['schema_version'] != VERSION or not isinstance(value['entries'], list)
            or not 1 <= len(value['entries']) <= 64):
        raise ValueError('source provenance list unavailable')
    entries = value['entries']
    seen = {singleton_ref} if singleton_ref is not None else set()
    for row in entries:
        if not isinstance(row, dict) or not {'canonical_ref','canonical_revision'} <= set(row):
            raise ValueError('source projection unavailable')
        source = safe_path(row['canonical_ref']); revision = row['canonical_revision']
        if source in seen or not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision):
            raise ValueError('duplicate or invalid source projection')
        seen.add(source)
        if 'source_authorization' in row:
            if set(row) != {'canonical_ref','canonical_revision','source_authorization'}:
                raise ValueError('invalid raw projection')
            _capture_valid(row['source_authorization'])
            if (row['source_authorization']['canonical_ref'] != source
                    or row['source_authorization']['canonical_revision'] != revision):
                raise ValueError('raw source association differs')
        else:
            if set(row) not in ({'canonical_ref','canonical_revision','independent_repo_read'},
                                {'canonical_ref','canonical_revision','independent_repo_read','independent_repo_additional_reads'}):
                raise ValueError('invalid repository projection')
            _repository_set(row['independent_repo_read'], row.get('independent_repo_additional_reads'))
        _has_requirement(metadata, source, revision)
    return singleton_ref, singleton, entries


def selected_projection(metadata, source):
    """Return only the projection belonging to one exact canonical source."""
    source = safe_path(source)
    singleton_ref, singleton, entries = _entries(metadata)
    if singleton and (singleton_ref is None or singleton_ref == source):
        return dict(singleton)
    for row in entries:
        if row['canonical_ref'] == source:
            result = {k:v for k,v in row.items() if k not in ('canonical_ref', 'canonical_revision')}
            if 'independent_repo_read' in result:
                result['independent_repo_source_ref'] = source
            return result
    return {}


def validate_provenance(metadata):
    """Validate a page's bounded declarations without authenticating a source."""
    _entries(metadata)


def preserved_projection_kinds(metadata, *, exclude_source=None):
    """Identify prior declarations without reading or revalidating their sources."""
    singleton_ref, singleton, entries = _entries(metadata, adding=True)
    rows = ([singleton] if singleton and singleton_ref != exclude_source else [])
    rows += [row for row in entries if row['canonical_ref'] != exclude_source]
    return (any('source_authorization' in row for row in rows),
            any('independent_repo_read' in row for row in rows))


def requalify_projection(metadata, auth):
    """Replace only the explicitly selected projection, leaving others intact."""
    singleton_ref, singleton, entries = _entries(metadata, adding=True)
    source = safe_path(auth['canonical_ref'])
    matches = [i for i, row in enumerate(entries) if row['canonical_ref'] == source]
    if len(matches) > 1:
        raise ValueError('ambiguous source projection')
    previous = singleton if singleton_ref == source else (entries[matches[0]] if matches else {})
    fresh = add_projection({}, auth)
    old_kind = ('raw' if 'source_authorization' in previous else
                'repo' if 'independent_repo_read' in previous else 'git')
    new_kind = ('raw' if 'source_authorization' in fresh else
                'repo' if 'independent_repo_read' in fresh else 'git')
    if old_kind != new_kind:
        raise ValueError('source projection kind changed')
    result = {k:metadata[k] for k in (*SINGLETON, FIELD) if k in metadata}
    if singleton_ref == source:
        for key in SINGLETON:
            result.pop(key, None)
        result.update(fresh)
    elif matches:
        updated = list(entries)
        row = {k:v for k,v in fresh.items() if k != 'independent_repo_source_ref'}
        updated[matches[0]] = {'canonical_ref':source, 'canonical_revision':auth['canonical_revision'], **row}
        result[FIELD] = {'schema_version':VERSION, 'entries':updated}
    return result


def add_projection(metadata, auth):
    """Preserve old projections exactly and append the current request's projection."""
    singleton_ref, singleton, entries = _entries(metadata, adding=True)
    if not isinstance(auth, dict) or auth.get('source_kind') not in ('git', 'staged_raw'):
        raise ValueError('source kind unavailable')
    if auth['source_kind'] == 'staged_raw' and auth.get('independent_repo_read') is not None:
        raise ValueError('ambiguous source projection')
    source = safe_path(auth['canonical_ref']); revision = auth['canonical_revision']
    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision):
        raise ValueError('source revision unavailable')
    if source == singleton_ref or any(row['canonical_ref'] == source for row in entries):
        raise ValueError('source projection already exists')
    from wiki_core.folder_capture_v2 import CAPTURE_KEYS, repository_receipt_projection
    row = {'canonical_ref':source, 'canonical_revision':revision}
    if auth.get('source_kind') == 'staged_raw':
        row['source_authorization'] = {key:auth[key] for key in CAPTURE_KEYS}
        _capture_valid(row['source_authorization'])
    elif auth.get('independent_repo_read') is not None:
        row['independent_repo_read'] = repository_receipt_projection(auth['independent_repo_read'])
        if auth.get('independent_repo_additional_reads'):
            row['independent_repo_additional_reads'] = [repository_receipt_projection(item)
                                                       for item in auth['independent_repo_additional_reads']]
        _repository_set(row['independent_repo_read'], row.get('independent_repo_additional_reads'))
    else:
        return {k:metadata[k] for k in (*SINGLETON, FIELD) if k in metadata}
    if not singleton and not entries:
        result = {k:v for k,v in row.items() if k not in ('canonical_ref', 'canonical_revision')}
        if 'independent_repo_read' in result:
            result['independent_repo_source_ref'] = source
        return result
    if len(entries) >= 64:
        raise ValueError('source provenance limit exceeded')
    return {**{k:metadata[k] for k in SINGLETON if k in metadata},
            FIELD:{'schema_version':VERSION, 'entries':[*entries, row]}}
