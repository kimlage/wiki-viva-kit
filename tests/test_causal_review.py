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
    with pytest.raises(ValueError, match='identical complete consumer unit'): run(b, c, changed, spec, inputs)


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


@pytest.mark.parametrize('key', ['verified_evidence_nodes', 'verified_record_documents', 'verified_record_shapes',
                               'verified_record_substantive_sha256', 'verified_precise_component_seeds'])
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


def markdown_position_pair(tmp_path, *, explicit_binding=False, semantic_change=None):
    """Real Markdown occurrences, including a transitively consumed source."""
    import yaml
    from wiki_core.config import load_config
    from wiki_core.freshness_impact import authored_graph
    (tmp_path / 'wiki.config.yaml').write_text('audit:\n  freshness_scope: impact\n')
    memory = tmp_path / 'memories'; memory.mkdir()
    bodies = {'policy': '# Policy\n\n## Scope\n\nUse [required](required.md).\n',
              'consumer': '# Consumer\n\nUse [policy](policy.md).\n',
              'tail': '# Tail\n\nUse [consumer](consumer.md).\n',
              'required': '# Required\n\n## Fact\n\nStable required duty.\n',
              'other': '# Other\n\nAnother required duty.\n'}
    for name, body in bodies.items():
        fields = dict(page_id=name, page_type='project', updated_at='2026-01-01' if name == 'tail' else '2026-10-26',
                      stale_after_days=30)
        (memory / (name + '.md')).write_text('---\n' + yaml.safe_dump(fields) + '---\n' + body)
    base = authored_graph(tmp_path, load_config(tmp_path))
    path = memory / 'policy.md'
    text = path.read_text().replace('Use [required]', 'Clarified applicable review.\n\nUse [required]')
    if semantic_change == 'section': text = text.replace('## Scope', '## Different duty')
    if semantic_change == 'target': text = text.replace('(required.md)', '(other.md)')
    if semantic_change == 'multiplicity': text += '\nAlso use [required](required.md).\n'
    path.write_text(text)
    current = authored_graph(tmp_path, load_config(tmp_path))
    if semantic_change in {'field', 'classification'}:
        edge = next(e for e in current['edges'] if e['source'] == 'memories/policy.md')
        edge[semantic_change] = 'different-semantic-role'
    content = '## Fact\n\nStable required duty.\n'
    spec = dict(schema_version='document_record.v2',
        base_documents_sha256={p: digest(t) for p,t in base['documents'].items()},
        current_documents_sha256={p: digest(t) for p,t in current['documents'].items()},
        documents=[dict(path='memories/required.md', records=[dict(id='fact', heading='Fact', independent=True,
            rationale='Complete stable prerequisite.', epistemic_status='decision', recorded_on='2026-10-26',
            context_records=[], base_sha256=digest(content), current_sha256=digest(content))])],
        document_modes={'memories/required.md':'h2_v1'}, bindings=[], artifacts=[])
    if explicit_binding:
        for origin, graph in (('base',base),('current',current)):
            edge = next(e for e in graph['edges'] if e['source']=='memories/policy.md')
            spec['bindings'].append(dict(origin=origin, edge_sha256=edge_digest(edge),
                consumer_record='document', role='consumption', target_record='fact',
                consumed_sha256=digest(content), rationale='This occurrence consumes the complete duty.'))
    return base,current,{'memories/policy.md'},spec


@pytest.mark.parametrize('explicit_binding', [False, True])
def test_transitive_markdown_position_shift_keeps_semantics_but_rebinds_review(tmp_path, explicit_binding):
    b,c,changed,spec = markdown_position_pair(tmp_path, explicit_binding=explicit_binding)
    be = next(e for e in b['edges'] if e['source']=='memories/policy.md')
    ce = next(e for e in c['edges'] if e['source']=='memories/policy.md')
    assert be['body_line'] != ce['body_line'] and be['body_offset'] != ce['body_offset']
    assert edge_digest(be) != edge_digest(ce)
    spec,inputs = authored(b,c,changed,spec=spec,select=lambda e,o:e['consumer']=='memories/consumer.md')
    result = run(b,c,changed,spec,inputs)
    assert result['ok']
    assert any(r['path']=='memories/tail.md' for r in result['unrelated_debt'])
    # New coordinates remain bound by the full pair/census, never normalized there.
    moved = copy.deepcopy(c)
    edge = next(e for e in moved['edges'] if e['source']=='memories/policy.md')
    edge['body_offset'] += 1
    if explicit_binding:
        for binding in spec['bindings']:
            if binding['origin']=='current': binding['edge_sha256']=edge_digest(edge)
    with pytest.raises(ValueError, match='pair/census'):
        run(b,moved,changed,spec,inputs)


