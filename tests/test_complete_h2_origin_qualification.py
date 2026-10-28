"""Renamed complete sections retain identity without refreshing their siblings."""
import copy
import json

import pytest

from test_documentary_edits import PATH, SUBJECT, TODAY, prepare, retirement, run, seal
from test_document_records import graph
from test_freshness_impact import page, repo
from wiki_core.causal_review import census
from wiki_core.document_records import digest, edge_digest, node_id, project_records, sections, structured_digest


def explicit_h2(data, root, *, rename=True):
    base, current, spec, inputs, proof = data
    old, new = 'Historical record', 'Archived record' if rename else 'Historical record'
    path = root / PATH
    path.write_text(current['documents'][PATH].replace('## ' + old + '\n', '## ' + new + '\n'))
    current = graph(root)
    spec['current_documents_sha256'] = {p: digest(t) for p, t in current['documents'].items()}
    spec['document_modes'][PATH] = 'explicit_view_v2'
    record = spec['documents'][0]['records'][0]
    record.pop('heading')
    record['selectors'] = {'base': {'kind': 'h2', 'heading': old}, 'current': {'kind': 'h2', 'heading': new}}
    proof['current_text'] = sections(current['documents'][PATH])[1][new][2]
    record['current_sha256'] = digest(proof['current_text'])
    proof['current_document_sha256'] = digest(current['documents'][PATH])
    return base, current, spec, inputs, proof


def seal_view(data):
    """Review representation updates, leaving every real arrival blocked."""
    seal(data)
    base, current, spec, inputs, _ = data
    proposal = copy.deepcopy(spec)
    proposal.pop('causal_review')
    pc, pb, changes, _ = project_records(current, base, {PATH}, proposal, artifact_inputs=inputs)
    inventory = census(pc, pb, changes)
    for row in spec['causal_review']['dispositions']:
        edge = inventory['edges'][inventory['obligations'][row['obligation_id']]['edge_id']]
        if (edge['consumer'] == PATH and edge['edge'].get('field') == 'document_components'
                and PATH in pc.get('verified_precise_component_seeds', {})):
            row.update(disposition='updated', reason='Complete document delta consists of the independently reviewed section.')
    receipt = json.loads(inputs['current', 'review'])
    receipt['plan_sha256'] = structured_digest({k: v for k, v in spec['causal_review'].items() if k != 'review_evidence'})
    raw = json.dumps(receipt, sort_keys=True).encode()
    inputs['current', 'review'] = raw
    next(a for a in spec['artifacts'] if a['id'] == 'review')['sha256'] = digest(raw.decode())


