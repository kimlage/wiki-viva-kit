"""Construct bounded, revision-bound context packets from authorized paths."""
from __future__ import annotations
import hashlib
import json
import datetime as dt
from pathlib import Path
from .context_policy import PolicyError, capability_status, safe_path, within, valid_adapter_report
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
    if section is not None and field is not None: raise PolicyError('section and field mutually exclusive')
    if any(x is not None and (not isinstance(x, str) or not x) for x in (section, field)):
        raise PolicyError('invalid proposal selector')
    return {'source': source, 'destination': destination, 'selector': selector, 'section': section, 'field': field,
            'purpose': purpose, 'classification': classification, 'expiry': expiry,
            'status': 'pending', 'grants_access': False}


def build_packet(root, policy, context_id, content_revision, evidence, budget, *, adapter_report=None,
                 required_capabilities=(), query_fingerprint=None, omissions=(), task_id=None, goal=None, output=None, integrator=None):
    if not all(isinstance(x, str) and x.strip() for x in (task_id, goal, output, integrator)): raise PolicyError('task identity, goal, output and integrator required')
    if not getattr(policy, '_binding', None) or Path(policy._binding[0]) != Path(root).resolve(): raise PolicyError('unbound or mismatched policy')
    policy = policy.fresh()
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 0:
        raise PolicyError('invalid byte budget')
    if query_fingerprint is not None: raise PolicyError('dynamic query selection not supported')
    if not isinstance(omissions, (list, tuple)) or any(not isinstance(x, str) or not x for x in omissions): raise PolicyError('invalid omissions')
    lineage = policy.lineage(context_id)
    if adapter_report is not None and not valid_adapter_report(adapter_report): raise PolicyError('invalid adapter report')
    if not isinstance(required_capabilities, (list, tuple)):
        raise PolicyError('invalid required capabilities')
    for effect in required_capabilities:
        if not isinstance(effect, dict) or set(effect) != {'capability', 'target'} or not all(isinstance(x, str) and x.strip() for x in effect.values()):
            raise PolicyError('capability and exact target required')
        if capability_status(policy, context_id, effect['capability'], adapter_report, target=effect['target']) != 'available':
            raise PolicyError('required capability lacks verified adapter evidence: ' + effect['capability'])
    reader = RepositoryReader(Path(root), content_revision)
    selected = []
    seen = set()
    # Rules are read from the approved policy revision, never historical content.
    policy_reader = RepositoryReader(Path(root), policy.policy_revision)
    def add(reader_, ref, reason, kind, section=None, field=None, producer=None, use=None, classification=None):
        ref = safe_path(ref)
        denied = any(within(ref, scope) for scope in policy.effective[context_id]['deny']['read'])
        if denied or (kind != 'mandatory' and not policy.permits(context_id, 'read', ref)): raise PolicyError('read denied: ' + ref)
        item = reader_.read(ref, section=section, field=field)
        text = item['text']
        if not isinstance(text, str): raise PolicyError('reader returned non-text')
        data = text.encode('utf-8')
        digest = hashlib.sha256(data).hexdigest()
        if item['content_digest'] != digest: raise PolicyError('reader digest mismatch')
        selected.append({'kind': kind, 'ref': ref, 'section': section, 'field': field,
                         'text': text, 'byte_length': len(data), 'sha256': digest,
                         'revision': item['revision'], 'document_sha256': item['content_sha256'],
                         'origin': item['origin'], 'reason': reason, 'producer': producer, 'use': use, 'classification': classification})
    for c in lineage:
        for key in ('instructions', 'skills', 'templates'):
            for ref in c[key]:
                if ref not in seen:
                    add(policy_reader, ref, f"mandatory {key} from {c['id']}", 'mandatory', producer=c['id'])
                    seen.add(ref)
    mandatory_bytes = sum(x['byte_length'] for x in selected)
    if mandatory_bytes > budget: raise PolicyError('mandatory content exceeds byte budget')
    if not isinstance(evidence, list): raise PolicyError('evidence must be a list')
    for e in evidence:
        allowed = {'ref','producer','reason','use','classification','section','field'}
        if not isinstance(e, dict) or set(e) - allowed or not all(isinstance(e.get(k), str) and e[k] for k in ('ref','producer','reason','use','classification')):
            raise PolicyError('invalid evidence')
        ref = safe_path(e['ref'])
        if any(k in e and (not isinstance(e[k], str) or not e[k]) for k in ('section','field')) or ('section' in e and 'field' in e): raise PolicyError('invalid evidence selector')
        status = policy.connection(e['producer'], context_id, ref, e['use'], e['classification'], section=e.get('section'), field=e.get('field'))
        if status != 'approved': raise PolicyError('connection ' + status)
        add(reader, ref, e['reason'], 'evidence', e.get('section'), e.get('field'), e['producer'], e['use'], e['classification'])
    total = sum(x['byte_length'] for x in selected)
    if total > budget: raise PolicyError('selected content exceeds byte budget')
    policy.fresh()  # Fail if approval moved during composition.
    packet = {'schema_version': 'wiki.task-context/v1', 'task_id': task_id, 'goal': goal, 'output': output, 'integrator': integrator, 'context_id': context_id,
            'content_revision': reader.revision, 'policy_revision': policy.policy_revision,
            'inputs': selected, 'declared_read_set': [{'ref': x['ref'], 'section': x['section'], 'field': x['field'], 'revision': x['revision']} for x in selected],
            'query_fingerprint': None, 'coverage': {'mode': 'explicit_read_set', 'complete': False, 'missing': list(omissions)},
            'byte_budget': budget, 'bytes_used': total,
            'capability_evidence': adapter_report, 'required_capabilities': list(required_capabilities), 'enforcement_claim': 'none; adapter report is supplied by the caller'}
    packet['packet_digest'] = hashlib.sha256(json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return packet


def validate_result(result, packet):
    """Validate a reported result and bind it to the actual canonical packet."""
    from jsonschema import ValidationError, validate
    schema_path = Path(__file__).resolve().parents[1] / 'docs/references/schemas/wiki-task-result-v1.schema.json'
    try:
        validate(result, json.loads(schema_path.read_text(encoding='utf-8')))
    except (ValidationError, OSError, ValueError) as exc:
        raise PolicyError('invalid task result') from exc
    if not isinstance(packet, dict) or not isinstance(packet.get('packet_digest'), str): raise PolicyError('invalid packet')
    payload = {k: v for k, v in packet.items() if k != 'packet_digest'}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if digest != packet['packet_digest'] or any(result[k] != packet.get(k) for k in ('task_id', 'context_id', 'packet_digest')):
        raise PolicyError('result is not bound to this packet')
    declared = {json.dumps(item, sort_keys=True) for item in packet['declared_read_set']}
    observed = {json.dumps(item, sort_keys=True) for item in result['read_coverage']['observed_refs']}
    if not observed.issubset(declared): raise PolicyError('result reports undeclared reads')
    return True