@pytest.mark.parametrize('semantic_change', ['section','target','multiplicity','field','classification'])
def test_position_normalization_does_not_hide_semantic_dependency_change(tmp_path, semantic_change):
    b,c,changed,spec = markdown_position_pair(tmp_path, semantic_change=semantic_change)
    spec,inputs = authored(b,c,changed,spec=spec,select=lambda e,o:e['consumer']=='memories/consumer.md')
    with pytest.raises(ValueError, match='identical complete consumer unit and interpretation'):
        run(b,c,changed,spec,inputs)


def partitioned_repair_pair(mode, *, field='updated_at', relevant_repair=False, envelope=False):
    """A real repair in one H2 cannot repair freshness-only sibling metadata."""
    b, c, changed = make()
    old, new = {'updated_at': ('2026-10-25', '2026-10-26'), 'published_on': ('2026-10-25', '2026-10-26'),
                'stale_after_days': ('30', '60'), 'refresh_cadence_days': ('7', '14'),
                'stale_exempt': ('false', 'true')}[field]
    b['documents']['consumer'] = (f'---\n{field}: {old}\n---\n# Consumer\n\n'
        'Common duty remains.\n\n## Specific\n\nA separate duty.\n')
    c['documents']['consumer'] = b['documents']['consumer'].replace(
        f'{field}: {old}', f'{field}: {new}').replace('A separate duty.', 'A separate duty was repaired.')
    if relevant_repair:
        c['documents']['consumer'] = c['documents']['consumer'].replace(
            'Common duty remains.', 'Common duty now requires independent review.')
    changed.add('consumer')
    spec = contract(b, c)
    record = dict(id='specific', independent=True, rationale='Complete separate synthetic duty.',
                  epistemic_status='decision', recorded_on='2026-10-26', context_records=[])
    for origin, graph in (('base', b), ('current', c)):
        record[origin + '_sha256'] = digest(sections(graph['documents']['consumer'])[1]['Specific'][2])
    if mode == 'h2_v1':
        record['heading'] = 'Specific'
    else:
        record['selectors'] = {origin: dict(kind='h2', heading='Specific') for origin in ('base', 'current')}
    declaration = dict(path='consumer', records=[record])
    if envelope:
        declaration['envelope'] = [dict(id='publication', rationale='Declared publication metadata.',
            context_records=[], claim='artifact_publication_date', value_shape='canonical_iso_date',
            selectors={origin: dict(kind='frontmatter_field', path=[field]) for origin in ('base', 'current')},
            base_sha256=digest(f'{field}: {old}\n'), current_sha256=digest(f'{field}: {new}\n'))]
    spec['documents'].append(declaration)
    spec['document_modes']['consumer'] = mode
    return b, c, changed, spec


@pytest.mark.parametrize('mode', ['h2_v1', 'explicit_view_v2'])
@pytest.mark.parametrize('field', ['updated_at', 'stale_after_days', 'refresh_cadence_days', 'stale_exempt'])
def test_other_h2_repair_cannot_validate_freshness_only_remainder(mode, field):
    from wiki_core.document_records import node_id
    b, c, changed, spec = partitioned_repair_pair(mode, field=field)
    spec, inputs = authored(b, c, changed, spec=spec, disposition='updated',
        select=lambda e, o: e['consumer'] == node_id('consumer', 'remainder'))
    assert spec['causal_review']['dispositions']
    with pytest.raises(ValueError, match='affected record'):
        run(b, c, changed, spec, inputs)