def frontier(repo, kind, *, qualified=True, another_seed=False):
    page(repo, 'tail', stale=True, body='Uses the unchanged [decision](consumer.md).')
    data = (retirement(repo, whole=True) if kind == 'retirement'
            else explicit_h2(prepare(repo, correction=True, whole=True), repo, rename=kind == 'rename'))
    base, current, spec, inputs, proof = data
    record = spec['documents'][0]['records'][0]
    # This fixture reviews a historical correction in a currently reviewed
    # page. Keep the same finite freshness policy in both snapshots.
    for graph_data in (base, current):
        for path in (PATH, 'memories/old-source.md'):
            graph_data['documents'][path] = graph_data['documents'][path].replace('2026-01-01', TODAY.isoformat())
            graph_data['nodes'][path]['updated_at'] = TODAY.isoformat()
    if kind in {'literal_removal', 'reclassification', 'duplicate', 'native_navigation', 'native_change_target', 'outside_h2'}:
        original = proof['base_text']
        base['documents'][PATH] = base['documents'][PATH].replace(original,
            original.replace('A quoted quota reference.', 'A quoted [source](old-source.md).'))
        if kind == 'duplicate':
            base['documents'][PATH] = base['documents'][PATH].replace('A quoted [source](old-source.md).',
                'A quoted [source](old-source.md).\nA quoted [source](old-source.md).')
        # Rebuild native occurrences from the actual fixture bytes. Reclassify
        # keeps the literal reference; its role alone changes after projection.
        if kind in {'reclassification', 'duplicate', 'native_navigation', 'native_change_target'}:
            current['documents'][PATH] = current['documents'][PATH].replace('The archived meter value was 2.\n',
                'The archived meter value was 2.\nA quoted [source](old-source.md).\n')
        if kind.startswith('native_'):
            from wiki_core.markdown_link_roles import declare_link_role
            current['documents'][PATH] = current['documents'][PATH].replace('[source](old-source.md)',
                declare_link_role('[source](old-source.md)', kind.removeprefix('native_')))
        if kind == 'outside_h2':
            current['documents'][PATH] = current['documents'][PATH].replace(
                'Compare [terms](old-source.md)', 'Compare terms')
        for origin, graph_data in (('base', base), ('current', current)):
            for path, text in graph_data['documents'].items():
                (repo / path).write_text(text)
            graph_data.update(graph(repo))
        for origin, graph_data in (('base', base), ('current', current)):
            proof[origin + '_text'] = sections(graph_data['documents'][PATH])[1]['Historical record'][2]
            record[origin + '_sha256'] = digest(proof[origin + '_text'])
    for origin, graph_data in (('base', base), ('current', current)):
        spec[origin + '_documents_sha256'] = {p: digest(t) for p, t in graph_data['documents'].items()}
        proof[origin + '_document_sha256'] = digest(graph_data['documents'][PATH])
        if kind != 'retirement':
            edge = next(e for e in graph_data['edges'] if e['source'] == 'memories/consumer.md')
            spec['bindings'].append(dict(origin=origin, edge_sha256=edge_digest(edge), target_record='entry-0',
                consumed_sha256=record[origin + '_sha256'], rationale='This conclusion consumes this complete historical assertion only.'))
    if kind == 'reclassification':
        edge = min((e for e in current['edges'] if e['source'] == PATH and e['target'] == 'memories/old-source.md'),
                   key=lambda e: e['body_line'])
        spec['bindings'].append(dict(origin='current', edge_sha256=edge_digest(edge), consumer_record='entry-0',
            role='navigation', target_document_sha256=digest(current['documents']['memories/old-source.md']),
            rationale='Deliberately invalid attempt to describe role change as physical removal.'))
    if another_seed:
        # A separate new arrival cannot borrow the first seed's repaired path.
        page(repo, 'other', body='New independent [dependency](consumer.md).')
        other = graph(repo)
        for name in ('documents', 'nodes'):
            base[name]['memories/other.md'] = other[name]['memories/other.md']
            current[name]['memories/other.md'] = other[name]['memories/other.md']
        current['documents']['memories/other.md'] += '\nChanged external assertion.\n'
        for origin, graph_data in (('base', base), ('current', current)):
            graph_data['documents']['memories/consumer.md'] += '\nAlso uses [other](other.md).\n'
            for path, text in graph_data['documents'].items():
                (repo / path).write_text(text)
            graph_data.update(graph(repo))
            spec[origin + '_documents_sha256'] = {p: digest(t) for p, t in graph_data['documents'].items()}
    seal(data, retired_owner=True)
    proposal = copy.deepcopy(spec)
    proposal.pop('causal_review')
    changed = {p for p in base['documents'] | current['documents']
               if base['documents'].get(p) != current['documents'].get(p)}
    pc, pb, seeds, _ = project_records(current, base, changed, proposal, artifact_inputs=inputs)
    inventory = census(pc, pb, seeds)
    for item in spec['causal_review']['dispositions']:
        edge = inventory['edges'][inventory['obligations'][item['obligation_id']]['edge_id']]
        if edge['consumer'] == 'memories/consumer.md':
            item.update(disposition='no_change', reason='The independently reviewed historical edit leaves this complete conclusion unchanged.',
                reviewed_upstream_repairs=[PATH if kind == 'retirement' else SUBJECT])
    if not qualified:
        spec['causal_review'].pop('documentary_edits')
    receipt = json.loads(inputs['current', 'review'])
    receipt['plan_sha256'] = structured_digest({k: v for k, v in spec['causal_review'].items() if k != 'review_evidence'})
    raw = json.dumps(receipt, sort_keys=True).encode()
    inputs['current', 'review'] = raw
    next(a for a in spec['artifacts'] if a['id'] == 'review')['sha256'] = digest(raw.decode())
    return data


