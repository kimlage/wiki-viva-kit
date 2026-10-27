"""Reviewed unchanged cycles need grounded inputs, never circular authority."""
import copy

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
    if fault == 'unit_changed':
        current['documents']['peer'] += 'A new local obligation.\n'
    elif fault == 'context_changed':
        current['edges'].append(dict(reference('peer', 'left-authority'), field='context_records'))
    elif fault == 'multiplicity_changed':
        current['edges'].append(dict(reference('peer', 'consumer'), body_line=9))
    elif fault in {'stale_member', 'stale_premise'}:
        for graph in (base, current):
            graph['nodes']['peer' if fault == 'stale_member' else 'right-authority']['updated_at'] = '2026-01-01'
    spec = contract(base, current)
    pc, pb, seeds, _ = project_records(current, base, changed, spec)
    inventory = census(pc, pb, seeds)

    def qualify(plan):
        for item in plan['dispositions']:
            obligation = inventory['obligations'][item['obligation_id']]
            edge = inventory['edges'][obligation['edge_id']]
            if edge['consumer'] in {'consumer', 'peer'} and edge['prerequisite'] in {'left', 'right'}:
                item['reviewed_upstream_repairs'] = [edge['prerequisite']]
                if fault == 'blocked' and obligation['seed'] == 'other':
                    item['disposition'] = 'blocked'
                    item.pop('reviewed_upstream_repairs')

    def select(edge, obligation):
        if edge['consumer'] not in {'left', 'right', 'consumer', 'peer'}:
            return False
        return not (fault == 'missing_current' and obligation['seed'] == 'other'
                    and edge['consumer'] == 'peer' and edge['origin'] == 'current')

    spec, inputs = authored(base, current, changed, spec=spec, select=select,
        disposition=lambda edge: 'updated' if edge['consumer'] in {'left', 'right'} else 'no_change',
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
                                  'context_changed', 'multiplicity_changed'])
def test_preserved_cycle_cannot_hide_unqualified_arrival_or_local_change(fault):
    with pytest.raises(ValueError, match='interpretation'):
        run(*preserved_cycle(fault=fault))


@pytest.mark.parametrize('fault', ['stale_member', 'stale_premise'])
def test_preserved_cycle_keeps_factual_freshness_checks(fault):
    result = run(*preserved_cycle(fault=fault))
    assert not result['ok']
    expected = 'peer' if fault == 'stale_member' else 'right-authority'
    assert any(row['path'] == expected and row['state'] == 'stale' for row in result['blockers'])
