"""Narrow opt-in v2 folder packet for a limited, separately reviewed preflight."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wiki_core.context_policy import ContextPolicy, PolicyError, _git, revision, safe_path, within
from wiki_core.repo_read import contains_access_secrets
from wiki_core.folder_policy_v2 import FORMAT, _at_revision
from wiki_core.folder_declarations_v2 import authorized_index, authorized_instruction_chain, preauthorize_index
from wiki_core.repository_reader import RepositoryReader
from wiki_core.folder_auxiliary_v2 import qualify_auxiliary


def build_folder_packet_v2(root, policy, folder, max_bytes, *, content_revision, index_path, task_id, goal, output, integrator, evidence=(), index_section=None, start_folder=None):
    """Compose approved instruction chain and selected index, under v2 ceilings.

    The v2 format has no v1 query or result receipts. Its contents do not prove
    native instruction loading, isolation, execution or permission enforcement.
    """
    if getattr(policy, 'format_version', None) != FORMAT:
        raise PolicyError('explicit v2 policy required; v1 receipts require migration')
    if not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise PolicyError('unbound or mismatched v2 policy')
    policy = policy.fresh()
    if folder not in policy.folder_ids:
        raise PolicyError('folder is not a context with an instruction and index')
    if not all(isinstance(v, str) and v.strip() for v in (task_id, goal, output, integrator)):
        raise PolicyError('task identity, goal, output and integrator required')
    if type(max_bytes) is not int or max_bytes < 1:
        raise PolicyError('invalid byte budget')
    if not isinstance(evidence, (list, tuple)) or contains_access_secrets(evidence):
        raise PolicyError('invalid or secret evidence request')
    preauthorize_index(policy, folder, index_path)
    context = policy.folder_ids[folder]
    if start_folder is not None:
        # The requested output and its limits are checked before opening any
        # auxiliary instruction. This is still not an execution sandbox.
        target = safe_path(output)
        if (ContextPolicy.owner_of(policy, target) != context
                or not policy.permits(context, 'read', target)
                or not policy.permits(context, 'write', target)):
            raise PolicyError('auxiliary output is not authorized')
    reader = RepositoryReader(root, policy.policy_revision)
    content_sha = revision(root, content_revision)
    _git(root, 'merge-base', '--is-ancestor', content_sha, policy.policy_revision)
    historical = None
    evidence_reader = None
    if index_section is not None and (not isinstance(index_section, str) or not index_section.strip()):
        raise PolicyError('invalid selected index section')
    if start_folder is not None:
        policy = qualify_auxiliary(policy, reader, folder, start_folder, max_bytes=max_bytes)
        preauthorize_index(policy, folder, index_path)
    chain = authorized_instruction_chain(policy, reader, folder, max_bytes=max_bytes, start_folder=start_folder)
    index = authorized_index(policy, folder, index_path, chain)
    required_paths = [row['path'] for row in chain]
    for row in chain:
        required_paths.extend(row['declarations']['mandatory'])
    required_paths.append(index)
    if sum(reader.blob_size(path) for path in dict.fromkeys(required_paths)) > max_bytes:
        raise PolicyError('mandatory content exceeds byte budget')
    rows = []
    seen = set()
    for entry in chain:
        path, item = entry['path'], entry['item']
        rows.append({'kind': 'instruction', 'path': path, 'revision': reader.revision,
                     'sha256': item['content_sha256'], 'text': item['text']})
        seen.add(path)
        for ref in entry['declarations']['mandatory']:
            if ref in seen:
                continue
            item = reader.read(ref)
            if not item['text'].strip() or contains_access_secrets(item['text']):
                raise PolicyError('invalid or secret mandatory reference')
            rows.append({'kind': 'mandatory', 'path': ref, 'revision': reader.revision,
                         'sha256': item['content_sha256'], 'text': item['text'],
                         'producer_context': policy.owner_of(entry['path'])})
            seen.add(ref)
    item = reader.read(index, section=index_section)
    if not item['text'].strip() or contains_access_secrets(item['text']):
        raise PolicyError('invalid or secret selected index')
    rows.append({'kind': 'index', 'path': index, 'revision': reader.revision,
                 'sha256': item['content_digest'], 'document_sha256': item['content_sha256'],
                 'section': index_section, 'text': item['text']})
    for spec in evidence:
        if not isinstance(spec, dict) or set(spec) - {'path', 'producer_folder', 'reason', 'use', 'classification', 'section', 'field'}:
            raise PolicyError('invalid v2 evidence selector')
        if not all(isinstance(spec.get(k), str) and spec[k].strip() for k in ('path', 'producer_folder', 'reason', 'use', 'classification')):
            raise PolicyError('invalid v2 evidence selector')
        if 'section' in spec and 'field' in spec:
            raise PolicyError('section and field are mutually exclusive')
        for key in ('section', 'field'):
            if key in spec and (not isinstance(spec[key], str) or not spec[key].strip()):
                raise PolicyError('invalid v2 evidence selector')
        path = safe_path(spec['path'])
        producer = policy.folder_ids.get(spec['producer_folder'])
        if producer is None:
            raise PolicyError('v2 evidence producer unavailable')
        if policy.connection(producer, context, path, spec['use'], spec['classification'],
                             section=spec.get('section'), field=spec.get('field')) != 'approved':
            raise PolicyError('v2 evidence connection unavailable')
        # Current authority is checked before opening historical source content.
        if historical is None:
            historical = policy if content_sha == policy.policy_revision else _at_revision(Path(root), content_sha, policy.controls_path)
            evidence_reader = reader if content_sha == policy.policy_revision else RepositoryReader(root, content_sha)
            if start_folder is not None and historical is not policy:
                historical = qualify_auxiliary(historical, evidence_reader, folder, start_folder, max_bytes=max_bytes)
        if (historical.folder_ids.get(folder) != context
                or historical.folder_ids.get(spec['producer_folder']) != producer
                or historical.connection(producer, context, path, spec['use'], spec['classification'],
                                         section=spec.get('section'), field=spec.get('field')) != 'approved'):
            raise PolicyError('historical v2 evidence authority unavailable')
        item = evidence_reader.read(path, section=spec.get('section'), field=spec.get('field'))
        if contains_access_secrets(item['text']):
            raise PolicyError('secret detected in v2 evidence')
        rows.append({'kind': 'evidence', 'path': path, 'revision': evidence_reader.revision,
                     'sha256': item['content_digest'], 'document_sha256': item['content_sha256'],
                     'text': item['text'], 'producer_context': producer, 'reason': spec['reason'],
                     'use': spec['use'], 'classification': spec['classification'],
                     'section': spec.get('section'), 'field': spec.get('field')})
    packet = {'schema_version': 'wiki.folder-task-context/v2', 'policy_format': FORMAT,
              'task_id': task_id, 'goal': goal, 'output': output, 'integrator': integrator,
              'context_id': context, 'context_folder': folder, 'policy_revision': policy.policy_revision,
              'index_path': index, 'index_section': index_section,
              'content_revision': content_sha,
              'inputs': rows, 'max_bytes': max_bytes, 'bytes_used': 0,
              'limitations': ['No native loading, ACL or execution is proved',
                              'Limited preflight only; no dynamic queries, v1 receipt migration, approval or merge']}
    if start_folder is not None:
        packet['start_folder'] = safe_path(start_folder)
    if contains_access_secrets(packet):
        raise PolicyError('secret detected in packet')
    packet['packet_digest'] = '0' * 64
    while True:
        length = len(json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
        if packet['bytes_used'] == length:
            break
        packet['bytes_used'] = length
    if packet['bytes_used'] > max_bytes:
        raise PolicyError('complete v2 packet exceeds byte budget')
    payload = {key: value for key, value in packet.items() if key != 'packet_digest'}
    packet['packet_digest'] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    policy.fresh()
    return packet