@pytest.mark.parametrize('kind', ['rename', 'retirement', 'literal_removal'])
def test_reviewed_historical_frontier_reconciles_same_seed_without_altering_graph(repo, kind):
    data = frontier(repo, kind)
    pc, pb, result = run(data)
    assert result['ok'], result['blockers']
    assert any(r['path'] == 'memories/tail.md' for r in result['unrelated_debt'])
    assert not any(r['path'] == 'memories/tail.md' for r in result['included'])
    assert result['causal_review']['approved_boundaries']
    assert pc['documents'] == data[1]['documents'] and pb['documents'] == data[0]['documents']


@pytest.mark.parametrize('kind', ['rename', 'retirement', 'literal_removal', 'reclassification', 'duplicate',
                                  'native_navigation', 'native_change_target'])
def test_frontier_cannot_infer_edit_permission_or_hide_surviving_literal(repo, kind):
    data = frontier(repo, kind, qualified=kind in {'reclassification', 'duplicate', 'native_navigation', 'native_change_target'})
    with pytest.raises(ValueError, match='reviewed upstream repair lacks'):
        run(data)


def test_partition_proof_cannot_supply_a_different_seeds_frontier(repo):
    data = frontier(repo, 'rename', another_seed=True)
    with pytest.raises(ValueError, match='reviewed upstream repair lacks'):
        run(data)


def test_reviewed_h2_removal_cannot_hide_another_relations_loss(repo):
    # The reviewed historical section loses one literal citation. The rule
    # outside that complete section loses a different use of the same target;
    # its obligation cannot borrow the first section's editorial permission.
    with pytest.raises(ValueError):
        run(frontier(repo, 'outside_h2'))


@pytest.mark.parametrize('rename', [False, True])
def test_complete_historical_h2_edit_preserves_actual_origin_selectors(repo, rename):
    data = explicit_h2(prepare(repo, correction=True), repo, rename=rename)
    seal_view(data)
    pc, pb, result = run(data)
    assert result['ok']
    assert pc['nodes'][PATH]['updated_at'] == pb['nodes'][PATH]['updated_at'] == '2026-01-01'
    assert pc['nodes'][SUBJECT]['updated_at'] == '2026-01-01'
    assert 'memories/old-source.md' in {r['path'] for r in result['unrelated_debt']}
    assert pb['verified_record_shapes'][SUBJECT]['selector']['heading'] == 'Historical record'
    assert pc['verified_record_shapes'][SUBJECT]['selector']['heading'] == ('Archived record' if rename else 'Historical record')
    assert next(r for r in result['included'] if r['path'] == PATH)['precise_representation_components'] == [SUBJECT]


@pytest.mark.parametrize('kind', ['whole', 'context', 'cycle', 'another_seed', 'stale_source'])
def test_real_use_of_renamed_h2_still_requires_factual_freshness(repo, kind):
    data = explicit_h2(prepare(repo, correction=True, **{kind: True}), repo)
    seal_view(data)
    _, _, result = run(data)
    assert not result['ok']
    if kind in {'whole', 'cycle', 'another_seed'}:
        assert SUBJECT in result['causal_review']['documentary_edit_factual_demands']
        assert 'precise_representation_components' not in next(r for r in result['included'] if r['path'] == PATH)


