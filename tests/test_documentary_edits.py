"""Synthetic edit permission is separate from factual freshness and use."""
import copy
import datetime as dt
import json

import pytest

from test_document_records import declaration, graph
from test_freshness_impact import page, repo, commit
from wiki_core.causal_review import census, pair_digest
from wiki_core.document_records import digest, node_id, project_records, sections, structured_digest
from wiki_core.freshness_impact import evaluate_impact
from wiki_core.config import load_config
from wiki_core.freshness_impact import repository_report


TODAY = dt.date(2026, 10, 18)
PATH = 'memories/log.md'
SUBJECT = node_id(PATH, 'entry-0')


def prepare(repo, *, correction=False, whole=False, context=False, stale_source=False,
            cycle=False, another_seed=False):
    page(repo, 'old-source', stale=True)
    page(repo, 'live-source', stale=stale_source)
    source_link = '[Source](live-source.md).\n' if stale_source else ''
    if cycle:
        source_link += 'See [consumer](consumer.md).\n'
    old = ('# Notes\n\n## Historical record\n\nThe archived meter value was 0.\n'
           'A quoted quota reference.\n' + source_link +
           '\n## Rule\n\nCompare [terms](old-source.md) before claiming payment.\n')
    p = page(repo, 'log', stale=True, body=old)
    if whole or cycle or another_seed:
        page(repo, 'consumer', body='The current decision requires the complete [notes](log.md).')
    base = graph(repo)
    text = p.read_text()
    text = text.replace('value was 0', 'value was 2') if correction else text.replace('A quoted quota reference.\n', '')
    p.write_text(text)
    if another_seed:
        consumer = repo / 'memories/consumer.md'
        consumer.write_text(consumer.read_text().replace('current decision', 'revised decision'))
    current = graph(repo)
    spec = declaration(base, current, headings=('Historical record',))
    spec.update(schema_version='document_record.v2', document_modes={PATH: 'h2_v1'}, artifacts=[])
    record = spec['documents'][0]['records'][0]
    record['current_evidence'] = ['source']
    if context:
        record['context_records'] = ['remainder']
    source = b'{"historical_cut":"2026-01-01","original_value":2,"owner_instruction":"remove the quoted quota reference"}'
    inputs = {('current', 'source'): source}
    spec['artifacts'] = [dict(id='source', origin='current', path='references/source.json', sha256=digest(source.decode()))]
    proof = dict(schema_version='wiki_documentary_edit.v1', subject=SUBJECT,
        base_text=sections(base['documents'][PATH])[1]['Historical record'][2],
        current_text=sections(current['documents'][PATH])[1]['Historical record'][2],
        base_document_sha256=digest(base['documents'][PATH]), current_document_sha256=digest(current['documents'][PATH]),
        edit_kind='historical_correction' if correction else 'authorized_removal',
        historical_as_of='2026-01-01', reviewed_on=TODAY.isoformat(),
        scope='Only the historical assertion or its quoted reference. No present service, payment or rule is certified.',
        sources=[dict(id='source', sha256=digest(source.decode()), purpose='Retained original assertion and owner removal instruction.')])
    return base, current, spec, inputs, proof


def seal(data, *, omit_dispositions=False, changed=None, retired_owner=False):
    base, current, spec, inputs, proof = data
    record = spec['documents'][0]['records'][0]
    # Reconstruct graph identities before sealing the complete causal pair.
    spec.pop('causal_review', None)
    spec['artifacts'] = [a for a in spec['artifacts'] if a['id'] not in {'edit-proof', 'review'}]
    pc, pb, seeds, _ = project_records(current, base, changed_pages(data) if changed is None else changed,
                                      spec, artifact_inputs=inputs)
    inventory = census(pc, pb, seeds)
    proof.setdefault('declaration_sha256', structured_digest(record))
    proof.setdefault('contexts', {node_id(PATH, r): {o: g['nodes'][node_id(PATH, r)]['record_sha256']
        for o, g in (('base', pb), ('current', pc))} for r in record['context_records']})
    raw = json.dumps(proof, sort_keys=True).encode()
    inputs['current', 'edit-proof'] = raw
    spec['artifacts'].append(dict(id='edit-proof', origin='current', path='references/edit.json', sha256=digest(raw.decode())))
    # WHOLE needs its own causal assessment. A blocked disposition deliberately
    # remains unresolved; a documentary edit must never clear it.
    plan = dict(schema_version='wiki_causal_review.v1', author='fixture-author',
        pair_sha256=pair_digest(pc, pb, seeds), census_sha256=structured_digest(inventory),
        dispositions=[] if omit_dispositions else [dict(obligation_id=k,
            disposition='updated' if retired_owner and inventory['edges'][v['edge_id']]['consumer'] == PATH else 'blocked',
            reason='Complete owner reflects the reviewed removal; other current factual uses remain unresolved.')
            for k, v in inventory['obligations'].items()], review_evidence='review',
        documentary_edits=[dict(subject=SUBJECT, evidence_id='edit-proof', evidence_sha256=digest(raw.decode()),
            reason='Independently reviewed historical documentary edit, not freshness.')])
    spec['causal_review'] = plan
    review = dict(schema_version='wiki_causal_review_receipt.v1', author='fixture-author', reviewer='fixture-reviewer',
        decision='approved', plan_sha256=structured_digest({k:v for k,v in plan.items() if k!='review_evidence'}), unresolved_findings=[])
    raw = json.dumps(review, sort_keys=True).encode()
    inputs['current', 'review'] = raw
    spec['artifacts'].append(dict(id='review', origin='current', path='references/review.json', sha256=digest(raw.decode())))


