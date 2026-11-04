"""Stable identity of a single folder-bound emitted request."""
import hashlib
import json
import re


def folder_request_identity(request):
    from wiki_core.llm.context_pass import context_fingerprint
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
        chunks.append({k:row[k] for k in ('chunk_id', 'source_id', 'chunk_hash_sha256', 'context_sha256', 'cache_key')})
    envelope = {'version':'wiki.folder-request-identity/v2', 'source_id':request['source_id'],
                'context':context_fingerprint(request, {'source_id':request['source_id']}), 'chunks':chunks}
    return hashlib.sha256(json.dumps(envelope, sort_keys=True, ensure_ascii=False,
                        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def folder_request_path(paths, request):
    request_id = folder_request_identity(request)
    if request.get('folder_request_id') not in (None, request_id):
        raise ValueError('folder request identity differs')
    source_digest = hashlib.sha256(request['source_id'].encode()).hexdigest()
    return paths.extraction_events / f'folder-{source_digest}-{request_id}-llm-context-request.json'
