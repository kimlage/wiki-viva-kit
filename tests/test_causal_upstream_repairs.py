"""Synthetic upstream-repair qualification; no private fixtures or new authority.

Prepared outside the checkout for the sole integrator to install and run.
The opt-in declaration binds a reviewed arrival, never an inferred waiver.
"""
import copy
import json

import pytest

from test_causal_authority import reseal_review
from test_causal_review import (
    TODAY, authored, contract, make, markdown_position_pair,
    partitioned_repair_pair, run,
)
from test_causal_revalidation import revalidated_pair
from wiki_core.causal_reconciliation import repaired_boundary
from wiki_core.causal_review import census
from wiki_core.document_records import digest, edge_digest, project_records, structured_digest
from wiki_core.freshness_impact import evaluate_impact


def reference(source, target, **extra):
    return dict(source=source, target=target, type='source_ref',
                direction='directed', basis='frontmatter', path=source,
                field='source_refs', **extra)


def _add_node(graph, name, text, *, stale=False):
    graph['documents'][name] = text
    graph['nodes'][name] = dict(updated_at='2026-01-01' if stale else '2026-10-26',
                                stale_after_days=30)


def upstream_pair(kind='citation'):
    """policy -> repaired premise -> intact consumer -> stale downstream tail."""
    base, current, changed = make()
    for graph in (base, current):
        graph['documents']['consumer'] = (
            '# Consumer\n\nApply the complete premise and retain its limits.\n')
        _add_node(graph, 'premise', '# Premise\n\nUse the policy and retain all existing duties.\n')
        _add_node(graph, 'authority', '# Authority\n\nIndependent review remains required.\n')
        next(e for e in graph['edges'] if e['source'] == 'consumer')['target'] = 'premise'
        graph['edges'].append(reference('premise', 'policy'))
    current['documents']['premise'] += 'The applicable procedure now names the independent review explicitly.\n'
    changed.add('premise')
    if kind == 'citation':
        current['documents']['premise'] += 'Use [authority](authority).\n'
        current['edges'].append(reference('premise', 'authority'))
    elif kind == 'relocation':
        for graph, section, line in ((base, 'Prior wording', 3), (current, 'Reviewed wording', 7)):
            graph['documents']['premise'] += f'\n## {section}\n\nUse [authority](authority).\n'
            graph['edges'].append(dict(source='premise', target='authority', type='markdown_link',
                direction='directed', basis='markdown_body', path='premise', field='body',
                body_section=section, body_line=line, body_offset=0))
    elif kind == 'history':
        event = dict(event_id='synthetic-origin', text='Complete historical local observation.',
                     at='2026-01-01T00:00:00Z')
        for graph in (base, current):
            text = '---\naction_dialogue: ' + json.dumps([event]) + '\n---\n# Historical source\n'
            _add_node(graph, 'history', text, stale=True)
        current['documents']['premise'] += 'The [history](history) records the origin, not current facts.\n'
        current['edges'].append(reference('premise', 'history', body_line=8))
    else:
        raise AssertionError(kind)
    spec = contract(base, current)
    if kind == 'history':
        spec['artifacts'].append(dict(origin='current', id='retained-history', document='history',
            field='action_dialogue', match_key='event_id', match_value='synthetic-origin',
            sha256=structured_digest(event)))
        raw = next(e for e in current['edges'] if e['source'] == 'premise' and e['target'] == 'history')
        spec['bindings'].append(dict(origin='current', edge_sha256=edge_digest(raw),
            consumer_record='document', role='provenance', evidence=['retained-history'],
            target_document_sha256=digest(current['documents']['history']),
            rationale='This exact new origin citation consumes the retained event, not current source state.'))
    return base, current, changed, spec