def changed_pages(data):
    base, current, *_ = data
    return {p for p in base['documents'] | current['documents']
            if base['documents'].get(p) != current['documents'].get(p)}


def run(data, *, today=TODAY):
    b, c, spec, inputs, _ = data
    pc, pb, seeds, _ = project_records(c, b, changed_pages(data), spec, artifact_inputs=inputs)
    return pc, pb, evaluate_impact(pc, pb, seeds, today=today)


def retirement(repo, **kwargs):
    base, _, spec, inputs, proof = prepare(repo, **kwargs)
    # The surviving page keeps its original metadata and unrelated rule. The
    # removed record has no fabricated empty CURRENT selection or fresh date.
    (repo / PATH).write_text(base['documents'][PATH].replace(proof['base_text'], '', 1))
    current = graph(repo)
    spec['document_modes'][PATH] = 'explicit_view_v2'
    record = spec['documents'][0]['records'][0]
    record['selectors'] = {'base': dict(kind='h2', heading=record.pop('heading')), 'current': None}
    record['current_sha256'] = None
    spec['current_documents_sha256'] = {p: digest(t) for p, t in current['documents'].items()}
    proof.update(current_text='', current_document_sha256=digest(current['documents'][PATH]),
                 scope='Retire the complete obsolete historical observation; preserve the original source and all current obligations.')
    source = json.loads(inputs['current', 'source'])
    source['owner_instruction'] = 'Retire the complete Historical record section as obsolete; preserve the original evidence.'
    inputs['current', 'source'] = json.dumps(source, sort_keys=True).encode()
    source_hash = digest(inputs['current', 'source'].decode())
    spec['artifacts'][0]['sha256'] = proof['sources'][0]['sha256'] = source_hash
    return base, current, spec, inputs, proof


def test_complete_retirement_retains_current_evidence_without_freshening_history(repo):
    data = retirement(repo)
    seal(data, retired_owner=True)
    pc, pb, result = run(data)
    proof = pc['verified_causal_review']['documentary_edits'][SUBJECT]
    assert proof['retired'] and proof['historical_as_of'] == '2026-01-01'
    assert SUBJECT not in pc['nodes'] and SUBJECT in pb['nodes']
    assert pc['nodes'][PATH]['updated_at'] == pb['nodes'][PATH]['updated_at'] == '2026-01-01'
    source = 'evidence::source:' + data[4]['sources'][0]['sha256']
    assert any(r['path'] == source and r['reason'] == 'required_dependency' for r in result['included'])
    assert any(e['target'] == source and e.get('field') == 'removed_record_evidence' for e in pc['edges'])
    assert not any(e.get('field') == 'removed_record_evidence' for e in pb['edges'])
    assert result['ok'], result['blockers']


@pytest.mark.parametrize('kind', ['whole', 'context', 'stale_source', 'another_seed', 'cycle'])
def test_retirement_does_not_clear_real_factual_obligations(repo, kind):
    data = retirement(repo, **{kind: True})
    seal(data, retired_owner=True)
    pc, pb, result = run(data)
    assert not result['ok']
    if kind in {'whole', 'another_seed', 'cycle'}:
        assert any(r['path'] == 'memories/consumer.md' for r in result['blockers'])
    if kind in {'whole', 'context'}:
        assert any(r['path'] == 'memories/old-source.md' for r in result['blockers']), result['blockers']
    if kind == 'stale_source':
        assert any(r['path'] == 'memories/live-source.md' for r in result['blockers'])
    assert SUBJECT not in pc['nodes'] and SUBJECT in pb['nodes']


