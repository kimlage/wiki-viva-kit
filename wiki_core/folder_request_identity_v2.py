"""Stable identity of a single folder-bound emitted request."""
import hashlib
import json
import re


def _install_once(path, text):
    """Publish a complete file without replacing a concurrent or earlier one."""
    import os
    import tempfile
    fd, temporary = tempfile.mkstemp(prefix='.wiki-retain-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
    finally:
        os.unlink(temporary)


def request_identity(request):
    """Identify a semantic request; this digest does not authorize any read."""
    if (not isinstance(request, dict) or request.get('context_binding_version') not in (None, 1, 2)
            or not isinstance(request.get('source_id'), str)
            or not isinstance(request.get('chunks'), list)):
        raise ValueError('folder request identity unavailable')
    chunks = []
    for row in request['chunks']:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k]
                                             for k in ('chunk_id', 'source_id', 'chunk_hash_sha256', 'context_sha256', 'cache_key')):
            raise ValueError('folder request identity unavailable')
        if any(not re.fullmatch(r'[0-9a-f]{64}', row[k]) for k in ('chunk_hash_sha256', 'context_sha256', 'cache_key')):
            raise ValueError('folder request identity unavailable')
        chunks.append({k:v for k,v in row.items() if k not in ('result_exists', 'result_source_id', 'result_chunk_id')})
    envelope = {k:v for k,v in request.items() if k not in
                ('folder_request_id', 'byte_accounting', 'pending_llm_calls', 'cached_calls', 'chunks')}
    envelope['chunks'] = chunks
    return hashlib.sha256(json.dumps(envelope, sort_keys=True, ensure_ascii=False,
                        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def folder_request_identity(request):
    if not isinstance(request, dict) or request.get('context_binding_version') != 2:
        raise ValueError('folder request identity unavailable')
    return request_identity(request)


def folder_request_path(paths, request):
    request_id = folder_request_identity(request)
    if request.get('folder_request_id') != request_id:
        raise ValueError('folder request identity differs')
    return request_identity_path(paths, request['source_id'], request_id)


def request_identity_path(paths, source_id, request_id):
    """Map identities to the established request filename without granting access."""
    if (not isinstance(source_id, str)
            or not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{64}', request_id)):
        raise ValueError('request identity unavailable')
    source_digest = hashlib.sha256(source_id.encode()).hexdigest()
    return paths.extraction_events / f'folder-{source_digest}-{request_id}-llm-context-request.json'


def validate_retained_folder_request(root, paths, request):
    """Require the exact bounded retained semantic request, without legacy fallback."""
    from pathlib import Path
    from wiki_core.context_selection import strict_json_loads
    from wiki_core.folder_ingestion_v2 import _check_local_boundaries
    expected = folder_request_identity(request)
    path = folder_request_path(paths, request)
    _check_local_boundaries(Path(root), path.relative_to(root).as_posix())
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise ValueError('retained folder request unavailable')
    with path.open('rb') as stream:
        content = stream.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError('retained folder request unavailable')
    data = strict_json_loads(content.decode('utf-8'))
    if (not isinstance(data, dict) or data.get('folder_request_id') != expected
            or folder_request_identity(data) != expected):
        raise ValueError('retained folder request differs')


def retain_folder_request(root, paths, request):
    """Create the semantic request once; a repeat preserves its original bytes."""
    from wiki_core.llm.context_pass import canonical_request_text
    path = folder_request_path(paths, request)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _install_once(path, canonical_request_text(request))
    except FileExistsError:
        validate_retained_folder_request(root, paths, request)
        return path
    return path


def retain_request(root, paths, request):
    """Retain an existing-format request without replacing another context."""
    from pathlib import Path
    from wiki_core.context_selection import strict_json_loads
    from wiki_core.llm.context_pass import canonical_request_text
    from wiki_core.traversal import require_wiki_boundaries
    if request.get('context_binding_version') == 2:
        return retain_folder_request(root, paths, request)
    source_id = request.get('source_id')
    if not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,511}', source_id):
        raise ValueError('invalid source identity')
    identity = request_identity(request)
    legacy = paths.extraction_events / f'{source_id}-llm-context-request.json'
    target = request_identity_path(paths, source_id, identity)
    require_wiki_boundaries(Path(root), directories=(paths.extraction_events,), files=(legacy, target))
    paths.extraction_events.mkdir(parents=True, exist_ok=True)
    if not legacy.exists():
        try:
            _install_once(legacy, canonical_request_text(request))
            return legacy
        except FileExistsError:
            pass
    require_wiki_boundaries(Path(root), files=(legacy,))
    if not legacy.is_file() or legacy.is_symlink() or legacy.stat().st_size > 2_000_000:
        raise ValueError('legacy request unavailable; preserved')
    with legacy.open('rb') as stream:
        raw = stream.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('legacy request unavailable; preserved')
    try:
        existing = strict_json_loads(raw.decode('utf-8'))
        if request_identity(existing) == identity:
            return legacy
    except (ValueError, TypeError, KeyError):
        raise ValueError('legacy request unavailable; preserved') from None
    qualified = {**request, 'folder_request_id': identity}
    require_wiki_boundaries(Path(root), files=(target,))
    try:
        _install_once(target, canonical_request_text(qualified))
    except FileExistsError:
        if not target.is_file() or target.is_symlink() or target.stat().st_size > 2_000_000:
            raise ValueError('existing request unavailable; preserved') from None
        with target.open('rb') as stream:
            raw = stream.read(2_000_001)
        try:
            retained = strict_json_loads(raw.decode('utf-8'))
            if (len(raw) > 2_000_000 or retained.get('folder_request_id') != identity
                    or request_identity(retained) != identity):
                raise ValueError('existing request differs; preserved')
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError('existing request unavailable; preserved') from None
    return target


def write_folder_result(cache_dir, result):
    """Create once; repeat the same result idempotently, never replace it."""
    from wiki_core.context_selection import strict_json_loads
    from wiki_core.llm.context_pass import validate_result, ContextRequestBlocked
    errors = validate_result(result)
    key = result.get('cache_key') if isinstance(result, dict) else None
    if errors or not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}', key):
        raise ValueError('invalid folder result')
    path = cache_dir / (key + '.json')
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n'
    if len(text.encode('utf-8')) > 2_000_000:
        raise ContextRequestBlocked('folder_result_too_large', 'Folder result exceeds the 2000000 byte retention limit.')
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        _install_once(path, text)
    except FileExistsError:
        try:
            if path.is_symlink() or path.stat().st_size > 2_000_000:
                raise ValueError('existing result unavailable')
            with path.open('rb') as stream:
                retained = strict_json_loads(stream.read(2_000_001).decode('utf-8'))
            if json.dumps(retained, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False) != \
                    json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False):
                raise ValueError('existing result differs')
            return path
        except (ValueError, OSError, TypeError, UnicodeError, RecursionError):
            raise ContextRequestBlocked('folder_result_conflict', 'A different or unreadable result already exists for this cache key; it was preserved.') from None
    return path