def author_upstream(base, current, changed, spec=None, *, declare=True, select=None,
                    disposition=None, mutate=None):
    spec = copy.deepcopy(spec) if spec is not None else contract(base, current)
    # Refresh only the test fixture contract after an explicit fixture mutation.
    # This does not change an old review receipt or make stale replay acceptable.
    for origin, graph in (('base', base), ('current', current)):
        spec[origin + '_documents_sha256'] = {p: digest(t) for p, t in graph['documents'].items()}
    pc, pb, seeds, _ = project_records(current, base, changed, spec)
    inventory = census(pc, pb, seeds)

    def qualify(plan):
        for item in plan['dispositions']:
            obligation = inventory['obligations'][item['obligation_id']]
            edge = inventory['edges'][obligation['edge_id']]
            if declare and edge['consumer'] == 'consumer':
                item['reviewed_upstream_repairs'] = ['premise']
        if mutate:
            mutate(plan, inventory)

    return authored(base, current, changed, spec=spec,
        select=select or (lambda e, o: e['consumer'] in {'premise', 'consumer'}),
        disposition=disposition or (lambda e: 'updated' if e['consumer'] == 'premise' else 'no_change'),
        mutate=qualify)


def assert_tail_is_retained_debt(result, tail='tail'):
    assert any(row['path'] == tail and row['state'] == 'stale' for row in result['unrelated_debt'])
    assert not any(row['path'] == tail for row in result['included'])


@pytest.mark.parametrize('kind', ['citation', 'relocation', 'history'])
def test_same_seed_explicit_repaired_frontier_preserves_upstream_and_downstream_debt(kind):
    b, c, changed, spec = upstream_pair(kind)
    untouched = copy.deepcopy((b, c, changed))
    spec, inputs = author_upstream(b, c, changed, spec)
    result = run(b, c, changed, spec, inputs)
    assert result['ok']
    assert {'policy', 'premise', 'consumer'} <= {row['path'] for row in result['included']}
    assert_tail_is_retained_debt(result)
    pc, _, _, _ = project_records(c, b, changed, spec, artifact_inputs=inputs)
    receipts = pc['verified_causal_review']['reconciled_interpretations']
    assert receipts and all('premise' in row['upstream_repairs'] for row in receipts.values())
    assert any(row['upstream_repairs']['premise'] for row in receipts.values())  # policy-seed path
    assert any(row['direct_repaired_seed'] == 'premise' for row in receipts.values())
    if kind == 'history':
        assert any(row['state'] == 'historical_evidence' for row in result['included'])
        assert any(row['path'] == 'history' and row['state'] == 'stale' for row in result['unrelated_debt'])
    else:
        assert 'authority' in {row['path'] for row in result['included']}
    assert (b, c, changed) == untouched


def test_repaired_frontier_is_never_inferred_without_explicit_arrival_declaration():
    b, c, changed, spec = upstream_pair()
    spec, inputs = author_upstream(b, c, changed, spec, declare=False)
    with pytest.raises(ValueError, match='interpretation'):
        run(b, c, changed, spec, inputs)


@pytest.mark.parametrize('binding', [False, True])
def test_direct_repaired_seed_allows_unique_markdown_section_relocation(tmp_path, binding):
    b, c, changed, spec = markdown_position_pair(tmp_path, explicit_binding=binding, semantic_change='section')
    spec, inputs = authored(b, c, changed, spec=spec,
        select=lambda e, o: e['consumer'] == 'memories/consumer.md',
        mutate=lambda plan: [row.update(reviewed_upstream_repairs=['memories/policy.md'])
                             for row in plan['dispositions']])
    result = run(b, c, changed, spec, inputs)
    assert result['ok']
    assert_tail_is_retained_debt(result, 'memories/tail.md')


def test_zero_length_exception_does_not_qualify_a_non_direct_repaired_seed():
    b, c, changed, spec = upstream_pair()
    # The current premise has its own real change, but policy is not the
    # consumer's direct prerequisite. A seed ID is not a blanket frontier.
    def request_policy(plan, inventory):
        for item in plan['dispositions']:
            edge = inventory['edges'][inventory['obligations'][item['obligation_id']]['edge_id']]
            if edge['consumer'] == 'consumer':
                item['reviewed_upstream_repairs'] = ['policy']
    spec, inputs = author_upstream(b, c, changed, spec, mutate=request_policy)
    with pytest.raises(ValueError, match='same-seed substantive support'):
        run(b, c, changed, spec, inputs)


@pytest.mark.parametrize('status', [None, 'blocked'])
def test_same_seed_path_requires_an_actual_validated_updated_disposition(status):
    b, c, changed, spec = upstream_pair()
    spec, inputs = author_upstream(b, c, changed, spec,
        select=lambda e, o: e['consumer'] == 'consumer' or status is not None and e['consumer'] == 'premise',
        disposition=lambda e: status if e['consumer'] == 'premise' else 'no_change')
    with pytest.raises(ValueError, match='same-seed substantive support'):
        run(b, c, changed, spec, inputs)


