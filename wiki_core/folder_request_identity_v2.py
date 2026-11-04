"""Stable identity of a single folder-bound emitted request."""
import hashlib
import json
import re


def folder_request_identity(request):
    if (not isinstance(request, dict) or request.get('context_binding_version') != 2
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


def folder_request_path(paths, request):
    request_id = folder_request_identity(request)
    if request.get('folder_request_id') != request_id:
        raise ValueError('folder request identity differs')
    source_digest = hashlib.sha256(request['source_id'].encode()).hexdigest()
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


def write_folder_result(cache_dir, result):
    """Create once; repeat the same result idempotently, never replace it."""
    import os
    from wiki_core.context_selection import strict_json_loads
    from wiki_core.llm.context_pass import validate_result, ContextRequestBlocked
    errors = validate_result(result)
    key = result.get('cache_key') if isinstance(result, dict) else None
    if errors or not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}', key):
        raise ValueError('invalid folder result')
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / (key + '.json')
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n'
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(path, flags, 0o600)
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
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(text)
    return path
