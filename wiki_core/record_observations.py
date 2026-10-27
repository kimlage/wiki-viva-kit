"""Evidence-bound freshness of one independently reviewed H2 observation.

This does not renew its document, relax prerequisites or authenticate an actor.
The final-HEAD independent review remains responsible for semantic truth/scope.
"""
from __future__ import annotations

import datetime as dt
import json


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate observation receipt key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid observation receipt JSON') from exc


def apply_observations(graphs, contract, changes, inputs):
    from wiki_core.document_records import digest, node_id, structured_digest
    from wiki_core.freshness import is_stale_exempt, parse_updated_date

    declarations = contract['documents']
    requested = [(d, r) for d in declarations for r in d['records'] + d.get('envelope', [])
                 if 'current_observation' in r]
    if not requested:
        return
    proof_ids = {r['current_observation'] for _, r in requested if isinstance(r['current_observation'], str)}
    artifacts = {a['id']: a for a in contract.get('artifacts', []) if a['origin'] == 'current'}
    causal_review = contract.get('causal_review') or {}
    if isinstance(causal_review.get('review_evidence'), str):
        proof_ids.add(causal_review['review_evidence'])
    proof_hashes = {artifacts[aid]['sha256'] for aid in proof_ids if aid in artifacts}
    verified = {}
    current, base = graphs['current'], graphs['base']
    for declaration, record in requested:
        path, rid, aid = declaration['path'], record['id'], record['current_observation']
        nid = node_id(path, rid)
        if (contract.get('schema_version') != 'document_record.v2'
                or contract.get('document_modes', {}).get(path) != 'h2_v1'
                or record.get('epistemic_status') != 'observation'
                or record not in declaration['records'] or rid in {'remainder', 'preamble'}
                or path in changes or nid not in changes or nid not in current['nodes']):
            raise ValueError('observation requires a complete independent H2 delta')
        before = base.get('verified_record_substantive_sha256', {}).get(nid)
        after = current['verified_record_substantive_sha256'][nid]
        if before == after or not record.get('current_sha256'):
            raise ValueError('observation requires a substantive changed record')
        old_policy, policy = base['nodes'][path], current['nodes'][path]
        fields = ('updated_at', 'stale_after_days', 'refresh_cadence_days', 'stale_exempt')
        if any(old_policy.get(k) != policy.get(k) for k in fields):
            raise ValueError('observation cannot change page freshness policy')
        try:
            window = int(policy.get('stale_after_days') or 0)
        except (TypeError, ValueError):
            window = 0
        if parse_updated_date(policy.get('updated_at')) is None or window <= 0 or is_stale_exempt(policy.get('stale_exempt')):
            raise ValueError('observation requires an existing finite freshness policy')
        if not isinstance(aid, str) or aid not in artifacts or 'path' not in artifacts[aid]:
            raise ValueError('observation requires a CURRENT file receipt')
        raw = inputs.get(('current', aid))
        if raw is None or digest(raw.decode()) != artifacts[aid]['sha256']:
            raise ValueError('observation receipt bytes changed or missing')
        proof = _json(raw)
        expected = {'schema_version', 'document', 'record_id', 'document_sha256', 'record_sha256',
                    'declaration_sha256', 'observed_on', 'scope', 'contexts', 'sources', 'review'}
        if (not isinstance(proof, dict) or set(proof) != expected
                or proof['schema_version'] != 'wiki_record_observation.v1'
                or proof['document'] != path or proof['record_id'] != rid
                or proof['document_sha256'] != digest(current['documents'][path])
                or proof['record_sha256'] != current['nodes'][nid]['record_sha256']
                or proof['declaration_sha256'] != structured_digest({k: v for k, v in record.items() if k != 'current_observation'})
                or not isinstance(proof['scope'], str) or not proof['scope'].strip()):
            raise ValueError('observation receipt scope or snapshot changed')
        try:
            observed = dt.date.fromisoformat(proof['observed_on'])
            recorded = dt.date.fromisoformat(record['recorded_on'])
        except (TypeError, ValueError) as exc:
            raise ValueError('invalid observation date') from exc
        if observed.isoformat() != proof['observed_on'] or observed > recorded:
            raise ValueError('observation cannot postdate its recording')
        contexts = {name: current['nodes'][node_id(path, name)]['record_sha256'] for name in record['context_records']}
        if proof['contexts'] != contexts:
            raise ValueError('observation omits or changes mandatory contexts')
        review = proof['review']
        if (not isinstance(review, dict) or set(review) != {'author', 'reviewer', 'decision', 'unresolved_findings'}
                or any(not isinstance(review[k], str) or not review[k].strip() for k in ('author', 'reviewer'))
                or review['author'].strip() == review['reviewer'].strip()
                or review['decision'] != 'approved' or review['unresolved_findings'] != []):
            raise ValueError('observation requires independent scope/evidence review')
        sources, seen = proof['sources'], set()
        subject_hashes = {digest(g['documents'][path]) for g in (base, current)}
        subject_hashes.update({record.get('base_sha256'), record['current_sha256'], *proof_hashes})
        # A declared structured slice of the subject is still self-evidence,
        # including when identical bytes are supplied under a file/ID alias.
        subject_hashes.update(a['sha256'] for a in contract.get('artifacts', [])
                              if a.get('document') == path)
        if not isinstance(sources, list) or not sources:
            raise ValueError('observation requires retained source evidence')
        for source in sources:
            if (not isinstance(source, dict) or set(source) != {'id', 'sha256', 'purpose'}
                    or any(not isinstance(source[k], str) or not source[k].strip() for k in source)
                    or source['id'] in seen | proof_ids or source['id'] not in artifacts
                    or source['sha256'] != artifacts[source['id']]['sha256']
                    or artifacts[source['id']].get('document') == path
                    or source['sha256'] in subject_hashes):
                raise ValueError('invalid, missing or circular observation source')
            seen.add(source['id'])
        if seen != set(record.get('current_evidence', [])):
            raise ValueError('observation sources must remain exact factual prerequisites')
        current['nodes'][nid]['updated_at'] = observed.isoformat()
        verified[nid] = dict(observed_on=observed.isoformat(), receipt_id=aid, receipt_sha256=artifacts[aid]['sha256'],
            document_sha256=proof['document_sha256'], record_sha256=proof['record_sha256'],
            declaration_sha256=proof['declaration_sha256'])
    current['verified_record_observations'] = verified


def observation_is_future(graph, node, today):
    """Only projector-owned qualifications affect the ordinary freshness verdict."""
    proof = graph.get('verified_record_observations', {}).get(node)
    if proof is None:
        return False
    from wiki_core.document_records import digest
    path = graph.get('verified_record_documents', {}).get(node)
    if (path not in graph['documents'] or digest(graph['documents'][path]) != proof['document_sha256']
            or graph['nodes'][node].get('record_sha256') != proof['record_sha256']
            or graph['nodes'][node].get('updated_at') != proof['observed_on']):
        raise ValueError('verified observation changed after projection')
    return dt.date.fromisoformat(proof['observed_on']) > today