def test_another_seed_cannot_borrow_the_policy_seeds_updated_path():
    b, c, changed, spec = upstream_pair()
    for graph in (b, c):
        _add_node(graph, 'other', '# Another cause\n\nIndependent required premise.\n')
        graph['edges'].append(reference('consumer', 'other'))
    c['documents']['other'] += 'Its own substantive change.\n'
    changed.add('other')
    spec, inputs = author_upstream(b, c, changed, spec)
    with pytest.raises(ValueError, match='same-seed substantive support'):
        run(b, c, changed, spec, inputs)


@pytest.mark.parametrize('cycle', [False, True])
def test_potential_updated_path_beyond_no_change_or_cycle_cannot_supply_reachability(cycle):
    b, c, changed, spec = upstream_pair()
    for graph in (b, c):
        _add_node(graph, 'stop', '# Intact first boundary\n\nThe policy does not change this duty.\n')
        next(e for e in graph['edges'] if e['source'] == 'premise' and e['target'] == 'policy')['target'] = 'stop'
        graph['edges'].append(reference('stop', 'policy'))
        if cycle:
            _add_node(graph, 'loop', '# Loop\n\nA distinct procedure.\n')
            graph['edges'].extend([reference('loop', 'premise'), reference('premise', 'loop')])
    if cycle:
        c['documents']['loop'] += 'Its own substantive repair.\n'
        changed.add('loop')
    spec, inputs = author_upstream(b, c, changed, spec,
        select=lambda e, o: e['consumer'] in {'stop', 'premise', 'consumer', 'loop'},
        disposition=lambda e: 'updated' if e['consumer'] in {'premise', 'loop'} else 'no_change')
    with pytest.raises(ValueError, match='same-seed substantive support'):
        run(b, c, changed, spec, inputs)


def test_new_actual_stale_prerequisite_is_not_hidden_by_repaired_frontier():
    b, c, changed, spec = upstream_pair()
    for graph in (b, c):
        graph['nodes']['authority']['updated_at'] = '2026-01-01'
    spec, inputs = author_upstream(b, c, changed, spec)
    result = run(b, c, changed, spec, inputs)
    assert not result['ok']
    assert any(row['path'] == 'authority' and row['reason'] == 'required_dependency'
               and row['state'] == 'stale' for row in result['blockers'])
    assert_tail_is_retained_debt(result)


def test_repaired_premise_itself_must_still_be_fresh():
    b, c, changed, spec = upstream_pair()
    for graph in (b, c):
        graph['nodes']['premise']['updated_at'] = '2026-01-01'
    spec, inputs = author_upstream(b, c, changed, spec)
    result = run(b, c, changed, spec, inputs)
    assert not result['ok']
    assert any(row['path'] == 'premise' and row['state'] == 'stale' for row in result['blockers'])


@pytest.mark.parametrize('requested', [[], ['premise', 'premise'], ['unknown'], '', [None], [1], ['']])
def test_malformed_duplicate_unknown_or_empty_repair_declarations_fail_closed(requested):
    b, c, changed, spec = upstream_pair()
    spec, inputs = author_upstream(b, c, changed, spec)
    row = next(row for row in spec['causal_review']['dispositions'] if row['disposition'] == 'no_change')
    row['reviewed_upstream_repairs'] = requested
    reseal_review(spec, inputs)
    with pytest.raises(ValueError, match='upstream repair'):
        run(b, c, changed, spec, inputs)


@pytest.mark.parametrize('status', ['updated', 'blocked'])
def test_repair_list_is_illegal_on_updated_or_blocked_disposition(status):
    b, c, changed, spec = upstream_pair()
    spec, inputs = author_upstream(b, c, changed, spec)
    row = next(row for row in spec['causal_review']['dispositions'] if row['disposition'] == 'updated')
    row.update(disposition=status, reviewed_upstream_repairs=['premise'])
    reseal_review(spec, inputs)
    with pytest.raises(ValueError, match='invalid reviewed upstream repair declaration'):
        run(b, c, changed, spec, inputs)