@pytest.mark.parametrize('fault', ['remainder', 'references', 'record_order', 'old_receipt', 'partial_selector'])
def test_origin_selection_does_not_hide_mixed_or_stale_proof(repo, fault):
    data = explicit_h2(prepare(repo, correction=True), repo)
    base, current, spec, inputs, proof = data
    record = spec['documents'][0]['records'][0]
    if fault in {'remainder', 'references', 'record_order'}:
        text = current['documents'][PATH]
        if fault == 'remainder': text = text.replace('Compare [terms]', 'Never compare [terms]')
        elif fault == 'references': text += '\n[changed]: old-source.md\n'
        else:
            section = proof['current_text']
            text = text.replace(section, '') + '\n' + section
        (repo / PATH).write_text(text)
        current = graph(repo)
        spec['current_documents_sha256'][PATH] = digest(text)
        proof['current_document_sha256'] = digest(text)
        if fault == 'record_order':
            proof['current_text'] = sections(text)[1]['Archived record'][2]
            record['current_sha256'] = digest(proof['current_text'])
        data = base, current, spec, inputs, proof
    elif fault == 'old_receipt': proof['current_text'] = proof['base_text']
    else: record['selectors']['current']['kind'] = 'markdown_preamble'
    with pytest.raises(ValueError):
        seal_view(data)
        run(data)


def mixed_data(repo, mandatory_old_context=False):
    base, current, spec, inputs, proof = explicit_h2(prepare(repo, correction=True), repo)
    old_assertion = '## Current proposal\n\nTentative plan based on the prior measurement.\n\n'
    new_assertion = '## Current proposal\n\nTentative plan revised against the retained measurement; no execution approved.\n\n'
    for origin, snapshot, text in (('base', base, old_assertion), ('current', current, new_assertion)):
        (repo / PATH).write_text(snapshot['documents'][PATH].replace('## Rule\n', text + '## Rule\n'))
        updated = graph(repo)
        snapshot.clear(); snapshot.update(updated)
        spec[origin + '_documents_sha256'][PATH] = digest(snapshot['documents'][PATH])
        proof[origin + '_document_sha256'] = digest(snapshot['documents'][PATH])
    record = dict(id='proposal', independent=True, rationale='Complete preexisting proposal, not an execution grant.',
        epistemic_status='proposal', recorded_on=TODAY.isoformat(), context_records=['remainder'] if mandatory_old_context else [],
        selectors={o: dict(kind='h2', heading='Current proposal') for o in ('base', 'current')},
        base_sha256=digest(old_assertion), current_sha256=digest(new_assertion),
        current_evidence=['proposal-source'], current_review='proposal-review')
    spec['documents'][0]['records'].append(record)
    source = b'{"measurement":7,"proposal":"tentative revision; no execution authorized"}'
    inputs['current', 'proposal-source'] = source
    spec['artifacts'].append(dict(id='proposal-source', origin='current', path='references/proposal-source.json', sha256=digest(source.decode())))
    contexts = {}
    if mandatory_old_context:
        from wiki_core.document_view_selectors import partition_view
        contexts['remainder'] = {o: partition_view(g['documents'][PATH], spec['documents'][0]['records'], o)['parts']['remainder']['content_sha256']
                                 for o, g in (('base', base), ('current', current))}
    review = dict(schema_version='wiki_record_review.v1', document=PATH, record_id='proposal',
        document_sha256=digest(current['documents'][PATH]), record_sha256=record['current_sha256'],
        declaration_sha256=structured_digest({k: v for k, v in record.items() if k != 'current_review'}),
        reviewed_on=TODAY.isoformat(), base_document_sha256=digest(base['documents'][PATH]),
        base_record_sha256=record['base_sha256'], base_text=old_assertion, current_text=new_assertion,
        epistemic_status='proposal', scope='Complete tentative proposal; historical sibling retains its old cut.', contexts=contexts,
        sources=[dict(id='proposal-source', sha256=digest(source.decode()), purpose='Independent retained measurement and proposal.')],
        review=dict(author='fixture-author', reviewer='fixture-reviewer', decision='approved', unresolved_findings=[]))
    raw = json.dumps(review, sort_keys=True).encode()
    inputs['current', 'proposal-review'] = raw
    spec['artifacts'].append(dict(id='proposal-review', origin='current', path='references/proposal-review.json', sha256=digest(raw.decode())))
    return base, current, spec, inputs, proof


