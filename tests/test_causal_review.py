"""Synthetic only: bounded causal review is not a date waiver or permission."""
import copy
import datetime as dt
import json

import pytest

from wiki_core.causal_review import census, pair_digest
from wiki_core.document_records import project_records, digest, structured_digest, edge_digest, sections
from wiki_core.freshness_impact import evaluate_impact

TODAY = dt.date(2026, 10, 26)


def make(*, old_prerequisite=False):
    nodes = {p: dict(updated_at='2026-10-26', stale_after_days=30) for p in ('policy', 'consumer', 'tail', 'declaration')}
    nodes['tail']['updated_at'] = '2026-01-01'
    documents = {p: '# ' + p + '\n' for p in nodes}
    documents['declaration'] = '# Declaration\n\n## Stable\n\nComplete unrelated unit.\n'
    documents['consumer'] = '# Consumer\n\nUse the policy; its reviewed authorization wording does not change this duty.\n'
    def edge(a, b):
        return dict(source=a, target=b, type='source_ref', direction='directed', basis='frontmatter', path=a, field='source_refs')
    edges = [edge('consumer', 'policy'), edge('tail', 'consumer')]
    if old_prerequisite:
        nodes['required'] = dict(updated_at='2026-01-01', stale_after_days=30)
        documents['required'] = '# Required fact\n'
        edges.append(edge('consumer', 'required'))
    base = dict(documents=documents, nodes=nodes, edges=edges, errors=[])
    current = copy.deepcopy(base)
    current['documents']['policy'] += 'Review follows the applicable authorization.\n'
    return base, current, {'policy'}


def contract(base, current):
    content = '## Stable\n\nComplete unrelated unit.\n'
    return dict(schema_version='document_record.v2',
        base_documents_sha256={p: digest(t) for p, t in base['documents'].items()},
        current_documents_sha256={p: digest(t) for p, t in current['documents'].items()},
        documents=[dict(path='declaration', records=[dict(id='stable', heading='Stable', independent=True,
            rationale='Unchanged complete synthetic independent unit.', epistemic_status='observation',
            recorded_on='2026-10-26', context_records=[], base_sha256=digest(content), current_sha256=digest(content))])],
        document_modes={'declaration': 'h2_v1'}, bindings=[], artifacts=[])


def authored(base, current, changed, *, select=None, disposition='no_change', mutate=None, spec=None):
    c = copy.deepcopy(spec) if spec is not None else contract(base, current)
    pc, pb, seeds, _ = project_records(current, base, changed, c)
    inventory = census(pc, pb, seeds)
    selected = []
    for oid, obligation in inventory['obligations'].items():
        e = inventory['edges'][obligation['edge_id']]
        if select(e, obligation) if select else e['consumer'] == 'consumer':
            selected.append(dict(obligation_id=oid, disposition=disposition(e) if callable(disposition) else disposition,
                reason='Exact changed approval wording leaves this complete consumer duty unchanged; no assertion about downstream current facts.'))
    plan = dict(schema_version='wiki_causal_review.v1', author='fixture-author',
        pair_sha256=pair_digest(pc, pb, seeds), census_sha256=structured_digest(inventory),
        dispositions=selected, review_evidence='synthetic-independent-review')
    if mutate:
        mutate(plan)
    receipt = dict(schema_version='wiki_causal_review_receipt.v1', author='fixture-author', reviewer='fixture-reviewer',
        decision='approved', plan_sha256=structured_digest({k: v for k, v in plan.items() if k != 'review_evidence'}), unresolved_findings=[])
    data = (json.dumps(receipt, sort_keys=True) + '\n').encode()
    c['causal_review'] = plan
    c['artifacts'].append(dict(origin='current', id=plan['review_evidence'], path='review.json', sha256=digest(data.decode())))
    inputs = {('current', plan['review_evidence']): data}
    return c, inputs


def run(base, current, changed, c, inputs):
    pc, pb, seeds, _ = project_records(current, base, changed, c, artifact_inputs=inputs)
    return evaluate_impact(pc, pb, seeds, today=TODAY)


def test_opt_in_exact_causal_boundary_preserves_factual_edges_and_debt():
    b, c, changed = make()
    before = copy.deepcopy((b, c))
    spec, inputs = authored(b, c, changed)
    result = run(b, c, changed, spec, inputs)
    assert result['ok']
    assert {r['path'] for r in result['included']} == {'policy', 'consumer'}
    assert any(r['path'] == 'tail' and r['state'] == 'stale' for r in result['unrelated_debt'])
    assert len(result['causal_review']['approved_boundaries']) == 2  # BASE and CURRENT occurrences
    assert (b, c) == before