def test_repair_declaration_is_rejected_when_interpretation_was_already_identical():
    b, c, changed = make()
    spec, inputs = authored(b, c, changed,
        mutate=lambda plan: [row.update(reviewed_upstream_repairs=['policy']) for row in plan['dispositions']])
    with pytest.raises(ValueError, match='unused'):
        run(b, c, changed, spec, inputs)


def test_valid_but_unconsumed_repaired_branch_cannot_be_listed():
    b, c, changed, spec = upstream_pair()
    for graph in (b, c):
        _add_node(graph, 'branch', '# Separate branch\n\nAnother complete procedure.\n')
        graph['edges'].append(reference('branch', 'policy'))
    c['documents']['branch'] += 'A valid independent substantive repair.\n'
    changed.add('branch')
    def include_unconsumed(plan, inventory):
        for row in plan['dispositions']:
            obligation = inventory['obligations'][row['obligation_id']]
            edge = inventory['edges'][obligation['edge_id']]
            if edge['consumer'] == 'consumer' and obligation['seed'] == 'policy':
                row['reviewed_upstream_repairs'] = ['premise', 'branch']
    spec, inputs = author_upstream(b, c, changed, spec,
        select=lambda e, o: e['consumer'] in {'premise', 'consumer', 'branch'},
        disposition=lambda e: 'no_change' if e['consumer'] == 'consumer' else 'updated',
        mutate=include_unconsumed)
    with pytest.raises(ValueError, match='same-seed substantive support'):
        run(b, c, changed, spec, inputs)


@pytest.mark.parametrize('fault', ['retarget', 'role', 'remove', 'multiply', 'ambiguous_relocation'])
def test_frontier_cannot_hide_loss_reclassification_or_ambiguous_relocation_of_old_reference(fault):
    b, c, changed, spec = upstream_pair('relocation')
    old = next(e for e in b['edges'] if e['source'] == 'premise' and e['target'] == 'authority')
    new = next(e for e in c['edges'] if e['source'] == 'premise' and e['target'] == 'authority')
    if fault == 'retarget':
        new['target'] = 'policy'
    elif fault == 'role':
        new['type'] = 'navigation_link'
    elif fault == 'remove':
        c['edges'].remove(new)
    elif fault == 'multiply':
        c['edges'].append({**new, 'body_line': 80})
    else:
        b['edges'].append({**old, 'body_line': 80, 'body_section': 'Second old use'})
        c['edges'].append({**new, 'body_line': 90, 'body_section': 'Second relocated use'})
    spec, inputs = author_upstream(b, c, changed, spec)
    with pytest.raises(ValueError, match='same-seed substantive support'):
        run(b, c, changed, spec, inputs)


@pytest.mark.parametrize('mode', ['h2_v1', 'explicit_view_v2'])
def test_siblings_substantive_repair_does_not_qualify_freshness_only_remainder(mode):
    b, c, changed, spec = partitioned_repair_pair(mode)
    pc, pb, _, _ = project_records(c, b, changed, spec)
    assert not repaired_boundary(pb, pc, 'consumer::record:remainder')
    assert repaired_boundary(pb, pc, 'consumer::record:specific')


def test_date_only_changed_premise_cannot_supply_an_updated_path():
    b, c, changed, spec = upstream_pair()
    b['documents']['premise'] = '---\nupdated_at: 2026-10-25\n---\nSame complete duty.\n'
    c['documents']['premise'] = b['documents']['premise'].replace('2026-10-25', '2026-10-26')
    spec, inputs = author_upstream(b, c, changed, spec)
    with pytest.raises(ValueError, match='substantive consumer repair'):
        run(b, c, changed, spec, inputs)


@pytest.mark.parametrize('change', ['scope', 'lineage', 'missing_base', 'missing_current'])
def test_repaired_boundary_requires_same_complete_scope_and_identity(change):
    b, c, changed, spec = partitioned_repair_pair('h2_v1', relevant_repair=True)
    pc, pb, _, _ = project_records(c, b, changed, spec)
    unit = 'consumer::record:specific'
    assert repaired_boundary(pb, pc, unit)
    if change == 'scope':
        pc['verified_record_shapes'][unit]['epistemic_status'] = 'observation'
    elif change == 'lineage':
        pc['verified_record_documents'][unit] = 'policy'
    elif change == 'missing_base':
        del pb['nodes'][unit]
    else:
        del pc['nodes'][unit]
    assert not repaired_boundary(pb, pc, unit)