@pytest.mark.parametrize('field', ['updated_at', 'published_on'])
def test_other_h2_repair_cannot_validate_freshness_only_envelope_field(field):
    from wiki_core.document_records import node_id
    b, c, changed, spec = partitioned_repair_pair('explicit_view_v2', field=field, envelope=True)
    spec, inputs = authored(b, c, changed, spec=spec, disposition='updated',
        select=lambda e, o: e['consumer'] == node_id('consumer', 'publication'))
    assert spec['causal_review']['dispositions']
    with pytest.raises(ValueError, match='affected record'):
        run(b, c, changed, spec, inputs)


@pytest.mark.parametrize('mode', ['h2_v1', 'explicit_view_v2'])
@pytest.mark.parametrize('record', ['specific', 'remainder'])
def test_substantive_repair_in_exact_affected_record_is_accepted(mode, record):
    from wiki_core.document_records import node_id
    b, c, changed, spec = partitioned_repair_pair(mode, relevant_repair=True)
    spec, inputs = authored(b, c, changed, spec=spec, disposition='updated',
        select=lambda e, o: e['consumer'] == node_id('consumer', record))
    assert spec['causal_review']['dispositions']
    pc, pb, seeds, _ = project_records(c, b, changed, spec, artifact_inputs=inputs)
    assert pc['verified_causal_review']['dispositions']


def unchanged_unit_sibling_repair(mode):
    b, c, changed, spec = partitioned_repair_pair(mode)
    c['documents']['consumer'] = b['documents']['consumer'].replace(
        'Common duty remains.', 'Common duty now requires independent review.')
    spec['current_documents_sha256']['consumer'] = digest(c['documents']['consumer'])
    declaration = next(d for d in spec['documents'] if d['path'] == 'consumer')
    declaration['records'][0]['current_sha256'] = declaration['records'][0]['base_sha256']
    return b, c, changed, spec


@pytest.mark.parametrize('mode', ['h2_v1', 'explicit_view_v2'])
def test_unchanged_complete_record_can_be_reviewed_when_its_sibling_changes(mode):
    """A sibling repair does not force fictional edits to an intact duty."""
    from wiki_core.document_records import node_id
    b, c, changed, spec = unchanged_unit_sibling_repair(mode)
    spec, inputs = authored(b, c, changed, spec=spec,
        select=lambda e, o: e['consumer'] == node_id('consumer', 'specific'))
    assert spec['causal_review']['dispositions']
    pc, pb, seeds, _ = project_records(c, b, changed, spec, artifact_inputs=inputs)
    assert pc['verified_causal_review']['dispositions']
    result = evaluate_impact(pc, pb, seeds, today=TODAY)
    assert not any(r.get('path') == node_id('consumer', 'specific')
                   and r.get('reason') == 'causal_missing' for r in result['blockers'])
    # This unit's review does not clear raw WHOLE consumers or sibling causes.
    assert not result['ok']


@pytest.mark.parametrize('mode', ['h2_v1', 'explicit_view_v2'])
def test_unchanged_unit_cannot_borrow_renewed_freshness_from_sibling(mode):
    from wiki_core.document_records import node_id
    b, c, changed, spec = unchanged_unit_sibling_repair(mode)
    b['nodes']['consumer']['updated_at'] = '2026-01-01'
    b['documents']['consumer'] = b['documents']['consumer'].replace('2026-10-25', '2026-01-01')
    c['documents']['consumer'] = c['documents']['consumer'].replace('2026-10-25', '2026-10-26')
    for origin, graph in (('base', b), ('current', c)):
        spec[origin + '_documents_sha256']['consumer'] = digest(graph['documents']['consumer'])
    spec, inputs = authored(b, c, changed, spec=spec,
        select=lambda e, o: e['consumer'] == node_id('consumer', 'specific'))
    result = run(b, c, changed, spec, inputs)
    assert any(r.get('path') == node_id('consumer', 'specific')
               and r.get('reason') == 'causal_no_change_consumer_not_fresh' for r in result['blockers'])
    assert any(r.get('path') == 'tail' for r in result['blockers'])
    assert not result['ok']