@pytest.mark.parametrize('mandatory_old_context', [False, True])
def test_current_review_and_historical_edit_share_page_without_refreshing_siblings(repo, mandatory_old_context):
    data = mixed_data(repo, mandatory_old_context)
    base, current, spec, inputs, proof = data
    seal_view(data)
    pc, pb, result = run(data)
    assert result['ok'] is (not mandatory_old_context)
    assert pc['nodes'][node_id(PATH, 'proposal')]['updated_at'] == TODAY.isoformat()
    assert pc['nodes'][SUBJECT]['updated_at'] == pb['nodes'][SUBJECT]['updated_at'] == '2026-01-01'
    assert pc['nodes'][PATH]['updated_at'] == '2026-01-01'
    if mandatory_old_context:
        assert 'memories/old-source.md' in {r['path'] for r in result['blockers']}


def composed_data(repo, fault=None):
    """One page: renamed history, two removals, new reading and reviewed proposal."""
    from test_freshness_impact import page
    from wiki_core.document_records import edge_digest
    from wiki_core.document_view_selectors import partition_view
    data = mixed_data(repo, mandatory_old_context=fault == 'context')
    base, current, spec, inputs, proof = data
    records = spec['documents'][0]['records']
    removed = ['## Retired quota\n\nA historical quoted ceiling.\n\n',
               '## Retired reading\n\nAn obsolete repeated reading.\n\n']
    if fault == 'removed_source':
        removed[0] = removed[0].replace('A historical quoted ceiling.', '[Original source](old-source.md).')
    added = '## New measurement\n\nMeasured value 7 from the retained reading.\n\n'
    if fault == 'new_source':
        added = added.replace('from the retained reading.', 'from the retained [reading](live-source.md).')
    if fault in {'whole', 'base_consumer'}:
        page(repo, 'consumer', body='This claim relies on the complete [record](log.md).')
    for origin, snapshot in (('base', base), ('current', current)):
        text = snapshot['documents'][PATH]
        text = text.replace('## Rule\n', (''.join(removed) if origin == 'base' else added) + '## Rule\n')
        if origin == 'base' and fault == 'forged_absence':
            text = text.replace('## Rule\n', added + '## Rule\n')
        if origin == 'current' and fault == 'uncovered':
            text = text.replace('Compare [terms]', 'Ignore [terms]')
        if origin == 'current' and fault == 'base_consumer':
            page(repo, 'consumer', body='Prior citation removed pending separate reconciliation.')
        (repo / PATH).write_text(text)
        updated = graph(repo); snapshot.clear(); snapshot.update(updated)
        spec[origin + '_documents_sha256'] = {p: digest(t) for p, t in snapshot['documents'].items()}
        proof[origin + '_document_sha256'] = digest(text)
    for i, text in enumerate(removed):
        heading = text.splitlines()[0].removeprefix('## ')
        records.append(dict(id='retired-' + str(i), independent=True, rationale='Complete removed historical H2; BASE obligations retained.',
            epistemic_status='observation', recorded_on=TODAY.isoformat(), context_records=[],
            selectors={'base': dict(kind='h2', heading=heading), 'current': None},
            base_sha256=digest(text), current_sha256=None))
    observation = dict(id='new-measurement', independent=True, rationale='New complete bounded reading.',
        epistemic_status='observation', recorded_on=TODAY.isoformat(), context_records=[],
        selectors={'base': None, 'current': dict(kind='h2', heading='New measurement')},
        base_sha256=None, current_sha256=digest(added),
        current_evidence=['proposal-source'], current_observation='new-measurement-proof')
    records.append(observation)
    source = next(a for a in spec['artifacts'] if a['id'] == 'proposal-source')
    receipt = dict(schema_version='wiki_record_observation.v1', document=PATH, record_id=observation['id'],
        document_sha256=digest(current['documents'][PATH]), record_sha256=observation['current_sha256'],
        declaration_sha256=structured_digest({k: v for k, v in observation.items() if k != 'current_observation'}),
        observed_on=TODAY.isoformat(), scope='Only the retained new measurement, not the old sibling or removed claims.',
        contexts={}, sources=[dict(id=source['id'], sha256=source['sha256'], purpose='Independent original retained reading.')],
        review=dict(author='fixture-author', reviewer='fixture-reviewer', decision='approved', unresolved_findings=[]))
    raw = json.dumps(receipt, sort_keys=True).encode(); inputs['current', 'new-measurement-proof'] = raw
    spec['artifacts'].append(dict(id='new-measurement-proof', origin='current', path='references/new-measurement.json', sha256=digest(raw.decode())))
    review = json.loads(inputs['current', 'proposal-review'])
    review['base_document_sha256'] = digest(base['documents'][PATH])
    review['document_sha256'] = digest(current['documents'][PATH])
    if fault == 'context':
        review['contexts']['remainder'] = {o: partition_view(g['documents'][PATH], records, o)['parts']['remainder']['content_sha256']
                                            for o, g in (('base', base), ('current', current))}
    raw = json.dumps(review, sort_keys=True).encode(); inputs['current', 'proposal-review'] = raw
    next(a for a in spec['artifacts'] if a['id'] == 'proposal-review')['sha256'] = digest(raw.decode())
    if fault == 'base_consumer':
        edge = next(e for e in base['edges'] if e['source'] == 'memories/consumer.md' and e['target'] == PATH)
        spec['bindings'].append(dict(origin='base', edge_sha256=edge_digest(edge), consumer_record='document',
            role='consumption', target_record='retired-0', consumed_sha256=digest(removed[0]),
            rationale='This BASE claim consumes the removed historical H2; it needs separate reconciliation.'))
    return data