def test_legacy_no_change_is_not_a_freshness_waiver():
    b, c, changed = make()
    c['nodes']['consumer']['impact_closure'] = {'no_change': [{'page': 'tail', 'reason': 'Administrative note'}]}
    result = evaluate_impact(c, b, changed, today=TODAY)
    assert not result['ok'] and any(r['path'] == 'tail' for r in result['blockers'])


def test_fresh_missing_disposition_blocks_opted_in_workflow():
    b, c, changed = make()
    spec, inputs = authored(b, c, changed, select=lambda e, o: False)
    result = run(b, c, changed, spec, inputs)
    assert any(r['path'] == 'consumer' and r['state'] == 'fresh' and r['reason'] == 'causal_missing' for r in result['blockers'])


@pytest.mark.parametrize('status', ['blocked', 'no_change'])
def test_stale_boundary_does_not_hide_downstream(status):
    b, c, changed = make()
    for g in (b, c): g['nodes']['consumer']['updated_at'] = '2026-01-01'
    spec, inputs = authored(b, c, changed, disposition=status)
    result = run(b, c, changed, spec, inputs)
    assert not result['ok']
    assert {'consumer', 'tail'} <= {r['path'] for r in result['blockers']}


def test_real_prerequisites_still_block_at_reviewed_boundary():
    b, c, changed = make(old_prerequisite=True)
    spec, inputs = authored(b, c, changed)
    result = run(b, c, changed, spec, inputs)
    assert any(r['path'] == 'required' and r['reason'] == 'required_dependency' for r in result['blockers'])


def test_uncovered_current_occurrence_is_not_cleared_by_base_review():
    b, c, changed = make()
    spec, inputs = authored(b, c, changed, select=lambda e, o: e['consumer'] == 'consumer' and e['origin'] == 'base')
    result = run(b, c, changed, spec, inputs)
    assert any(r['path'] == 'tail' for r in result['blockers'])
    assert any(r['reason'] == 'causal_missing' for r in result['blockers'])


def test_alternate_later_path_to_same_node_remains_pending():
    b, c, changed = make()
    for g in (b, c):
        g['nodes']['route'] = dict(updated_at='2026-10-26', stale_after_days=30)
        g['documents']['route'] = '# Same unchanged intermediate\n'
        g['edges'].extend([dict(source='route', target='policy', type='source_ref', direction='directed', basis='frontmatter', path='route', field='source_refs'),
                           dict(source='consumer', target='route', type='source_ref', direction='directed', basis='frontmatter', path='consumer', field='evidence_refs')])
    spec, inputs = authored(b, c, changed, select=lambda e, o: e['consumer'] == 'consumer' and e['prerequisite'] == 'policy')
    result = run(b, c, changed, spec, inputs)
    assert any(r['path'] == 'consumer' and r['reason'] == 'causal_missing' for r in result['blockers'])
    assert any(r['path'] == 'tail' for r in result['blockers'])


def test_other_seed_and_cycle_cannot_be_cleared_by_first_review():
    b, c, changed = make()
    for g in (b, c):
        g['nodes']['other'] = dict(updated_at='2026-10-26', stale_after_days=30)
        g['documents']['other'] = '# Other factual premise\n'
        g['edges'].extend([dict(source='consumer', target='other', type='source_ref', direction='directed', basis='frontmatter', path='consumer', field='claims'),
                           dict(source='other', target='consumer', type='source_ref', direction='directed', basis='frontmatter', path='other', field='evidence_refs')])
    c['documents']['other'] += 'A fact changed.\n'; changed.add('other')
    spec, inputs = authored(b, c, changed, select=lambda e, o: e['consumer'] == 'consumer' and o['seed'] == 'policy')
    result = run(b, c, changed, spec, inputs)
    assert any(r['path'] == 'tail' for r in result['blockers'])
    assert any(r['seed'] == 'other' and r['reason'] == 'causal_missing' for r in result['blockers'])


def test_changed_consumer_cannot_be_no_change():
    b, c, changed = make(); c['documents']['consumer'] += 'Changed assertion.\n'; changed.add('consumer')
    spec, inputs = authored(b, c, changed)
    with pytest.raises(ValueError, match='identical full consumer'): run(b, c, changed, spec, inputs)