def precise_component_pair(*, whole=False, context=False, premise='historical', mutation=None):
    """An exact procedure edit has no claim about an independent old source."""
    b, c, changed = make()
    before = ('# Policy\n\n## Procedure\n\nApply the local review rule.\n\n'
              '## Historical\n\nHistorical observation.\n')
    if premise == 'historical':
        before = before.replace('Historical observation.', 'Historical [observation](required).')
    elif premise == 'procedure':
        before = before.replace('Apply the local review rule.', 'Apply the local [review rule](required).')
    elif premise == 'common':
        before = before.replace('# Policy\n', '# Policy\n\nCommon [premise](required).\n')
    for g in (b, c):
        g['nodes']['required'] = dict(updated_at='2026-01-01', stale_after_days=30)
        g['documents']['required'] = '# Historical source, still stale\n'
        g['documents']['policy'] = before
        line = next(i for i, v in enumerate(before.splitlines(), 1) if '(required)' in v)
        g['edges'].append(dict(source='policy', target='required', type='markdown_link',
            direction='directed', basis='markdown_body', path='policy', field='body', body_line=line))
    c['documents']['policy'] = before.replace('Apply the local', 'Apply the independently approved local')
    if mutation == 'remainder':
        c['documents']['policy'] = c['documents']['policy'].replace('# Policy\n', '# Policy revised\n')
    if mutation == 'references':
        for g in (b, c): g['documents']['policy'] += '\n[guide]: /original\n'
        c['documents']['policy'] = c['documents']['policy'].replace('/original', '/different')
    if mutation == 'order':
        text = c['documents']['policy']; a = sections(text)[1]
        c['documents']['policy'] = '# Policy\n\n' + a['Historical'][2] + '\n' + a['Procedure'][2]
        # Keep the factual occurrence attached to its actual text after reorder.
        c['edges'][-1]['body_line'] = next(i for i,v in enumerate(c['documents']['policy'].splitlines(),1) if '(required)' in v)
    if mutation == 'shape':
        c['documents']['policy'] = c['documents']['policy'].replace('## Historical', '## Archive')
    spec = contract(b, c)
    records = []
    for rid, heading in [('procedure', 'Procedure'), ('historical', 'Historical')]:
        record = dict(id=rid, independent=True, rationale='Complete independent synthetic unit.',
            epistemic_status='decision', recorded_on='2026-10-26',
            context_records=['historical'] if context and rid == 'procedure' else [],
            selectors={o: dict(kind='h2', heading=heading) for o in ('base','current')})
        for o,g in [('base',b),('current',c)]:
            selected_heading = 'Archive' if mutation == 'shape' and o == 'current' and rid == 'historical' else heading
            record['selectors'][o]['heading'] = selected_heading
            record[o+'_sha256'] = digest(sections(g['documents']['policy'])[1][selected_heading][2])
        records.append(record)
    spec['documents'].append(dict(path='policy', records=records))
    spec['document_modes']['policy'] = 'explicit_view_v2'
    if not whole:
        for o,g in [('base',b),('current',c)]:
            edge=next(e for e in g['edges'] if e['source']=='consumer' and e['target']=='policy')
            spec['bindings'].append(dict(origin=o,edge_sha256=edge_digest(edge),consumer_record='document',
                target_record='procedure',consumed_sha256=records[0][o+'_sha256'],
                rationale='This complete consumer duty consumes Procedure, not the independent historical assertion.'))
    return b,c,changed,spec


def authored_precise_pair(**kwargs):
    b,c,changed,spec = precise_component_pair(**kwargs)
    spec,inputs = authored(b,c,changed,spec=spec,
        select=lambda e,o:e['consumer'] in {'policy','consumer'},
        disposition=lambda e:'updated' if e['consumer']=='policy' else 'no_change')
    return b,c,changed,spec,inputs


def test_precise_raw_carrier_preserves_history_without_requesting_its_revalidation():
    b,c,changed,spec,inputs = authored_precise_pair()
    result = run(b,c,changed,spec,inputs)
    assert result['ok']
    assert 'policy' in result['seeds']  # WHOLE downstream identity was retained.
    assert result['causal_review']['precise_representation_carriers'] == ['policy']
    assert any(r['path']=='required' and r['state']=='stale' for r in result['unrelated_debt'])
    assert not any(r['path']=='required' for r in result['included'])