@pytest.mark.parametrize('operation', ['introduced', 'removed'])
@pytest.mark.parametrize('disposition', ['updated', 'no_change', 'revalidated'])
def test_complete_unit_delta_accepts_reviewed_updated_arrival_without_cutting_its_consumers(repo, operation, disposition):
    """Qualification and causal reconciliation must compose on an exact delta."""
    from test_freshness_impact import page
    from test_documentary_edits import changed_pages
    data = composed_data(repo, 'new_source' if operation == 'introduced' else 'removed_source')
    base, current, spec, inputs, _ = data
    source = 'live-source' if operation == 'introduced' else 'old-source'
    page(repo, source, stale=operation == 'removed', body='The retained source has a substantive correction.')
    current.clear(); current.update(graph(repo))
    spec['current_documents_sha256'] = {p: digest(t) for p, t in current['documents'].items()}
    seal(data)
    bare = copy.deepcopy(spec); bare.pop('causal_review')
    pc, pb, seeds, _ = project_records(current, base, changed_pages(data), bare, artifact_inputs=inputs)
    target = node_id(PATH, 'new-measurement' if operation == 'introduced' else 'retired-0')
    assert (target not in pb['nodes']) if operation == 'introduced' else (target not in pc['nodes'])
    if operation == 'introduced':
        assert target in pc['verified_record_observations']
    inventory = census(pc, pb, seeds)
    selected = []
    for row in spec['causal_review']['dispositions']:
        edge = inventory['edges'][inventory['obligations'][row['obligation_id']]['edge_id']]
        if edge['consumer'] == target:
            selected.append(row['obligation_id'])
            row.update(disposition=disposition, reason='Reviewed complete unit addition or removal; propagate every downstream arrival.')
    assert selected, 'The qualified unit must receive an actual factual arrival.'
    receipt = json.loads(inputs['current', 'review'])
    receipt['plan_sha256'] = structured_digest({k: v for k, v in spec['causal_review'].items() if k != 'review_evidence'})
    raw = json.dumps(receipt, sort_keys=True).encode()
    inputs['current', 'review'] = raw
    next(a for a in spec['artifacts'] if a['id'] == 'review')['sha256'] = digest(raw.decode())
    if disposition != 'updated':
        with pytest.raises(ValueError, match='removed/added consumer'):
            run(data)
        return
    pc, pb, result = run(data)
    assert all(pc['verified_causal_review']['dispositions'][oid]['disposition'] == 'updated' for oid in selected)
    assert not result['ok']  # This review does not reconcile other consumers or stale sources.
    assert not any(row['consumer'] == target for row in result['causal_review']['approved_boundaries'])
    assert any(row['path'] == PATH for row in result['blockers'])
    if operation == 'removed':
        assert any(row['path'] == 'memories/old-source.md' for row in result['blockers'])