def test_changed_mandatory_context_cannot_be_hidden_as_an_added_citation():
    b, c, changed, spec = upstream_pair()
    for graph in (b, c):
        graph['edges'].append(reference('premise', 'authority', context='mandatory'))
        graph['edges'][-1]['field'] = 'context_records'
    c['edges'].append(reference('premise', 'declaration'))
    c['edges'][-1]['field'] = 'context_records'
    spec, inputs = author_upstream(b, c, changed, spec)
    with pytest.raises(ValueError, match='same-seed substantive support'):
        run(b, c, changed, spec, inputs)


def test_revalidated_intact_rule_uses_explicit_repaired_upstream_without_borrowing_current_fact():
    def upstream(b, c, changed, spec, proof):
        for graph in (b, c):
            _add_node(graph, 'premise', '# Premise\n\nUse the existing local policy.\n')
            _add_node(graph, 'authority', '# Current normative authority\n\nKeep separate access review.\n')
            next(e for e in graph['edges'] if e['source'] == 'consumer')['target'] = 'premise'
            graph['edges'].append(reference('premise', 'policy'))
        c['documents']['premise'] += 'Repaired procedure explicitly cites its independent authority.\n'
        c['edges'].append(reference('premise', 'authority'))
        changed.add('premise')
        for origin, graph in (('base', b), ('current', c)):
            spec[origin + '_documents_sha256'] = {p: digest(t) for p, t in graph['documents'].items()}
    unit = 'consumer::record:specific'
    b, c, changed, spec, inputs = revalidated_pair(mutation=upstream,
        select=lambda e, o: e['consumer'] == 'premise' or (
            e['consumer'] == unit and o['seed'] in {'policy', 'premise'}),
        disposition=lambda e: 'updated' if e['consumer'] == 'premise' else 'revalidated')
    for row in spec['causal_review']['dispositions']:
        if row['disposition'] == 'revalidated':
            row['reviewed_upstream_repairs'] = ['premise']
    reseal_review(spec, inputs)
    result = run(b, c, changed, spec, inputs)
    assert any(row['consumer'] == unit and row['disposition'] == 'revalidated'
               for row in result['causal_review']['approved_boundaries'])
    # Other raw/sibling arrivals retain their own obligations; not a global pass.
    assert not result['ok']
    assert not any(row['path'] == unit and row.get('seed') in {'policy', 'premise'}
                   and row['reason'].startswith('causal_') for row in result['blockers'])


@pytest.mark.parametrize('mutation', ['qualification', 'edge', 'source_scope'])
def test_post_projection_changes_cannot_reuse_a_verified_upstream_frontier(mutation):
    b, c, changed, spec = upstream_pair()
    spec, inputs = author_upstream(b, c, changed, spec)
    pc, pb, seeds, _ = project_records(c, b, changed, spec, artifact_inputs=inputs)
    if mutation == 'qualification':
        for graph in (pb, pc):
            report = graph['verified_causal_review']['reconciled_interpretations']
            next(iter(report.values()))['upstream_repairs']['invented'] = []
    elif mutation == 'edge':
        next(e for e in pc['edges'] if e['source'] == 'premise')['target'] = 'declaration'
    else:
        pc.setdefault('verified_record_shapes', {})['premise'] = {'selection': 'smaller invented scope'}
    with pytest.raises(ValueError, match='changed after'):
        evaluate_impact(pc, pb, seeds, today=TODAY)


def test_arrival_declaration_is_sealed_by_independent_review_receipt():
    b, c, changed, spec = upstream_pair()
    spec, inputs = author_upstream(b, c, changed, spec)
    # Semantically identical list value remains valid; changing the review's
    # authored reason still changes the receipt's exact plan and must fail.
    row = next(row for row in spec['causal_review']['dispositions'] if row['disposition'] == 'no_change')
    row['reason'] += ' A different review statement.'
    with pytest.raises(ValueError, match='not independent'):
        run(b, c, changed, spec, inputs)