def test_date_only_is_not_substantive_updated():
    b, c, changed = make()
    b['documents']['consumer'] = '---\nupdated_at: 2026-10-25\n---\nSame duty.\n'
    c['documents']['consumer'] = b['documents']['consumer'].replace('2026-10-25', '2026-10-26')
    changed.add('consumer'); spec, inputs = authored(b, c, changed, disposition='updated')
    with pytest.raises(ValueError, match='substantive'): run(b, c, changed, spec, inputs)


def test_changed_interpretation_is_not_equal_bytes():
    b, c, changed = make()
    c['edges'][0]['field'] = 'claims'  # Same bytes, changed documentary interpretation.
    spec, inputs = authored(b, c, changed)
    with pytest.raises(ValueError, match='interpretation'): run(b, c, changed, spec, inputs)


@pytest.mark.parametrize('field', ['pair_sha256', 'census_sha256'])
def test_mismatched_guard_fails(field):
    b, c, changed = make(); spec, inputs = authored(b, c, changed, mutate=lambda p: p.update({field: '0' * 64}))
    with pytest.raises(ValueError, match='pair/census'): run(b, c, changed, spec, inputs)


@pytest.mark.parametrize('mutation', [lambda r: r.update(reviewer='fixture-author'), lambda r: r.update(decision='pending'),
    lambda r: r.update(unresolved_findings=['Open finding']), lambda r: r.update(plan_sha256='0'*64)])
def test_review_receipt_is_bound_and_independent(mutation):
    b, c, changed = make(); spec, inputs = authored(b, c, changed)
    k = next(iter(inputs)); r = json.loads(inputs[k]); mutation(r); inputs[k] = json.dumps(r).encode();spec['artifacts'][0]['sha256'] = digest(inputs[k].decode())
    with pytest.raises(ValueError, match='not independent'): run(b, c, changed, spec, inputs)


def test_post_projection_mutation_invalidates_review():
    b, c, changed = make(); spec, inputs = authored(b, c, changed)
    pc, pb, seeds, _ = project_records(c, b, changed, spec, artifact_inputs=inputs)
    pc['nodes']['consumer']['updated_at'] = '2026-10-27'
    with pytest.raises(ValueError, match='inputs changed'): evaluate_impact(pc, pb, seeds, today=TODAY)


def test_incomplete_duplicate_or_unknown_dispositions_fail():
    b, c, changed = make()
    for mutate in (lambda p: p['dispositions'].append(copy.deepcopy(p['dispositions'][0])),
                   lambda p: p['dispositions'][0].update(obligation_id='0'*64),
                   lambda p: p['dispositions'][0].update(reason='')):
        spec, inputs = authored(b, c, changed, mutate=mutate)
        with pytest.raises(ValueError, match='disposition'): run(b, c, changed, spec, inputs)


def test_remainder_selection_change_is_not_equal_interpretation():
    b, c, changed = make()
    b['documents']['policy'] = '# Policy\n\n## Original\n\nOriginal duty.\n\n## Other\n\nOther duty.\n'
    c['documents']['policy'] = b['documents']['policy'] + 'Clarified applicable review.\n'
    spec = contract(b, c)
    record = dict(id='selected', independent=True, rationale='Complete synthetic section.',
                  epistemic_status='decision', recorded_on='2026-10-26', context_records=[],
                  selectors={'base': {'kind': 'h2', 'heading': 'Original'},
                             'current': {'kind': 'h2', 'heading': 'Other'}})
    for origin, g, heading in (('base', b, 'Original'), ('current', c, 'Other')):
        selected = sections(g['documents']['policy'])[1][heading][2]
        record[origin + '_sha256'] = digest(selected)
        edge = next(e for e in g['edges'] if e['source'] == 'consumer')
        spec['bindings'].append(dict(origin=origin, edge_sha256=edge_digest(edge),
            target_record='remainder', consumed_sha256=digest(g['documents']['policy'].replace(selected, '', 1)),
            rationale='Deliberately differing remainder for adversarial scope proof.'))
    spec['documents'].append(dict(path='policy', records=[record]))
    spec['document_modes']['policy'] = 'explicit_view_v2'
    spec, inputs = authored(b, c, changed, spec=spec)
    with pytest.raises(ValueError, match='interpretation'):
        run(b, c, changed, spec, inputs)


