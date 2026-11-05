"""Compare selected protected interpretation evidence, never confer authority."""
from __future__ import annotations

import copy
import hashlib
import json
import re

from wiki_core.context_policy import within


def _packet_digest(packet):
    if not isinstance(packet, dict) or packet.get('authority_format') != 'folder':
        raise ValueError('historical packet unavailable')
    encoded = json.dumps(packet, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    if type(packet.get('bytes_used')) is not int or packet['bytes_used'] != len(encoded):
        raise ValueError('historical packet unavailable')
    value = {key: item for key, item in packet.items() if key != 'packet_digest'}
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if digest != packet.get('packet_digest'):
        raise ValueError('historical packet unavailable')


def comparable_request(request, *, source_may_differ=False):
    """Retain selected context; source differences require a separate chunk proof."""
    if not isinstance(request, dict) or request.get('context_binding_version') != 1:
        raise ValueError('historical request unavailable')
    out = copy.deepcopy(request)
    packet = out.get('block_context_package')
    _packet_digest(packet)
    auth = out.get('source_authorization')
    if (not isinstance(auth, dict) or auth.get('policy_revision') != packet.get('policy_revision')
            or packet.get('policy_revision') != packet.get('content_revision')):
        raise ValueError('historical request unavailable')
    revision = packet['policy_revision']
    auth.pop('policy_revision')
    for key in ('policy_revision', 'content_revision', 'packet_digest', 'bytes_used'):
        packet.pop(key, None)
    for key in ('inputs', 'declared_read_set'):
        rows = packet.get(key)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('historical request unavailable')
        for row in rows:
            if row.get('revision') != revision:
                raise ValueError('historical input revision unavailable')
            if key == 'inputs':
                origin = row.get('origin')
                if (not isinstance(origin, dict) or origin.get('kind') != 'git'
                        or origin.get('revision') != revision or origin.get('path') != row.get('ref')):
                    raise ValueError('historical input origin unavailable')
                text = row.get('text')
                if (not isinstance(text, str) or len(text.encode('utf-8')) != row.get('byte_length')
                        or hashlib.sha256(text.encode('utf-8')).hexdigest() != row.get('sha256')):
                    raise ValueError('historical input body unavailable')
                origin.pop('revision')
            row.pop('revision', None)
    for key in ('protected_request_id', 'byte_accounting', 'pending_llm_calls', 'cached_calls'):
        out.pop(key, None)
    rows = out.get('chunks')
    if not isinstance(rows, list) or not rows:
        raise ValueError('historical request unavailable')
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('historical request unavailable')
        for key in ('context_sha256', 'cache_key', 'result_exists', 'result_source_id', 'result_chunk_id'):
            row.pop(key, None)
    if source_may_differ:
        source_id, source_hash = out.get('source_id'), out.get('source_hash_sha256')
        if (not isinstance(source_id, str) or not source_id
                or not isinstance(source_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', source_hash)
                or packet.get('task_id') != source_id):
            raise ValueError('historical source identity unavailable')
        packet.pop('task_id')
        out.pop('source_id')
        out.pop('source_hash_sha256')
        out.pop('chunks')
    return out


def selected_grants(policy, request):
    """Describe matching read scopes and bilateral grants for selected bodies."""
    packet, auth = request['block_context_package'], request['source_authorization']
    context, actor = auth['context_id'], auth['artifact_context']
    readers = {context, actor}
    selections = [(auth['producer'], auth['ref'], 'interpretation', 'source', None, None)]
    for row in packet['inputs']:
        selections.append((row['producer'], row['ref'], row.get('use') or 'interpretation',
                           row.get('classification') or 'context', row.get('section'), row.get('field')))
    evidence = []
    for producer, ref, use, classification, section, field in selections:
        for reader in sorted(readers):
            if (policy.owner_of(ref) != producer or policy._connection(producer, reader, ref, use,
                    classification, section=section, field=field, qualified=False) != 'approved'):
                raise ValueError('selected grant unavailable')
            scopes = {}
            for party in {producer, reader}:
                scopes[party] = sorted(scope for scope in policy.effective[party]['read'] if within(ref, scope))
            shared = []
            if producer != reader:
                for grant in policy.contexts[producer]['exports']:
                    if (grant in policy.contexts[reader]['imports'] and grant['from_context'] == producer
                            and grant['to_context'] == reader and grant['selector'] == ref
                            and grant['use'] == use and grant['classification'] == classification
                            and grant.get('section') == section and grant.get('field') == field):
                        shared.append(grant)
                shared.sort(key=lambda value: json.dumps(value, sort_keys=True))
            evidence.append({'producer': producer, 'reader': reader, 'ref': ref, 'use': use,
                             'classification': classification, 'section': section, 'field': field,
                             'read_scopes': scopes, 'bilateral': shared})
    return evidence
