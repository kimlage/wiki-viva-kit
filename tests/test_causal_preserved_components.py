"""Reviewed unchanged cycles need grounded inputs, never circular authority."""
import copy
import json

import pytest

from test_causal_review import authored, contract, run
from test_causal_upstream_repairs import independent_repairs_pair, reference, _add_node
from wiki_core.causal_review import census
from wiki_core.document_records import project_records


def preserved_cycle(*, fault=None):
    base, current, changed = independent_repairs_pair()
    for graph in (base, current):
        _add_node(graph, 'peer', '# Peer\n\nKeep the complete independent duty.\n')
        next(e for e in graph['edges'] if e['source'] == 'consumer'
             and e['target'] == 'right').update(source='peer', path='peer')
        graph['edges'].extend([reference('consumer', 'peer'), reference('peer', 'consumer')])
        if fault in {'unfounded_input', 'redundant_repair'}:
            _add_node(graph, 'extra', '# Extra\n\nAnother complete duty.\n')
            graph['edges'].extend([reference('consumer', 'extra'), reference('extra', 'policy')])
    if fault in {'unfounded_input', 'redundant_repair'}:
        current['documents']['extra'] += 'Its independent local duty changed.\n'
        changed.add('extra')
        if fault == 'unfounded_input':
            current['edges'].append(reference('extra', 'left-authority'))
    if fault == 'unit_changed':
        current['documents']['peer'] += 'A new local obligation.\n'
    elif fault == 'context_changed':
        current['edges'].append(dict(reference('peer', 'left-authority'), field='context_records'))
    elif fault == 'multiplicity_changed':
        current['edges'].append(dict(reference('peer', 'consumer'), body_line=9))
    elif fault in {'stale_member', 'stale_premise', 'stale_new_arrival'}:
        for graph in (base, current):
            graph['nodes']['right-authority' if fault == 'stale_premise' else 'peer']['updated_at'] = '2026-01-01'
    spec = contract(base, current)
    pc, pb, seeds, _ = project_records(current, base, changed, spec)
    inventory = census(pc, pb, seeds)

    def qualify(plan):
        for item in plan['dispositions']:
            obligation = inventory['obligations'][item['obligation_id']]
            edge = inventory['edges'][obligation['edge_id']]
            if edge['consumer'] in {'consumer', 'peer'} and edge['prerequisite'] in (
                    {'left', 'right', 'extra'} if fault == 'redundant_repair' else {'left', 'right'}):
                item['reviewed_upstream_repairs'] = [edge['prerequisite']]
                if fault == 'blocked' and obligation['seed'] == 'other':
                    item['disposition'] = 'blocked'
                    item.pop('reviewed_upstream_repairs')

    def select(edge, obligation):
        if edge['consumer'] not in {'left', 'right', 'extra', 'consumer', 'peer'}:
            return False
        if fault == 'stale_new_arrival' and obligation['seed'] == 'other' and edge['prerequisite'] == 'peer':
            return False
        return not (fault == 'missing_current' and obligation['seed'] == 'other'
                    and edge['consumer'] == 'peer' and edge['origin'] == 'current')

    spec, inputs = authored(base, current, changed, spec=spec, select=select,
        disposition=lambda edge: 'updated' if edge['consumer'] in {'left', 'right', 'extra'} else 'no_change',
        mutate=qualify)
    return base, current, changed, spec, inputs


def test_preserved_cycle_composes_only_its_reviewed_external_repairs():
    args = preserved_cycle()
    original = copy.deepcopy(args[:3])
    result = run(*args)
    assert result['ok']
    assert any(row['path'] == 'tail' for row in result['unrelated_debt'])
    assert args[:3] == original


@pytest.mark.parametrize('fault', ['blocked', 'missing_current', 'unit_changed',
                                  'context_changed', 'multiplicity_changed', 'unfounded_input'])
def test_preserved_cycle_cannot_hide_unqualified_arrival_or_local_change(fault):
    with pytest.raises(ValueError, match='interpretation'):
        run(*preserved_cycle(fault=fault))


@pytest.mark.parametrize('fault', ['stale_member', 'stale_premise'])
def test_preserved_cycle_keeps_factual_freshness_checks(fault):
    result = run(*preserved_cycle(fault=fault))
    assert not result['ok']
    expected = 'peer' if fault == 'stale_member' else 'right-authority'
    assert any(row['path'] == expected and row['state'] == 'stale' for row in result['blockers'])


def test_preserved_cycle_does_not_make_a_redundant_repair_necessary():
    with pytest.raises(ValueError, match='unused'):
        run(*preserved_cycle(fault='redundant_repair'))