def test_retirement_future_review_cannot_be_used_early(repo):
    data = retirement(repo)
    seal(data, retired_owner=True)
    _, _, result = run(data, today=TODAY - dt.timedelta(days=1))
    assert not result['ok']
    assert any(r['path'] == SUBJECT and r['reason'] == 'documentary_review_in_future' for r in result['blockers'])


@pytest.mark.parametrize('fault', ['decision', 'partial_text', 'uncovered', 'source_bytes',
                                  'reused_proof', 'context_changed', 'fresh_date', 'missing_evidence'])
def test_retirement_requires_complete_current_review_of_exact_historical_unit(repo, fault):
    data = retirement(repo, context=fault == 'context_changed')
    b, c, spec, inputs, proof = data
    record = spec['documents'][0]['records'][0]
    if fault == 'decision': record['epistemic_status'] = 'decision'
    elif fault == 'partial_text': proof['base_text'] = 'The archived meter value was 0.\n'
    elif fault == 'missing_evidence': record['current_evidence'] = []
    elif fault in {'uncovered', 'context_changed', 'fresh_date'}:
        p = repo / PATH
        text = p.read_text()
        text = text.replace('2026-01-01', '2026-10-18') if fault == 'fresh_date' else text.replace('Compare', 'Skip')
        p.write_text(text)
        c = graph(repo)
        data = b, c, spec, inputs, proof
        spec['current_documents_sha256'][PATH] = proof['current_document_sha256'] = digest(c['documents'][PATH])
    seal(data, retired_owner=True)
    if fault == 'source_bytes': inputs['current', 'source'] += b' '
    elif fault == 'reused_proof': c['documents'][PATH] += '\nNew unreviewed assertion.\n'
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize('correction', [False, True])
def test_documentary_edit_does_not_claim_freshness(repo, correction):
    data = prepare(repo, correction=correction)
    b,c,spec,inputs,_ = data
    pc,pb,seeds,_ = project_records(c,b,{PATH},spec,artifact_inputs=inputs)
    assert not evaluate_impact(pc,pb,seeds,today=TODAY)['ok']
    seal(data)
    pc,pb,result = run(data)
    assert result['ok']
    row = next(r for r in result['included'] if r['path']==SUBJECT)
    assert row['state']=='stale' and row['documentary_edit_satisfied']
    assert pc['nodes'][SUBJECT]['updated_at']==pb['nodes'][SUBJECT]['updated_at']=='2026-01-01'
    assert 'memories/old-source.md' in {r['path'] for r in result['unrelated_debt']}


@pytest.mark.parametrize('kind', ['whole', 'context', 'stale_source', 'future_review', 'missing_disposition'])
def test_real_factual_obligations_dominate_documentary_edit(repo, kind):
    data = prepare(repo, whole=kind in {'whole','missing_disposition'}, context=kind=='context', stale_source=kind=='stale_source')
    seal(data,omit_dispositions=kind=='missing_disposition')
    _,_,result = run(data,today=TODAY-dt.timedelta(days=1) if kind=='future_review' else TODAY)
    assert not result['ok']
    if kind=='whole':
        assert SUBJECT in result['causal_review']['documentary_edit_factual_demands']
        assert SUBJECT not in result['causal_review']['documentary_edits_satisfied']
    if kind=='missing_disposition':
        assert any(r['reason']=='causal_missing' for r in result['blockers'])
    if kind in {'whole','context'}:
        assert 'memories/old-source.md' in {r['path'] for r in result['blockers']}


@pytest.mark.parametrize('kind', ['cycle', 'another_seed'])
def test_a_later_factual_arrival_cannot_borrow_edit_satisfaction(repo, kind):
    data = prepare(repo, **{kind: True})
    seal(data)
    _, _, result = run(data)
    assert not result['ok']
    assert SUBJECT in result['causal_review']['documentary_edit_factual_demands']
    assert SUBJECT not in result['causal_review']['documentary_edits_satisfied']
    assert any(r['path'] == SUBJECT and r['state'] == 'stale' for r in result['blockers'])
    if kind == 'another_seed':
        assert 'memories/consumer.md' in result['seeds']


@pytest.mark.parametrize('fault', ['empty_sources','self_source','context_source','wrong_source_hash','wrong_snapshot','partial_text',
    'declaration','context','removal_inserts','normative','unknown_kind','future_cut','policy','unchanged'])
