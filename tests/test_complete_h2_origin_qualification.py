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


@pytest.mark.parametrize('mandatory_old_context', [False, True])
def test_current_review_and_historical_edit_share_page_without_refreshing_siblings(repo, mandatory_old_context):
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
    data = base, current, spec, inputs, proof
    seal_view(data)
    pc, pb, result = run(data)
    assert result['ok'] is (not mandatory_old_context)
    assert pc['nodes'][node_id(PATH, 'proposal')]['updated_at'] == TODAY.isoformat()
    assert pc['nodes'][SUBJECT]['updated_at'] == pb['nodes'][SUBJECT]['updated_at'] == '2026-01-01'
    assert pc['nodes'][PATH]['updated_at'] == '2026-01-01'
    if mandatory_old_context:
        assert 'memories/old-source.md' in {r['path'] for r in result['blockers']}