def test_transitive_context_reclassification_is_not_equal_interpretation():
    b, c, changed = make(old_prerequisite=True)
    for g in (b, c):
        g['edges'].append(dict(source='policy', target='required', type='source_ref',
            direction='directed', basis='frontmatter', path='policy', field='context_records'))
    c['edges'][-1]['field'] = 'evidence_refs'
    spec, inputs = authored(b, c, changed)
    with pytest.raises(ValueError, match='interpretation'):
        run(b, c, changed, spec, inputs)


@pytest.mark.parametrize('key', ['verified_evidence_nodes', 'verified_record_documents', 'verified_record_shapes'])
def test_trusted_projection_marker_mutation_invalidates_pair(key):
    b, c, changed = make(old_prerequisite=True)
    spec, inputs = authored(b, c, changed)
    pc, pb, seeds, _ = project_records(c, b, changed, spec, artifact_inputs=inputs)
    if key == 'verified_evidence_nodes':
        pc[key].append('required')
    else:
        pc[key]['required'] = 'invented-scope'
    with pytest.raises(ValueError, match='inputs changed'):
        evaluate_impact(pc, pb, seeds, today=TODAY)


def test_stale_exemption_only_is_not_a_substantive_update():
    b, c, changed = make()
    b['documents']['consumer'] = '---\nstale_exempt: false\n---\nUnrepaired duty.\n'
    c['documents']['consumer'] = b['documents']['consumer'].replace('false', 'true')
    c['nodes']['consumer']['stale_exempt'] = True
    changed.add('consumer')
    spec, inputs = authored(b, c, changed, disposition='updated')
    with pytest.raises(ValueError, match='substantive'):
        run(b, c, changed, spec, inputs)


def test_removed_seed_retains_base_obligation():
    b, c, changed = make()
    del c['documents']['policy']; del c['nodes']['policy']
    c['edges'] = [e for e in c['edges'] if e['target'] != 'policy']
    spec, inputs = authored(b, c, changed, disposition='blocked')
    result = run(b, c, changed, spec, inputs)
    assert result['removed_pages'] == ['policy']
    assert any(r['seed'] == 'policy' and r['reason'] == 'causal_blocked' for r in result['blockers'])
    assert not result['ok']


def test_removed_consumer_cannot_receive_no_change():
    b, c, changed = make()
    del c['documents']['consumer']; del c['nodes']['consumer']; changed.add('consumer')
    c['edges'] = []
    spec, inputs = authored(b, c, changed)
    with pytest.raises(ValueError, match='removed/added consumer'):
        run(b, c, changed, spec, inputs)


def test_updated_repair_propagates_to_separately_reviewed_unchanged_tail():
    b, c, changed = make()
    for g in (b, c):
        g['nodes']['tail']['updated_at'] = '2026-10-26'
    c['documents']['consumer'] += 'Applicable review is independent and bound to the final revision.\n'
    changed.add('consumer')
    spec, inputs = authored(b, c, changed, select=lambda e, o: True,
        disposition=lambda e: 'updated' if e['consumer'] == 'consumer' else 'no_change')
    result = run(b, c, changed, spec, inputs)
    assert result['ok']
    assert {r['path'] for r in result['included']} == {'policy', 'consumer', 'tail'}
    assert all(v['consumer'] == 'tail' for v in result['causal_review']['approved_boundaries'])


