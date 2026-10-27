"""Renamed complete sections retain identity without refreshing their siblings."""
import copy
import json

import pytest

from test_documentary_edits import PATH, SUBJECT, TODAY, prepare, run, seal
from test_document_records import graph
from test_freshness_impact import repo
from wiki_core.causal_review import census
from wiki_core.document_records import digest, node_id, project_records, sections, structured_digest


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
    header = '| Key | Value |\n| --- | --- |\n'
    stable = '| stable | 1 |\n'
    row = '| changed | 7 |\n'
    before = '# Register\n\n' + header + stable + (row if operation == 'remove' else '')
    after = '# Register\n\n' + header + stable + (row if operation == 'add' else '')
    path = page(repo, 'log', stale=True, body=before); base = graph(repo)
    page(repo, 'log', stale=True, body=after); current = graph(repo)
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
    record['current_observation'] = 'unqualified'
    with pytest.raises(ValueError, match='complete independent H2 delta'):
        project_records(current, base, {PATH}, spec)