def test_freshness_failure_exposes_a_new_arrival_without_inventing_its_review():
    result = run(*preserved_cycle(fault='stale_new_arrival'))
    assert not result['ok']
    assert any(row['seed'] == 'other' and row['path'] == 'consumer'
               and row['reason'] == 'causal_missing' for row in result['blockers'])


def test_component_proof_does_not_depend_on_disposition_order():
    from test_causal_authority import reseal_review
    args = preserved_cycle()
    expected = run(*args)
    args[3]['causal_review']['dispositions'].reverse()
    reseal_review(args[3], args[4])
    actual = run(*args)
    assert actual['ok'] == expected['ok']
    assert actual['blockers'] == expected['blockers']
    for key in ('approved_boundaries', 'considered_arrivals', 'unresolved', 'beyond_boundaries'):
        assert actual['causal_review'][key] == expected['causal_review'][key]
    # The order is part of the exact authored plan, so the newly reviewed
    # artifact deliberately has a different identity despite equal semantics.
    assert actual['causal_review']['review_sha256'] != expected['causal_review']['review_sha256']


def composed_input_chain(*, fault=None, intermediaries=1):
    """A reviewed cut supplies a factual input through an untouched intermediary."""
    base, current, changed = independent_repairs_pair()
    chain = ['bridge', *(f'bridge-{n}' for n in range(1, intermediaries))]
    for graph in (base, current):
        for node in ['first', *chain]:
            _add_node(graph, node, '# ' + node + '\n\nRetain the complete input.\n')
        next(e for e in graph['edges'] if e['source'] == 'consumer'
             and e['target'] == 'left')['target'] = chain[-1]
        graph['edges'].extend([reference('first', 'left'), reference(chain[0], 'first'),
            *(reference(node, prior) for prior, node in zip(chain, chain[1:]))])
    spec = contract(base, current)
    pc, pb, seeds, _ = project_records(current, base, changed, spec)
    inventory = census(pc, pb, seeds)

    def qualify(plan):
        for item in plan['dispositions']:
            edge = inventory['edges'][inventory['obligations'][item['obligation_id']]['edge_id']]
            if edge['consumer'] == 'first':
                if fault == 'blocked':
                    item['disposition'] = 'blocked'
                else:
                    item['reviewed_upstream_repairs'] = ['left']
            elif edge['consumer'] == 'consumer' and edge['prerequisite'] == 'right':
                item['reviewed_upstream_repairs'] = ['right']

    spec, inputs = authored(base, current, changed, spec=spec,
        select=lambda e, o: e['consumer'] in {'left', 'right', 'first', 'consumer'}
            and (fault != 'missing' or e['consumer'] != 'first'),
        disposition=lambda e: 'updated' if e['consumer'] in {'left', 'right'} else 'no_change',
        mutate=qualify)
    return base, current, changed, spec, inputs


def test_completed_proof_can_cross_intact_input_without_inventing_arrival():
    args = composed_input_chain()
    result = run(*args)
    assert result['ok']
    assert 'bridge' in {row['path'] for row in result['included']}  # still a factual prerequisite
    assert 'bridge' not in {row['consumer'] for row in result['causal_review']['approved_boundaries']}
    pc, _, _, _ = project_records(args[1], args[0], args[2], args[3], artifact_inputs=args[4])
    proof = pc['verified_causal_review']['composed_interpretations']['consumer']
    assert set(proof['upstream_repairs']) == {'left', 'right'}


@pytest.mark.parametrize('fault', ['missing', 'blocked'])
def test_intact_intermediary_cannot_manufacture_missing_or_blocked_input_review(fault):
    with pytest.raises(ValueError, match='interpretation'):
        run(*composed_input_chain(fault=fault))


def test_composed_chain_receipt_keeps_flat_supports_without_recursive_proofs():
    from wiki_core.document_records import structured_digest
    args = composed_input_chain(intermediaries=40)
    pc, _, _, _ = project_records(args[1], args[0], args[2], args[3], artifact_inputs=args[4])
    verified = pc['verified_causal_review']
    proof = verified['composed_interpretations']['consumer']
    for input_proof in proof['prerequisite_qualifications'].values():
        assert 'prerequisite_qualifications' not in input_proof
    assert set(proof['upstream_repairs']) == {'left', 'right'}
    assert proof['arrivals']
    assert json.loads(json.dumps(verified)) == verified
    assert verified['payload_sha256'] == structured_digest(
        {key: value for key, value in verified.items() if key != 'payload_sha256'})
