"""Finite owner-only queries anchored in an existing collection contract.

Receipts separate revision provenance, membership and selected-byte equivalence.
They are not factual verification, durable state, or a filesystem sandbox.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import PurePosixPath
import re
import subprocess
import yaml
from .context_policy import PolicyError, UniqueLoader, safe_path, within, historical_policy
from .detectors import scan_text
from .frontmatter import FRONTMATTER_RE
from .repository_reader import canonical_path


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def reject_secrets(value):
    if any(f.category == 'secret' for f in scan_text(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))):
        raise PolicyError('secret detected in query input')


def normalize_query(entry):
    required = {'target', 'query', 'reason', 'use', 'classification'}
    if not isinstance(entry, dict) or set(entry) != required:
        raise PolicyError('invalid anchored query')
    if any(not isinstance(entry[k], str) or not entry[k].strip() for k in required - {'query'}):
        raise PolicyError('invalid query metadata')
    reject_secrets(entry)
    target = safe_path(entry['target'])
    q = entry['query']
    keys = {'scope', 'filters', 'max_enumerated', 'max_matches', 'max_scan_bytes'}
    if not isinstance(q, dict) or not keys <= set(q) or set(q) - (keys | {'section', 'field'}):
        raise PolicyError('invalid query descriptor')
    scope = safe_path(q['scope'], allow_root=True)
    if scope != '.': canonical_path(scope)
    canonical_path(target)
    parent = str(PurePosixPath(target).parent)
    if not target.endswith('.md') or not within(scope, parent):
        raise PolicyError('query scope must be within its collection anchor directory')
    filters = q['filters']
    if not isinstance(filters, dict) or not 1 <= len(filters) <= 8:
        raise PolicyError('bounded query filters required')
    normalized = {}
    def scalar(value):
        return type(value) in (str, bool, int) and (not isinstance(value, str) or 0 < len(value) <= 256)
    for key, value in filters.items():
        if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', key):
            raise PolicyError('invalid query field')
        values = value if isinstance(value, list) else [value]
        if not 1 <= len(values) <= 16 or any(not scalar(x) for x in values):
            raise PolicyError('invalid query value')
        # Lists mean OR of exact typed scalar values, not substring or tags.
        if len({digest(x) for x in values}) != len(values): raise PolicyError('duplicate query value')
        normalized[key] = sorted(values, key=lambda x: json.dumps(x, sort_keys=True)) if isinstance(value, list) else value
    limits = {'max_enumerated': 1000, 'max_matches': 128, 'max_scan_bytes': 2_000_000}
    for key, ceiling in limits.items():
        if type(q[key]) is not int or not 1 <= q[key] <= ceiling: raise PolicyError('invalid query limit')
    if 'section' in q and 'field' in q: raise PolicyError('ambiguous query selector')
    for key in ('section', 'field'):
        if key in q and (not isinstance(q[key], str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,127}', q[key])):
            raise PolicyError('invalid query selector')
    return {**entry, 'target': target, 'query': {**q, 'scope': scope, 'filters': normalized}}


def query_identity(entry):
    q = entry['query']
    return digest({'target': entry['target'], 'excluded_anchor': entry['target'], 'query': {k: v for k, v in q.items()
        if k not in ('max_enumerated', 'max_matches', 'max_scan_bytes')},
        'use': entry['use'], 'classification': entry['classification']})


def authority_digest(policy, context_id, entry):
    """Hash only the relevant path authority; no protected paths are delivered."""
    target=entry['target']; scope=entry['query']['scope']
    if context_id not in policy.contexts: raise PolicyError('query authority unavailable')
    c=policy.contexts[context_id]; effective=policy.effective[context_id]
    def clipped(scopes):
        values=set()
        for path in scopes:
            if within(scope,path): values.add(scope)
            elif within(path,scope): values.add(path)
        return sorted(p for p in values if not any(p!=other and within(p,other) for other in values))
    excluded=clipped([x['root'] for key,x in policy.contexts.items() if key!=context_id and within(x['root'],scope)])
    return digest({'context_id':context_id,'owner':c['owner'],'root':c['root'],
        'scope_owner':policy.owner_of(scope) if scope!='.' else next(x['id'] for x in policy.contexts.values() if x['root']=='.'),
        'anchor_owner':policy.owner_of(target),'anchor_read':policy.permits(context_id,'read',target),
        'read':clipped(effective['read']),'deny':clipped(effective['deny']['read']), 'excluded_context_roots':excluded})


def reproduce_query(policy, context_id, reader, entry, *, policy_revision, expected_authority, read_budget=None, _candidate_refs=None):
    """Check historical authority BEFORE reading, then use only current permission."""
    entry=normalize_query(entry)
    if not isinstance(expected_authority,str) or not re.fullmatch(r'[0-9a-f]{64}',expected_authority):
        raise PolicyError('query authority changed or unavailable; requalification required')
    # Content must already have existed when its claimed policy was approved.
    if (not getattr(policy, '_binding', None) or subprocess.run(
            ['git', '-C', str(policy._binding[0]), 'merge-base', '--is-ancestor', reader.revision, policy_revision],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode):
        raise PolicyError('query content is not an ancestor of its policy')
    old=historical_policy(policy,policy_revision)
    if (authority_digest(old,context_id,entry)!=expected_authority
            or authority_digest(policy,context_id,entry)!=expected_authority):
        raise PolicyError('query authority changed or unavailable; requalification required')
    receipt,anchor,members=select_query(policy,context_id,reader,entry,read_budget=read_budget,_candidate_refs=_candidate_refs)
    receipt['policy_revision']=policy_revision
    return receipt,anchor,members


def _metadata(item):
    """Strict query parsing only; legacy explicit reader parsing is unchanged."""
    match = FRONTMATTER_RE.match(item['text'])
    if match is None:
        if item['text'].startswith('---'): raise PolicyError('malformed query frontmatter')
        return {}
    try:
        if any(isinstance(token, yaml.AliasToken) for token in yaml.scan(match.group(1))):
            raise PolicyError('YAML aliases unsupported in query metadata')
        values = yaml.load(match.group(1), Loader=UniqueLoader)
    except (yaml.YAMLError, ValueError, TypeError) as exc: raise PolicyError('ambiguous query frontmatter') from exc
    if not isinstance(values, dict): raise PolicyError('invalid query frontmatter')
    reject_secrets(values)
    return values


def select_query(policy, context_id, reader, entry, *, read_budget=None, _candidate_refs=None):
    """Apply current owner/read authorization before opening candidate blobs."""
    entry = normalize_query(entry)
    target = entry['target']; q = entry['query']; scope = q['scope']
    if context_id not in policy.contexts: raise PolicyError('unknown query context')
    root = policy.contexts[context_id]['root']
    if (not within(scope, root) or (scope != '.' and policy.owner_of(scope) != context_id)
            or policy.owner_of(target) != context_id or not policy.permits(context_id, 'read', target)
            or not any(within(scope, x) for x in policy.effective[context_id]['read'])
            or any(within(scope, x) for x in policy.effective[context_id]['deny']['read'])):
        raise PolicyError('query scope not authorized')
    scanned = 0
    def admit(path):
        nonlocal scanned
        size = reader.blob_size(path)
        scanned += size
        if scanned > q['max_scan_bytes']: raise PolicyError('query scan byte limit exceeded')
        if read_budget is not None:
            if size > read_budget[0]: raise PolicyError('query operation byte limit exceeded')
            read_budget[0] -= size
    admit(target)
    anchor = reader.read(target)
    metadata = _metadata(anchor)
    if metadata.get('page_type') not in ('context_hub', 'ontology_index', 'source_catalog', 'root_entity') or not isinstance(metadata.get('page_id'), str) or not metadata['page_id'].strip() or any(ord(c)<32 for c in metadata['page_id']):
        raise PolicyError('query anchor must identify an existing collection contract')
    reject_secrets(anchor['text'])
    # Ownership and denies precede every content/metadata read and count.
    def authorized(path):
        return path != target and within(path, scope) and policy.owner_of(path) == context_id and policy.permits(context_id, 'read', path)
    if any(path.endswith(b'.md') and authorized(path.decode('utf-8', errors='surrogateescape')) for path in reader.invalid_paths):
        raise PolicyError('query path is not UTF-8')
    if any((path.endswith('.md') and authorized(path)) or (within(scope,path) and policy.owner_of(path)==context_id and policy.permits(context_id,'read',path)) for path in reader.unsupported_paths):
        raise PolicyError('unsupported query path')
    allowed = [p for p in reader.paths if p.endswith('.md') and authorized(p)]
    if len(allowed) > q['max_enumerated']: raise PolicyError('query enumeration limit exceeded')
    members = []; inputs = []; identities = {metadata['page_id']}
    for path in allowed:
        reject_secrets(path)
        admit(path)
        item = reader.read(path); fm = _metadata(item)
        page_id = fm.get('page_id')
        if _candidate_refs is not None: _candidate_refs.append((path, page_id is not None))
        if page_id is None: continue  # Non-page Markdown is not a collection member.
        if not isinstance(page_id, str) or not page_id.strip() or any(ord(c)<32 for c in page_id) or page_id in identities:
            raise PolicyError('query page identity missing or ambiguous')
        identities.add(page_id)
        def matches(key, value):
            options = value if isinstance(value, list) else [value]
            actual = fm.get(key)
            return any(type(actual) is type(v) and actual == v for v in options)
        if not all(matches(k, v) for k, v in q['filters'].items()): continue
        if len(members) >= q['max_matches']: raise PolicyError('query match limit exceeded')
        selected = reader.read(path, section=q.get('section'), field=q.get('field'))
        reject_secrets(selected['text'])
        members.append({'ref': path, 'page_id': page_id})
        inputs.append(selected)
    identity = query_identity(entry)
    receipt = {'request': entry, 'query_id': identity, 'revision': reader.revision,
        'policy_revision':policy.policy_revision,'authority_digest':authority_digest(policy,context_id,entry),'excluded_anchor':target,
        'members': members, 'members_digest': digest({'query_id': identity, 'members': members}),
        'selected_digest': digest({'query_id': identity, 'anchor': anchor['content_digest'],
            'selected': [{'ref': item['path'], 'sha256': item['content_digest']} for item in inputs]}),
        'coverage': 'complete_only_within_current_authorized_owner_scope', 'enumerated': len(allowed)}
    return receipt, anchor, inputs


def packet_queries(packet):
    return [row['request'] for row in packet.get('query_selections', [])]


def same_selection(before, after):
    return all(before[k] == after[k] for k in ('query_id', 'members_digest', 'selected_digest', 'authority_digest'))


def requirement_query(requirement):
    return {'target': requirement['target'], 'query': requirement['query'], 'reason': 'canonical collection requirement',
        'use': requirement.get('use', 'interpret'), 'classification': requirement.get('classification', 'internal')}


def revalidate_packet_queries(policy, packet, historical, current, *, read_budget=None):
    """Reproduce receipts under current policy, then compare semantic selection."""
    rows = packet.get('query_selections', [])
    if not rows:
        if packet.get('query_fingerprint') is not None or any('query_id' in x for x in packet['inputs']):
            raise PolicyError('invalid query packet binding')
        return []
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8 or packet.get('query_fingerprint') != digest(rows):
        raise PolicyError('invalid query packet binding')
    if len({r['query_id'] for r in rows}) != len(rows): raise PolicyError('duplicate query')
    specs = []; refreshed = []
    if read_budget is None: read_budget = [32_000_000]
    for row in rows:
        if row.get('policy_revision')!=packet['policy_revision']: raise PolicyError('query policy revision differs from packet')
        prior, anchor, members = reproduce_query(policy, packet['context_id'], historical, row['request'], policy_revision=row.get('policy_revision'), expected_authority=row.get('authority_digest'), read_budget=read_budget)
        if prior != row: raise PolicyError('query receipt cannot be reproduced')
        now, _, _ = select_query(policy, packet['context_id'], current, row['request'], read_budget=read_budget)
        if not same_selection(row, now): raise PolicyError('query selection changed since task')
        refreshed.append(now)
        entry = row['request']; q = entry['query']
        for item in [anchor, *members]:
            specs.append({'query_id': row['query_id'], 'ref': item['path'],
                'section': q.get('section') if item is not anchor else None,
                'field': q.get('field') if item is not anchor else None,
                'producer': packet['context_id'], 'reason': entry['reason'], 'use': entry['use'],
                'classification': entry['classification'], 'kind': 'evidence'})
    keys = ('query_id','ref','section','field','producer','reason','use','classification','kind')
    actual = [{k:item.get(k) for k in keys} for item in packet['inputs'] if 'query_id' in item]
    if actual != specs: raise PolicyError('query inputs differ from receipt')
    return refreshed


def strict_json_loads(text):
    """Ambiguous JSON never supplies a query, receipt, or protected task."""
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result: raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def constant(_): raise ValueError('non-finite JSON value')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