@pytest.mark.parametrize('kwargs', [dict(whole=True),dict(context=True),
    dict(premise='procedure'),dict(premise='common')])
def test_real_factual_demand_still_expands_all_required_components(kwargs):
    b,c,changed,spec,inputs = authored_precise_pair(**kwargs)
    result = run(b,c,changed,spec,inputs)
    assert not result['ok']
    assert any(r['path']=='required' and r['state']=='stale' for r in result['blockers'])
    if kwargs.get('whole'):
        assert result['causal_review']['approved_boundaries']  # no_change is no freshness waiver.


@pytest.mark.parametrize('mutation', ['remainder','references','order'])
def test_uncovered_delta_never_becomes_a_precise_representation_carrier(mutation):
    b,c,changed,spec = precise_component_pair(mutation=mutation)
    pc,pb,_,_ = project_records(c,b,changed,spec)
    assert pc['verified_precise_component_seeds'] == pb['verified_precise_component_seeds'] == {}


def test_exact_h2_rename_preserves_changed_component_and_its_factual_dependencies():
    b, c, changed, spec, inputs = authored_precise_pair(mutation='shape')
    pc, pb, seeds, _ = project_records(c, b, changed, spec, artifact_inputs=inputs)
    assert pc['verified_precise_component_seeds']['policy'] == ['policy::record:historical', 'policy::record:procedure']
    assert pb['verified_record_shapes']['policy::record:historical']['selector']['heading'] == 'Historical'
    assert pc['verified_record_shapes']['policy::record:historical']['selector']['heading'] == 'Archive'
    result = evaluate_impact(pc, pb, seeds, today=TODAY)
    assert not result['ok']
    assert any(r['path'] == 'required' and r['state'] == 'stale' for r in result['blockers'])


def test_authored_marker_cannot_make_uncovered_delta_precise():
    b,c,changed,spec = precise_component_pair(mutation='remainder')
    for graph in (b,c):
        graph['verified_precise_component_seeds'] = {'policy':['policy::record:procedure']}
        graph['nodes']['policy']['verified_precise_component_seeds'] = ['policy::record:procedure']
    pc,pb,_,_ = project_records(c,b,changed,spec)
    assert pc['verified_precise_component_seeds'] == pb['verified_precise_component_seeds'] == {}


@pytest.mark.parametrize('change', ['role-to-fact','role-to-navigation','evidence'])
def test_unchanged_sibling_interpretation_change_preserves_full_raw_demand(change):
    b,c,changed,spec = precise_component_pair()
    inputs = {}
    if change.startswith('role-'):
        edge = next(e for e in c['edges'] if e['source']=='policy' and e['target']=='required')
        spec['bindings'].append(dict(origin='base' if change == 'role-to-fact' else 'current',edge_sha256=edge_digest(edge),
            consumer_record='historical',role='navigation',
            prerequisite_document_sha256=digest(c['documents']['required']),
            rationale='Adversarial reinterpretation of identical historical text.'))
    else:
        data=b'Historical observation evidence.\n'
        for origin in ('base','current'):
            spec['artifacts'].append(dict(origin=origin,id='additional-proof',path='proof.txt',sha256=digest(data.decode())))
            inputs[origin,'additional-proof']=data
        declaration=next(d for d in spec['documents'] if d['path']=='policy')
        next(r for r in declaration['records'] if r['id']=='historical')['current_evidence']=['additional-proof']
    pc,pb,_,_=project_records(c,b,changed,spec,artifact_inputs=inputs)
    assert pc['verified_precise_component_seeds'] == pb['verified_precise_component_seeds'] == {}