@pytest.mark.parametrize('fault', [None, 'context', 'whole', 'removed_source', 'base_consumer'])
def test_complete_h2_composition_preserves_every_real_obligation(repo, fault):
    data = composed_data(repo, fault)
    seal_view(data)
    pc, pb, result = run(data)
    assert result['ok'] is (fault is None)
    new = node_id(PATH, 'new-measurement')
    removed = {node_id(PATH, 'retired-0'), node_id(PATH, 'retired-1')}
    assert new not in pb['nodes'] and pc['nodes'][new]['updated_at'] == TODAY.isoformat()
    assert removed <= set(result['removed_pages'])
    assert {SUBJECT, new, node_id(PATH, 'proposal'), *removed} <= set(result['seeds'])
    assert pc['nodes'][SUBJECT]['updated_at'] == pb['nodes'][SUBJECT]['updated_at'] == '2026-01-01'
    assert pc['nodes'][PATH]['updated_at'] == pb['nodes'][PATH]['updated_at'] == '2026-01-01'
    if fault is None:
        assert set(pc['verified_precise_component_seeds'][PATH]) == {SUBJECT, new, node_id(PATH, 'proposal'), *removed}
        assert next(row for row in result['included'] if row['path'] == PATH)['precise_representation_components']
    if fault in {'context', 'removed_source', 'whole'}:
        assert 'memories/old-source.md' in {row['path'] for row in result['blockers']}
    if fault == 'base_consumer':
        assert any(row['path'] == 'memories/consumer.md' and row['seed'] in removed
                   for row in result['causal_review']['unresolved'])


@pytest.mark.parametrize('fault', ['uncovered', 'forged_absence'])
def test_composition_rejects_uncovered_bytes_or_forged_absence(repo, fault):
    with pytest.raises(ValueError):
        data = composed_data(repo, fault)
        seal_view(data)
        run(data)