@pytest.mark.parametrize('raw', [b'{"decision": "approved", "decision": "approved"}', b'[]', b'not-json', b'\xff'])
def test_malformed_receipt_is_rejected(raw):
    b, c, changed = make()
    spec, inputs = authored(b, c, changed)
    import hashlib
    inputs[next(iter(inputs))] = raw
    spec['artifacts'][0]['sha256'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        run(b, c, changed, spec, inputs)


def test_receipt_bytes_changed_without_guard_is_rejected():
    b, c, changed = make()
    spec, inputs = authored(b, c, changed)
    inputs[next(iter(inputs))] += b' '
    with pytest.raises(ValueError, match='immutable evidence bytes'):
        run(b, c, changed, spec, inputs)


def test_same_mutation_of_both_verified_reviews_is_rejected():
    b, c, changed = make()
    spec, inputs = authored(b, c, changed, disposition='blocked')
    pc, pb, seeds, _ = project_records(c, b, changed, spec, artifact_inputs=inputs)
    for graph in (pc, pb):
        for item in graph['verified_causal_review']['dispositions'].values():
            item['disposition'] = 'no_change'
    with pytest.raises(ValueError, match='payload changed'):
        evaluate_impact(pc, pb, seeds, today=TODAY)


def test_git_repository_report_two_successive_reviews_and_stale_replay(tmp_path):
    """Exercise actual Markdown graph, Git BASE, artifact reads and next delta."""
    import subprocess
    import yaml
    from wiki_core.config import load_config
    from wiki_core.freshness_impact import authored_graph, repository_report
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, text=True).strip()
    git('init', '-q'); git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'user.name', 'Synthetic Fixture')
    config = tmp_path / 'wiki.config.yaml'
    config.write_text('audit:\n  freshness_scope: impact\n')
    memory = tmp_path / 'memories'; memory.mkdir()
    bodies = {'policy': '# Policy\n\nReview applicable permissions.\n',
              'consumer': '# Consumer\n\nUse [policy](policy.md).\n',
              'tail': '# Tail\n\nUse [consumer](consumer.md).\n',
              'declaration': '# Declaration\n\n## Stable\n\nComplete unrelated unit.\n'}
    for name, body in bodies.items():
        fields = dict(page_id=name, page_type='project', updated_at='2026-01-01' if name == 'tail' else '2026-10-26',
                      stale_after_days=30)
        (memory / (name + '.md')).write_text('---\n' + yaml.safe_dump(fields) + '---\n' + body)
    refs = tmp_path / 'docs/references'; refs.mkdir(parents=True)
    git('add', '.'); git('commit', '-qm', 'Initial synthetic policy')
    previous_spec = None
    for round_no in (1, 2):
        base_sha = git('rev-parse', 'HEAD')
        base = authored_graph(tmp_path, load_config(tmp_path))
        policy = memory / 'policy.md'
        policy.write_text(policy.read_text() + f'\nClarification {round_no}: review remains independent.\n')
        current = authored_graph(tmp_path, load_config(tmp_path))
        if previous_spec:
            with pytest.raises(ValueError, match='snapshot does not match'):
                repository_report(tmp_path, load_config(tmp_path), base_sha, today=TODAY)
        spec = dict(schema_version='document_record.v2',
            base_documents_sha256={p: digest(t) for p, t in base['documents'].items()},
            current_documents_sha256={p: digest(t) for p, t in current['documents'].items()},
            documents=[dict(path='memories/declaration.md', records=[dict(id='stable', heading='Stable', independent=True,
                rationale='Complete independent synthetic unit.', epistemic_status='observation',
                recorded_on='2026-10-26', context_records=[],
                base_sha256=digest('## Stable\n\nComplete unrelated unit.\n'),
                current_sha256=digest('## Stable\n\nComplete unrelated unit.\n'))])],
            document_modes={'memories/declaration.md': 'h2_v1'}, bindings=[], artifacts=[])
        evidence_path = f'docs/references/review-{round_no}.json'
        (tmp_path / evidence_path).write_text('{}')
        (refs / 'records.json').write_text('{}')
        config.write_text('audit:\n  freshness_scope: impact\n  freshness_records: docs/references/records.json\n')
        from scripts.wiki_page_graph import collect_git_changes
        changes = set(collect_git_changes(base_sha, root=tmp_path).paths)
        spec, inputs = authored(base, current, changes, spec=spec,
                               select=lambda e, o: e['consumer'] == 'memories/consumer.md')
        spec['artifacts'][0]['path'] = evidence_path
        (tmp_path / evidence_path).write_bytes(next(iter(inputs.values())))
        # Artifact location changes do not change unreferenced graph semantics;
        # its full immutable bytes/path are still checked by the projector.
        (refs / 'records.json').write_text(json.dumps(spec))
        result = repository_report(tmp_path, load_config(tmp_path), base_sha, today=TODAY)
        assert result['ok'] and result['base_sha'] == base_sha
        assert result['causal_review']['approved_boundaries']
        assert any(r['path'] == 'memories/tail.md' for r in result['unrelated_debt'])
        previous_spec = spec
        git('add', '.'); git('commit', '-qm', f'Reviewed synthetic clarification {round_no}')
    assert (refs / 'review-1.json').exists() and (refs / 'review-2.json').exists()