@pytest.mark.parametrize('route', ['whole-cycle','second-seed'])
def test_precise_carrier_does_not_clear_cycle_or_independent_cause(route):
    from wiki_core.document_records import node_id
    b,c,changed,spec = precise_component_pair()
    target = 'policy' if route == 'whole-cycle' else 'other'
    for origin,graph in [('base',b),('current',c)]:
        if route == 'second-seed':
            graph['nodes']['other'] = dict(updated_at='2026-10-26',stale_after_days=30)
            graph['documents']['other'] = '# Other independent policy\n' + ('Changed duty.\n' if origin=='current' else '')
        text=graph['documents']['policy'].replace('Historical [observation](required).',
            'Historical [observation](required) and [complete premise]('+target+').')
        graph['documents']['policy']=text
        line=next(i for i,v in enumerate(text.splitlines(),1) if 'complete premise' in v)
        graph['edges'].append(dict(source='policy',target=target,type='markdown_link',
            direction='directed',basis='markdown_body',path='policy',field='body',body_line=line))
        spec[origin+'_documents_sha256']={p:digest(t) for p,t in graph['documents'].items()}
        declaration=next(d for d in spec['documents'] if d['path']=='policy')
        next(r for r in declaration['records'] if r['id']=='historical')[origin+'_sha256']=digest(sections(text)[1]['Historical'][2])
    if route=='second-seed': changed.add('other')
    historical=node_id('policy','historical')
    spec,inputs=authored(b,c,changed,spec=spec,
        select=lambda e,o:e['consumer'] in {'policy','consumer',historical},
        disposition=lambda e:'updated' if e['consumer']=='policy' else 'no_change')
    result=run(b,c,changed,spec,inputs)
    assert result['causal_review']['precise_representation_carriers']==['policy']
    assert any(r['consumer']==historical and r['seed']==target
               for r in result['causal_review']['approved_boundaries'])
    assert any(r['path']=='required' and r['state']=='stale' for r in result['blockers'])
    assert not result['ok']


@pytest.mark.parametrize('kind', ['generation', 'membership'])
def test_selected_envelope_distinguishes_publication_date_from_membership(kind):
    from wiki_core.document_records import node_id
    from wiki_core.document_view_selectors import body_span, frontmatter_span
    b, c, changed, _ = partitioned_repair_pair('explicit_view_v2')
    selector = (dict(kind='markdown_generation_paragraph', container_heading_path=['Consumer'], required_match_count=1,
                     template=dict(prefix='Generated on ', suffix='.', value_format='iso_date'))
                if kind == 'generation' else dict(kind='frontmatter_field', path=['members']))
    slot = dict(id='envelope', rationale='Exact declared synthetic metadata.', context_records=[],
                claim='artifact_publication_date' if kind == 'generation' else 'declared_view_membership',
                value_shape='canonical_iso_date' if kind == 'generation' else 'unique_string_sequence',
                selectors={origin: copy.deepcopy(selector) for origin in ('base', 'current')})
    for origin, graph, date, members in (('base', b, '2026-10-25', 'one'),
                                        ('current', c, '2026-10-26', 'two')):
        text = graph['documents']['consumer']
        text = (text.replace('# Consumer\n', f'# Consumer\n\nGenerated on {date}.\n') if kind == 'generation'
                else text.replace('\n---\n', f'\nmembers:\n  - {members}\n---\n'))
        graph['documents']['consumer'] = text
        if kind == 'generation':
            start, end = body_span(text, selector)
            lines = sections(text)[0].splitlines(keepends=True)
        else:
            start, end = frontmatter_span(text, selector, slot['value_shape'])
            lines = text.splitlines(keepends=True)
        slot[origin + '_sha256'] = digest(''.join(lines[start:end]))
    spec = contract(b, c)
    record = dict(id='specific', independent=True, rationale='Complete separate duty.', epistemic_status='decision',
                  recorded_on='2026-10-26', context_records=[],
                  selectors={o: dict(kind='h2', heading='Specific') for o in ('base', 'current')})
    for origin, graph in (('base', b), ('current', c)):
        record[origin + '_sha256'] = digest(sections(graph['documents']['consumer'])[1]['Specific'][2])
    spec['documents'].append(dict(path='consumer', records=[record], envelope=[slot]))
    spec['document_modes']['consumer'] = 'explicit_view_v2'
    spec, inputs = authored(b, c, changed, spec=spec, disposition='updated',
        select=lambda e, o: e['consumer'] == node_id('consumer', 'envelope'))
    assert spec['causal_review']['dispositions']
    if kind == 'generation':
        with pytest.raises(ValueError, match='affected record'):
            run(b, c, changed, spec, inputs)
    else:
        pc, _, _, _ = project_records(c, b, changed, spec, artifact_inputs=inputs)
        assert pc['verified_causal_review']['dispositions']
