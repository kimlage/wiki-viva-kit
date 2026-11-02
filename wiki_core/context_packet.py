"""Construct bounded, revision-bound context packets from authorized paths."""
from __future__ import annotations
import hashlib
import datetime as dt
from pathlib import Path
from .context_policy import PolicyError, capability_status, safe_path
from .repository_reader import RepositoryReader


def blocker(action, target, reason, owner, required_action, resume_condition, status='pending', interface=None):
    if status not in ('pending', 'denied', 'uncertain'):
        raise PolicyError('invalid blocker status')
    if not all(isinstance(x, str) and x for x in (action, target, reason, owner, required_action, resume_condition)):
        raise PolicyError('incomplete blocker')
    return {'action': action, 'target': target, 'reason': reason, 'owner': owner,
            'required_action': required_action, 'interface': interface,
            'resume_condition': resume_condition, 'status': status}


def connection_proposal(source, destination, selector, purpose, classification, expiry, *, section=None, field=None):
    """A proposal contains selectors, never content; it grants no access."""
    safe_path(selector)
    if not all(isinstance(x, str) and x for x in (source, destination, purpose, classification, expiry)):
        raise PolicyError('incomplete connection proposal')
    try: dt.date.fromisoformat(expiry)
    except ValueError as exc: raise PolicyError('invalid proposal expiry') from exc
    if any(x is not None and (not isinstance(x, str) or not x) for x in (section, field)):
        raise PolicyError('invalid proposal selector')
    return {'source': source, 'destination': destination, 'selector': selector, 'section': section, 'field': field,
            'purpose': purpose, 'classification': classification, 'expiry': expiry,
            'status': 'pending', 'grants_access': False}


def build_packet(root, policy, context_id, content_revision, evidence, budget, *, adapter_report=None,
                 required_capabilities=(), query_fingerprint=None, omissions=()):
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 0:
        raise PolicyError('invalid byte budget')
    if query_fingerprint is not None and (not isinstance(query_fingerprint, str) or not query_fingerprint): raise PolicyError('invalid query fingerprint')
    if not isinstance(omissions, (list, tuple)) or any(not isinstance(x, str) or not x for x in omissions): raise PolicyError('invalid omissions')
    lineage = policy.lineage(context_id)
    for cap in required_capabilities:
        if capability_status(policy, context_id, cap, adapter_report) != 'available':
            raise PolicyError('required capability lacks verified adapter evidence: ' + cap)
    reader = RepositoryReader(Path(root), content_revision)
    selected = []
    seen = set()
    # Rules are read from the approved policy revision, never historical content.
    policy_reader = RepositoryReader(Path(root), policy.policy_revision)
    def add(reader_, ref, reason, kind, section=None, field=None):
        ref = safe_path(ref)
        if not policy.permits(context_id, 'read', ref): raise PolicyError('read denied: ' + ref)
        item = reader_.read(ref, section=section, field=field)
        text = item['text']
        if not isinstance(text, str): raise PolicyError('reader returned non-text')
        data = text.encode('utf-8')
        digest = hashlib.sha256(data).hexdigest()
        if item['content_digest'] != digest: raise PolicyError('reader digest mismatch')
        selected.append({'kind': kind, 'ref': ref, 'section': section, 'field': field,
                         'text': text, 'byte_length': len(data), 'sha256': digest,
                         'revision': item['revision'], 'document_sha256': item['content_sha256'],
                         'origin': item['origin'], 'reason': reason})
    for c in lineage:
        for key in ('instructions', 'skills', 'templates'):
            for ref in c[key]:
                if ref not in seen:
                    add(policy_reader, ref, f"mandatory {key} from {c['id']}", 'mandatory')
                    seen.add(ref)
    mandatory_bytes = sum(x['byte_length'] for x in selected)
    if mandatory_bytes > budget: raise PolicyError('mandatory content exceeds byte budget')
    if not isinstance(evidence, list): raise PolicyError('evidence must be a list')
    for e in evidence:
        allowed = {'ref','producer','reason','use','classification','section','field'}
        if not isinstance(e, dict) or set(e) - allowed or not all(isinstance(e.get(k), str) and e[k] for k in ('ref','producer','reason','use','classification')):
            raise PolicyError('invalid evidence')
        ref = safe_path(e['ref'])
        status = policy.connection(e['producer'], context_id, ref, e['use'], e['classification'], section=e.get('section'), field=e.get('field'))
        if status != 'approved': raise PolicyError('connection ' + status)
        add(reader, ref, e['reason'], 'evidence', e.get('section'), e.get('field'))
    total = sum(x['byte_length'] for x in selected)
    if total > budget: raise PolicyError('selected content exceeds byte budget')
    return {'schema_version': 'wiki.task-context/v1', 'context_id': context_id,
            'content_revision': reader.revision, 'policy_revision': policy.policy_revision,
            'inputs': selected, 'declared_read_set': [{'ref': x['ref'], 'section': x['section'], 'field': x['field'], 'revision': x['revision']} for x in selected],
            'query_fingerprint': query_fingerprint, 'omissions': list(omissions),
            'byte_budget': budget, 'bytes_used': total,
            'capability_evidence': adapter_report, 'enforcement_claim': 'none; adapter report is supplied by the caller'}
