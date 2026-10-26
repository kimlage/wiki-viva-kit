"""Exact independently reviewed revalidation of intact local normative rules.

Documentary evidence never grants operational or account authority.
"""
from __future__ import annotations

import datetime as dt
import re

from wiki_core.document_records import digest
from wiki_core.freshness import parse_updated_date


def _complete_unit(graph, node, text):
    from wiki_core.causal_review import _document
    path = _document(graph, node)
    if (node in graph['documents'] or not isinstance(text, str) or not text
            or digest(text) != graph['nodes'][node].get('record_sha256')
            or text not in graph['documents'][path]):
        raise ValueError('normative revalidation requires a complete verified contiguous record')
    return path


def _local_contexts(graph, node):
    pending, seen = [node], {node}
    while pending:
        source = pending.pop()
        for edge in graph['edges']:
            if (edge['source'] == source and edge['type'] == 'source_ref'
                    and edge.get('basis') == 'document_record.v1'
                    and edge.get('field') == 'context_records' and edge['target'] not in seen):
                seen.add(edge['target']); pending.append(edge['target'])
    return seen - {node}


def _artifact(contract, inputs, aid, sha):
    declarations = [a for a in contract.get('artifacts', [])
                    if a.get('origin') == 'current' and a.get('id') == aid and 'path' in a]
    raw = inputs.get(('current', aid))
    if (not isinstance(aid, str) or not isinstance(sha, str) or not re.fullmatch(r'[a-f0-9]{64}', sha)
            or len(declarations) != 1 or raw is None or not raw.strip() or declarations[0]['sha256'] != sha
            or digest(raw.decode()) != sha):
        raise ValueError('normative revalidation requires sealed CURRENT evidence')
    return raw


def normative_revalidations(plan, contract, artifact_inputs, base, current):
    """Verify identity and evidence; independent review must establish meaning.

    A normative classification is an authored assertion, not something a hash
    can prove. External current facts cannot use this documentary disposition.
    Actual prerequisite freshness and operational admission remain independent.
    """
    from wiki_core.causal_authority import _unique_json
    items = plan.get('normative_revalidations', [])
    if not isinstance(items, list):
        raise ValueError('invalid normative revalidations')
    result = {}
    for item in items:
        fields = {'consumer', 'evidence_id', 'evidence_sha256', 'reason'}
        if (not isinstance(item, dict) or set(item) != fields
                or any(not isinstance(item[k], str) or not item[k].strip() for k in fields)
                or item['consumer'] in result):
            raise ValueError('invalid/duplicate normative revalidation')
        consumer = item['consumer']
        if consumer not in base['nodes'] or consumer not in current['nodes']:
            raise ValueError('revalidated normative unit must preexist')
        proof = _unique_json(_artifact(contract, artifact_inputs, item['evidence_id'], item['evidence_sha256']))
        expected = {'schema_version', 'assertion_kind', 'consumer', 'base_sha256', 'current_sha256',
                    'complete_text', 'current_document_sha256', 'checked_on', 'contexts', 'sources', 'revalidation_reason'}
        if (not isinstance(proof, dict) or set(proof) != expected
                or proof['schema_version'] != 'wiki_normative_revalidation.v1'
                or proof['assertion_kind'] != 'normative_rule' or proof['consumer'] != consumer
                or not isinstance(proof['revalidation_reason'], str) or not proof['revalidation_reason'].strip()):
            raise ValueError('invalid normative revalidation proof')
        path = _complete_unit(current, consumer, proof['complete_text'])
        if (_complete_unit(base, consumer, proof['complete_text']) != path
                or proof['base_sha256'] != base['nodes'][consumer]['record_sha256']
                or proof['current_sha256'] != current['nodes'][consumer]['record_sha256']
                or proof['current_document_sha256'] != digest(current['documents'][path])):
            raise ValueError('normative revalidation unit or current document changed')
        # Only explicit complete decision records are supported. Merely labeling
        # a page normative or fresh does not create this verified identity.
        record_id = current['nodes'][consumer].get('document_record_id')
        declarations = [r for d in contract['documents'] if d['path'] == path for r in d['records']
                        if r['id'] == record_id]
        if len(declarations) != 1 or declarations[0].get('epistemic_status') != 'decision':
            raise ValueError('normative revalidation requires an explicit decision record')
        for field in ('stale_after_days', 'stale_exempt', 'refresh_cadence_days'):
            if base['nodes'][consumer].get(field) != current['nodes'][consumer].get(field):
                raise ValueError('normative revalidation cannot alter cadence or exemptions')
        try:
            checked = dt.date.fromisoformat(proof['checked_on'])
        except (TypeError, ValueError):
            raise ValueError('invalid normative verification date') from None
        prior = parse_updated_date(base['nodes'][consumer].get('updated_at'))
        after = parse_updated_date(current['nodes'][consumer].get('updated_at'))
        if (checked.isoformat() != proof['checked_on'] or prior is None or after is None
                or checked != after or checked <= prior):
            raise ValueError('normative verification must match the actual renewed CURRENT date')
        required = _local_contexts(current, consumer)
        if required != _local_contexts(base, consumer) or not isinstance(proof['contexts'], list):
            raise ValueError('normative revalidation context scope changed')
        seen = set()
        for support in proof['contexts']:
            if (not isinstance(support, dict) or set(support) != {'node', 'sha256', 'complete_text'}
                    or not isinstance(support['node'], str) or support['node'] in seen
                    or support['node'] not in required
                    or support['sha256'] != current['nodes'][support['node']]['record_sha256']
                    or _complete_unit(current, support['node'], support['complete_text']) != path):
                raise ValueError('invalid complete normative context')
            seen.add(support['node'])
        if seen != required:
            raise ValueError('normative revalidation omits mandatory context')
        for node in required:
            rid = current['nodes'][node].get('document_record_id')
            records = [r for d in contract['documents'] if d['path'] == path for r in d['records'] if r['id'] == rid]
            if len(records) != 1 or records[0].get('epistemic_status') != 'decision':
                raise ValueError('normative context must be an explicit complete decision record')
        sources = proof['sources']
        if not isinstance(sources, list) or not sources:
            raise ValueError('normative revalidation requires checked source evidence')
        # A second artifact ID does not turn the reviewed object into an
        # independent authority. Semantic independence still requires review.
        subject_hashes = {digest(g['documents'][path]) for g in (base, current)}
        subject_hashes.update(current['nodes'][n]['record_sha256'] for n in {consumer, *required})
        proof_ids = {claim['evidence_id'] for claim in items
                     if isinstance(claim, dict) and isinstance(claim.get('evidence_id'), str)}
        seen_sources = set()
        for source in sources:
            fields = {'evidence_id', 'sha256', 'purpose'}
            if (not isinstance(source, dict) or set(source) != fields
                    or any(not isinstance(source[k], str) or not source[k].strip() for k in fields)
                    or source['evidence_id'] in seen_sources
                    or source['evidence_id'] in proof_ids | {plan['review_evidence']}
                    or source['sha256'] in subject_hashes):
                raise ValueError('invalid/circular normative source evidence')
            _artifact(contract, artifact_inputs, source['evidence_id'], source['sha256'])
            seen_sources.add(source['evidence_id'])
        result[consumer] = dict(checked_on=checked.isoformat(), evidence_id=item['evidence_id'],
                                evidence_sha256=item['evidence_sha256'])
    return result