@pytest.mark.parametrize('operation', ['add', 'remove'])
def test_valid_partial_addition_or_removal_does_not_gain_h2_carrier(repo, operation):
    from test_freshness_impact import page
    from test_causal_review import authored
    header = '| Key | Value |\n| --- | --- |\n'
    stable = '| stable | 1 |\n'
    row = '| changed | 7 |\n'
    before = '# Register\n\n' + header + stable + (row if operation == 'remove' else '')
    after = '# Register\n\n' + header + stable + (row if operation == 'add' else '')
    page(repo, 'source', body='Original premise.')
    path = page(repo, 'log', stale=True, body=before, source_refs=['memories/source.md']); base = graph(repo)
    page(repo, 'log', stale=True, body=after, source_refs=['memories/source.md'])
    page(repo, 'source', body='Corrected premise.'); current = graph(repo)
    selector = dict(kind='table_row', container_heading_path=['Register'], header_sha256=digest(header),
                    key_column=0, key=dict(kind='text', value='changed'), required_match_count=1)
    record = dict(id='partial', independent=True, rationale='Valid exact table row, not a complete H2.',
        epistemic_status='observation', recorded_on=TODAY.isoformat(), context_records=[],
        selectors={'base': selector if operation == 'remove' else None,
                   'current': selector if operation == 'add' else None},
        base_sha256=digest(row) if operation == 'remove' else None,
        current_sha256=digest(row) if operation == 'add' else None)
    spec = dict(schema_version='document_record.v2', document_modes={PATH: 'explicit_view_v2'},
        base_documents_sha256={p: digest(t) for p, t in base['documents'].items()},
        current_documents_sha256={p: digest(t) for p, t in current['documents'].items()},
        documents=[dict(path=PATH, records=[record])], bindings=[], artifacts=[])
    pc, pb, seeds, evidence = project_records(current, base, {PATH}, spec)
    assert evidence[0]['complete_delta_covered'] and evidence[0]['precise_component_seeds']
    assert node_id(PATH, 'partial') in seeds
    assert PATH not in pc['verified_precise_component_seeds']
    causal, inputs = authored(base, current, {PATH, 'memories/source.md'}, spec=spec,
        select=lambda edge, obligation: edge['consumer'] == node_id(PATH, 'partial'), disposition='updated')
    assert causal['causal_review']['dispositions']
    with pytest.raises(ValueError, match='removed/added consumer'):
        project_records(current, base, {PATH, 'memories/source.md'}, causal, artifact_inputs=inputs)
    record['current_observation'] = 'unqualified'
    with pytest.raises(ValueError, match='complete independent H2 delta'):
        project_records(current, base, {PATH}, spec)


@pytest.mark.parametrize('upstream_change', ['reference', 'cycle'])
def test_local_receipts_do_not_require_or_grant_a_document_carrier(repo, upstream_change):
    """A complete reading can be qualified while its page still fails admission."""
    from test_freshness_impact import page
    data = composed_data(repo)
    base, current, spec, inputs, _ = data
    target = 'live-source.md' if upstream_change == 'reference' else 'log.md'
    page(repo, 'old-source', stale=True, body=f'A changed prerequisite consumes [evidence]({target}).')
    updated = graph(repo)
    current.clear(); current.update(updated)
    spec['current_documents_sha256'] = {p: digest(t) for p, t in current['documents'].items()}
    seal(data)
    pc, pb, result = run(data)
    assert node_id(PATH, 'new-measurement') in pc['verified_record_observations']
    assert node_id(PATH, 'proposal') in pc['verified_record_reviews']
    assert pc['nodes'][node_id(PATH, 'new-measurement')]['updated_at'] == TODAY.isoformat()
    assert pc['nodes'][node_id(PATH, 'proposal')]['updated_at'] == TODAY.isoformat()
    assert PATH not in pc['verified_precise_component_seeds']
    assert {PATH, 'memories/old-source.md', node_id(PATH, 'retired-0'),
            node_id(PATH, 'retired-1')} <= set(result['seeds'])
    for node in (PATH, SUBJECT, node_id(PATH, 'remainder')):
        assert pc['nodes'][node]['updated_at'] == pb['nodes'][node]['updated_at'] == '2026-01-01'
    assert not result['ok']
    assert {PATH, 'memories/old-source.md'} <= {r['path'] for r in result['blockers']}
    assert 'precise_representation_components' not in next(r for r in result['included'] if r['path'] == PATH)
    assert SUBJECT in pc['verified_causal_review']['documentary_edits']
    assert SUBJECT in result['causal_review']['documentary_edit_factual_demands']
    assert SUBJECT not in result['causal_review']['documentary_edits_satisfied']