def test_documentary_proof_rejects_incomplete_or_expanded_claims(repo, fault):
    data = prepare(repo, correction=fault=='removal_inserts', context=fault in {'context','context_source'})
    b,c,spec,inputs,proof = data
    record = spec['documents'][0]['records'][0]
    if fault=='empty_sources': proof['sources']=[]
    elif fault=='self_source':
        raw = b['documents'][PATH].encode();inputs['current','source']=raw
        spec['artifacts'][0]['sha256']=proof['sources'][0]['sha256']=digest(raw.decode())
    elif fault=='context_source':
        pc, _, _, _ = project_records(c, b, {PATH}, spec, artifact_inputs=inputs)
        raw = c['documents'][PATH].replace(proof['current_text'], '', 1).encode()
        assert digest(raw.decode()) == pc['nodes'][node_id(PATH, 'remainder')]['record_sha256']
        inputs['current','source'] = raw
        spec['artifacts'][0]['sha256']=proof['sources'][0]['sha256']=digest(raw.decode())
    elif fault=='wrong_source_hash': proof['sources'][0]['sha256']='0'*64
    elif fault=='wrong_snapshot': proof['current_document_sha256']='0'*64
    elif fault=='partial_text': proof['current_text']='The archived meter value was 0.\n'
    elif fault=='declaration': proof['declaration_sha256']='0'*64
    elif fault=='context': proof['contexts']={}
    elif fault=='removal_inserts': proof['edit_kind']='authorized_removal'
    elif fault=='normative': record['epistemic_status']='decision'
    elif fault=='unknown_kind': proof['edit_kind']='allow_stale'
    elif fault=='future_cut': proof['historical_as_of']='2026-10-18'
    elif fault=='policy': c['nodes'][PATH]['updated_at']='2026-10-18'
    elif fault=='unchanged':
        b=copy.deepcopy(c);data=b,c,spec,inputs,proof
        spec['base_documents_sha256']=copy.deepcopy(spec['current_documents_sha256'])
        record['base_sha256']=record['current_sha256'];proof['base_text']=proof['current_text']
        proof['base_document_sha256']=proof['current_document_sha256']
    seal(data)
    with pytest.raises(ValueError): run(data)


@pytest.mark.parametrize('fault', ['source_bytes','proof_bytes','review_bytes','pair','no_review',
                                  'self_review', 'unresolved_review'])
def test_documentary_proof_cannot_be_replayed(repo,fault):
    data=prepare(repo);seal(data)
    _,c,spec,inputs,_=data
    if fault=='source_bytes': inputs['current','source']+=b' '
    elif fault=='proof_bytes': inputs['current','edit-proof']+=b' '
    elif fault=='review_bytes': inputs['current','review']+=b' '
    elif fault=='pair': c['documents'][PATH]+='\nAdditional current assertion.\n'
    elif fault=='no_review': inputs.pop(('current','review'))
    elif fault in {'self_review', 'unresolved_review'}:
        receipt = json.loads(inputs['current','review'])
        if fault == 'self_review': receipt['reviewer'] = receipt['author']
        else: receipt['unresolved_findings'] = ['Meaning of the deletion was not checked.']
        inputs['current','review'] = json.dumps(receipt, sort_keys=True).encode()
        next(a for a in spec['artifacts'] if a['id']=='review')['sha256'] = digest(inputs['current','review'].decode())
    with pytest.raises(ValueError): run(data)


@pytest.mark.parametrize('complete_retirement', [False, True])
def test_native_git_report_reads_sealed_artifacts_and_rejects_later_edit(repo, complete_retirement):
    from scripts.wiki_page_graph import collect_git_changes
    data = retirement(repo) if complete_retirement else prepare(repo)
    base, current, spec, inputs, _ = data
    for path, text in base['documents'].items():
        (repo / path).write_text(text)
    base_sha = commit(repo)
    for path, text in current['documents'].items():
        (repo / path).write_text(text)
    (repo / 'references').mkdir()
    for name in ('source', 'edit', 'review', 'records'):
        (repo / f'references/{name}.json').write_text('{}')
    (repo / 'wiki.config.yaml').write_text(
        'audit:\n  freshness_scope: impact\n  freshness_records: references/records.json\n')
    seal(data, changed=set(collect_git_changes(base_sha, root=repo).paths), retired_owner=complete_retirement)
    for artifact in spec['artifacts']:
        path = repo / artifact['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(inputs[artifact['origin'], artifact['id']])
    (repo / 'references/records.json').write_text(json.dumps(spec))
    result = repository_report(repo, load_config(repo), base_sha, today=TODAY)
    assert result['ok'] and result['base_sha'] == base_sha
    assert result['causal_review']['documentary_edits_satisfied'] == ([] if complete_retirement else [SUBJECT])
    assert next(r for r in result['included'] if r['path']==SUBJECT)['state'] == ('removed' if complete_retirement else 'stale')
    (repo / PATH).write_text(current['documents'][PATH] + '\nA later unreviewed assertion.\n')
    with pytest.raises(ValueError, match='snapshot does not match'):
        repository_report(repo, load_config(repo), base_sha, today=TODAY)
