"""Reviewed historical edits satisfy editing, never current factual use.

The reviewer establishes historical meaning and authorized scope. These checks
bind that judgment to complete records and retained sources; hashes alone do
not establish truth, authorization, or the absence of a semantic change.
"""
from __future__ import annotations

import datetime as dt
from difflib import SequenceMatcher

from wiki_core.document_records import digest, structured_digest


def qualifications(plan, contract, inputs, base, current, seeds, *, complete_component_deltas=frozenset()):
    from wiki_core.causal_authority import _unique_json
    from wiki_core.causal_revalidation import _artifact, _complete_unit, _local_contexts
    from wiki_core.freshness import parse_updated_date
    from wiki_core.document_view_selectors import complete_h2_record

    items = plan.get('documentary_edits', [])
    if not isinstance(items, list):
        raise ValueError('documentary edits must be a list')
    result = {}
    proof_ids = {plan['review_evidence']}
    proof_ids.update(v.get('evidence_id') for v in items if isinstance(v, dict)
                     and isinstance(v.get('evidence_id'), str))
    proof_hashes = {a['sha256'] for a in contract.get('artifacts', [])
                    if a['origin'] == 'current' and a['id'] in proof_ids}
    for item in items:
        fields = {'subject', 'evidence_id', 'evidence_sha256', 'reason'}
        if (not isinstance(item, dict) or set(item) != fields
                or any(not isinstance(item[k], str) or not item[k].strip() for k in fields)
                or item['subject'] in result):
            raise ValueError('invalid or duplicate documentary edit')
        node = item['subject']
        if node not in seeds or node not in base['nodes'] or node not in current['nodes']:
            raise ValueError('documentary edit requires a preexisting changed subject')
        proof = _unique_json(_artifact(contract, inputs, item['evidence_id'], item['evidence_sha256']))
        fields = {'schema_version', 'subject', 'base_text', 'current_text',
                  'base_document_sha256', 'current_document_sha256', 'declaration_sha256',
                  'edit_kind', 'historical_as_of', 'reviewed_on', 'scope', 'contexts', 'sources'}
        if (not isinstance(proof, dict) or set(proof) != fields
                or proof['schema_version'] != 'wiki_documentary_edit.v1' or proof['subject'] != node
                or proof['edit_kind'] not in {'authorized_removal', 'historical_correction'}
                or not isinstance(proof['scope'], str) or not proof['scope'].strip()):
            raise ValueError('invalid documentary edit proof')
        path = _complete_unit(current, node, proof['current_text'])
        if _complete_unit(base, node, proof['base_text']) != path:
            raise ValueError('documentary subject identity changed')
        rid = current['nodes'][node].get('document_record_id')
        declaration = next(d for d in contract['documents'] if d['path'] == path)
        records = [r for r in declaration['records'] if r['id'] == rid]
        if (len(records) != 1 or rid in {'remainder', 'preamble'}
                or not complete_h2_record(contract, declaration, records[0])
                or contract['document_modes'][path] == 'explicit_view_v2'
                   and node not in complete_component_deltas
                or records[0].get('epistemic_status') != 'observation'
                or records[0].get('current_observation')
                or proof['declaration_sha256'] != structured_digest(records[0])):
            raise ValueError('documentary edit requires a complete historical observation record')
        record = records[0]
        for origin, graph in (('base', base), ('current', current)):
            if proof[origin + '_document_sha256'] != digest(graph['documents'][path]):
                raise ValueError('documentary input snapshot changed')
        policy = ('updated_at', 'stale_after_days', 'refresh_cadence_days', 'stale_exempt')
        if (any(base['nodes'][n].get(k) != current['nodes'][n].get(k)
                for n in (path, node) for k in policy)
                or parse_updated_date(current['nodes'][node].get('updated_at')) is None):
            raise ValueError('documentary edit cannot renew or replace freshness policy')
        before = base.get('verified_record_substantive_sha256', {}).get(node)
        after = current.get('verified_record_substantive_sha256', {}).get(node)
        if not before or not after or before == after:
            raise ValueError('documentary edit requires an actual substantive delta')
        if proof['edit_kind'] == 'authorized_removal':
            # Deletion is a lexical restriction, not proof of semantic safety:
            # removing a negation can still change meaning and requires review.
            edits = SequenceMatcher(None, proof['base_text'], proof['current_text'], autojunk=False).get_opcodes()
            if any(tag not in {'equal', 'delete'} for tag, *_ in edits):
                raise ValueError('authorized removal contains inserted or replaced text')
        try:
            historical = dt.date.fromisoformat(proof['historical_as_of'])
            reviewed = dt.date.fromisoformat(proof['reviewed_on'])
            recorded = dt.date.fromisoformat(record['recorded_on'])
        except (ValueError, TypeError) as exc:
            raise ValueError('invalid documentary review date') from exc
        if (historical.isoformat() != proof['historical_as_of'] or reviewed.isoformat() != proof['reviewed_on']
                or historical >= reviewed or reviewed > recorded):
            raise ValueError('documentary review must retain an earlier historical cut')
        required = _local_contexts(current, node)
        contexts = {n: {o: g['nodes'][n]['record_sha256'] for o, g in (('base', base), ('current', current))}
                    for n in required if n in base['nodes']}
        if (required != _local_contexts(base, node) or set(contexts) != required
                or proof['contexts'] != contexts):
            raise ValueError('documentary edit omits or changes its context scope')
        if any(v['base'] != v['current'] for v in contexts.values()):
            raise ValueError('documentary edit context also changed')
        subject_hashes = {digest(g['documents'][path]) for g in (base, current)} | proof_hashes
        subject_hashes.update(digest(proof[k]) for k in ('base_text', 'current_text'))
        subject_hashes.update(g['nodes'][n]['record_sha256']
                              for g in (base, current) for n in required)
        subject_hashes.update(a['sha256'] for a in contract.get('artifacts', []) if a.get('document') == path)
        sources, seen = proof['sources'], set()
        if not isinstance(sources, list) or not sources:
            raise ValueError('documentary edit requires retained independent sources')
        for source in sources:
            if (not isinstance(source, dict) or set(source) != {'id', 'sha256', 'purpose'}
                    or any(not isinstance(source[k], str) or not source[k].strip() for k in source)
                    or source['id'] in seen | proof_ids or source['sha256'] in subject_hashes):
                raise ValueError('invalid or circular documentary source')
            _artifact(contract, inputs, source['id'], source['sha256'])
            seen.add(source['id'])
        if seen != set(record.get('current_evidence', [])):
            raise ValueError('documentary sources must remain factual prerequisites')
        result[node] = dict(evidence_id=item['evidence_id'], evidence_sha256=item['evidence_sha256'],
                            edit_kind=proof['edit_kind'], historical_as_of=historical.isoformat(),
                            reviewed_on=reviewed.isoformat())
    return result
