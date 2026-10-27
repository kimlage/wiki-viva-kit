"""A reviewed hypothesis remains a hypothesis; retained premises still govern."""
import copy
import json

import pytest

from test_record_observations import prepared
from test_document_records import TODAY, graph
from test_freshness_impact import repo, commit
from wiki_core.config import load_config
from wiki_core.document_records import digest, node_id, project_records, sections, structured_digest
from wiki_core.freshness_impact import evaluate_impact, repository_report
from wiki_core.causal_review import census, pair_digest


PATH = 'memories/log.md'
SUBJECT = node_id(PATH, 'entry-0')


def prepare(repo, *, kind='hypothesis', context=False, whole=False):
    b, c, spec, inputs, proof = prepared(repo, context=context, whole=whole)
    caveat = 'The remaining estimate is uncertain; the proposal is pending; the rule grants no execution authority.\n'
    c['documents'][PATH] += caveat
    spec['current_documents_sha256'][PATH] = proof['document_sha256'] = digest(c['documents'][PATH])
    record = spec['documents'][0]['records'][0]
    record['current_sha256'] = proof['record_sha256'] = digest(sections(c['documents'][PATH])[1]['New record'][2])
    old = c['documents'][PATH].replace('measured value 7', 'expected value 3; not yet measured')
    (repo / PATH).write_text(old)
    b = graph(repo)
    spec['base_documents_sha256'] = {p: digest(t) for p, t in b['documents'].items()}
    record = spec['documents'][0]['records'][0]
    record['base_sha256'] = digest(sections(old)[1]['New record'][2])
    record['epistemic_status'] = kind
    record.pop('current_observation')
    record['current_review'] = 'record-review'
    proof.pop('observed_on')
    proof.update(schema_version='wiki_record_review.v1', reviewed_on=TODAY.isoformat(),
                 base_document_sha256=digest(old), base_record_sha256=record['base_sha256'],
                 base_text=sections(old)[1]['New record'][2],
                 current_text=sections(c['documents'][PATH])[1]['New record'][2],
                 epistemic_status=kind,
                 scope='Complete assertion reviewed against retained measurement; type and authority remain unchanged.')
    if context:
        proof['contexts'] = {'remainder': {o: digest(g['documents'][PATH].replace(
            sections(g['documents'][PATH])[1]['New record'][2], '', 1)) for o, g in (('base', b), ('current', c))}}
    return b, c, spec, inputs, proof


def seal(data):
    b, c, spec, inputs, proof = data
    record = spec['documents'][0]['records'][0]
    proof['declaration_sha256'] = structured_digest({k: v for k, v in record.items() if k != 'current_review'})
    raw = json.dumps(proof, sort_keys=True).encode()
    inputs['current', 'record-review'] = raw
    spec['artifacts'] = [a for a in spec['artifacts'] if a['id'] != 'record-review']
    spec['artifacts'].append(dict(id='record-review', origin='current', path='references/review.json', sha256=digest(raw.decode())))


def project(data, changed=None):
    b, c, spec, inputs, _ = data
    return project_records(c, b, changed or {PATH}, spec, artifact_inputs=inputs)


@pytest.mark.parametrize('kind', ['decision', 'hypothesis', 'proposal'])
def test_full_review_preserves_type_base_siblings_and_page(repo, kind):
    data = prepare(repo, kind=kind); seal(data)
    c, b, changed, _ = project(data)
    result = evaluate_impact(c, b, changed, today=TODAY)
    assert result['ok']
    assert c['verified_record_shapes'][SUBJECT]['epistemic_status'] == kind
    assert c['nodes'][SUBJECT]['updated_at'] == TODAY.isoformat()
    for graph in (c, b):
        assert graph['nodes'][PATH]['updated_at'] == '2026-01-01'
        assert graph['nodes'][node_id(PATH, 'remainder')]['updated_at'] == '2026-01-01'
    assert b['nodes'][SUBJECT]['updated_at'] == '2026-01-01'
    assert 'observed_on' not in c['verified_record_reviews'][SUBJECT]
    assert 'verified_record_observations' not in c
    assert all('authority' not in k for k in c['verified_record_reviews'][SUBJECT])
    assert 'estimate is uncertain; the proposal is pending' in c['documents'][PATH]
    assert c['nodes'][PATH] == b['nodes'][PATH]


@pytest.mark.parametrize('fault', ['base_text', 'current_text', 'base_document', 'base_record', 'type',
    'no_sources', 'source_hash', 'source_bytes', 'self_source', 'context_source', 'context',
    'missing_proof', 'self_review', 'unresolved', 'observed_instead', 'later_than_recording',
    'new_record', 'observation_type', 'both', 'unchanged', 'page_policy', 'mixed_delta'])
def test_review_requires_complete_independent_evidence(repo, fault):
    data = prepare(repo, context=fault in {'context', 'context_source'})
    b, c, spec, inputs, proof = data
    record = spec['documents'][0]['records'][0]
    if fault in {'base_text', 'current_text'}: proof[fault] = 'A partial quote.'
    elif fault == 'base_document': proof['base_document_sha256'] = '0'*64
    elif fault == 'base_record': proof['base_record_sha256'] = '0'*64
    elif fault == 'type': proof['epistemic_status'] = 'decision'
    elif fault == 'no_sources': proof['sources'] = []
    elif fault == 'source_hash': proof['sources'][0]['sha256'] = '0'*64
    elif fault == 'source_bytes': inputs['current', 'measurement'] += b' '
    elif fault in {'self_source', 'context_source'}:
        raw = (c['documents'][PATH] if fault == 'self_source' else
               c['documents'][PATH].replace(proof['current_text'], '', 1)).encode()
        inputs['current', 'measurement'] = raw
        spec['artifacts'][0]['sha256'] = proof['sources'][0]['sha256'] = digest(raw.decode())
    elif fault == 'context': proof['contexts'] = {}
    elif fault == 'self_review': proof['review']['reviewer'] = proof['review']['author']
    elif fault == 'unresolved': proof['review']['unresolved_findings'] = ['Unverified premise']
    elif fault == 'observed_instead': proof['observed_on'] = proof.pop('reviewed_on')
    elif fault == 'later_than_recording': proof['reviewed_on'] = '2026-10-19'
    elif fault == 'new_record':
        b['documents'][PATH] = b['documents'][PATH].replace(proof['base_text'], '', 1)
        spec['base_documents_sha256'][PATH] = digest(b['documents'][PATH]); record['base_sha256'] = None
    elif fault == 'observation_type': record['epistemic_status'] = 'observation'
    elif fault == 'both': record['current_observation'] = 'record-review'
    elif fault == 'unchanged':
        b = copy.deepcopy(c); data = b, c, spec, inputs, proof
        spec['base_documents_sha256'] = copy.deepcopy(spec['current_documents_sha256'])
        record['base_sha256'] = record['current_sha256']
    elif fault == 'page_policy': c['nodes'][PATH]['updated_at'] = TODAY.isoformat()
    elif fault == 'mixed_delta':
        c['documents'][PATH] += '# Outside the reviewed H2\nChanged duty.\n'
        spec['current_documents_sha256'][PATH] = digest(c['documents'][PATH])
    seal(data)
    if fault == 'missing_proof': inputs.pop(('current', 'record-review'))
    with pytest.raises(ValueError): project(data)


@pytest.mark.parametrize('case', ['context', 'whole', 'stale_source', 'future', 'expired'])
def test_current_review_does_not_clear_other_factual_obligations(repo, case):
    data = prepare(repo, context=case == 'context', whole=case == 'whole')
    if case == 'stale_source': data[1]['nodes']['memories/new-source.md']['updated_at'] = '2026-01-01'
    seal(data)
    c, b, changed, _ = project(data)
    import datetime as dt
    today = TODAY + dt.timedelta(days=31 if case == 'expired' else -1 if case == 'future' else 0)
    result = evaluate_impact(c, b, changed, today=today)
    assert not result['ok']
    if case in {'context', 'whole'}:
        assert 'memories/old-source.md' in {r['path'] for r in result['blockers']}


def test_review_is_sealed_in_causal_pair_and_not_replayable(repo):
    data = prepare(repo); seal(data)
    c, b, changed, _ = project(data)
    before = pair_digest(c, b, changed)
    c['verified_record_reviews'][SUBJECT]['receipt_sha256'] = '0'*64
    assert pair_digest(c, b, changed) != before
    c['nodes'][SUBJECT]['updated_at'] = '2026-10-19'
    with pytest.raises(ValueError, match='changed after projection'):
        evaluate_impact(c, b, changed, today=TODAY)


def test_review_binds_native_h2_including_leading_blank_padding(repo):
    data = prepare(repo)
    b, c, spec, inputs, proof = data
    record = spec['documents'][0]['records'][0]
    record['leading_blank_lines'] = 1
    for origin in ('base', 'current'):
        proof[origin + '_text'] = '\n' + proof[origin + '_text']
        record[origin + '_sha256'] = digest(proof[origin + '_text'])
    proof['base_record_sha256'] = record['base_sha256']
    proof['record_sha256'] = record['current_sha256']
    seal(data)
    pc, pb, seeds, _ = project(data)
    assert evaluate_impact(pc, pb, seeds, today=TODAY)['ok']
    proof['current_text'] = proof['current_text'][1:]; seal(data)
    with pytest.raises(ValueError, match='complete BASE and CURRENT'):
        project(data)


@pytest.mark.parametrize('fault', [None, 'omitted_transitive', 'transitive_source_alias'])
def test_transitive_mandatory_context_is_sealed_and_not_source_evidence(repo, fault):
    data = prepare(repo)
    b, c, spec, inputs, proof = data
    text = sections(b['documents'][PATH])[1]['Old record'][2]
    record = spec['documents'][0]['records'][0]
    record['context_records'] = ['premise']
    spec['documents'][0]['records'].append(dict(id='premise', heading='Old record', independent=True,
        rationale='Complete retained context, itself depending on the remaining document.',
        epistemic_status='observation', recorded_on=TODAY.isoformat(), context_records=['remainder'],
        base_sha256=digest(text), current_sha256=digest(text)))
    remainder = {o: g['documents'][PATH].replace(proof[o + '_text'], '', 1).replace(text, '', 1)
                 for o, g in (('base', b), ('current', c))}
    proof['contexts'] = {'premise': {'base': digest(text), 'current': digest(text)},
                         'remainder': {o: digest(t) for o, t in remainder.items()}}
    if fault == 'omitted_transitive': proof['contexts'].pop('remainder')
    if fault == 'transitive_source_alias':
        raw = remainder['current'].encode(); inputs['current', 'measurement'] = raw
        spec['artifacts'][0]['sha256'] = proof['sources'][0]['sha256'] = digest(raw.decode())
    seal(data)
    if fault:
        with pytest.raises(ValueError, match='contexts|circular observation source'): project(data)
    else:
        pc, pb, seeds, _ = project(data)
        result = evaluate_impact(pc, pb, seeds, today=TODAY)
        assert not result['ok']
        assert node_id(PATH, 'premise') in {r['path'] for r in result['blockers']}


def test_another_seed_and_cycle_still_require_their_own_reconciliation(repo):
    data = prepare(repo)
    b, c, spec, inputs, _ = data
    for origin, g in (('base', b), ('current', c)):
        g['documents']['memories/new-source.md'] += '\nDepends on the complete [log](log.md).\n'
        spec[origin + '_documents_sha256']['memories/new-source.md'] = digest(g['documents']['memories/new-source.md'])
        g['edges'].append(dict(source='memories/new-source.md', target=PATH, type='markdown_link',
            direction='directed', basis='markdown_body', path='memories/new-source.md', field='body'))
    c['documents']['memories/new-source.md'] += '\nChanged premise.\n'
    spec['current_documents_sha256']['memories/new-source.md'] = digest(c['documents']['memories/new-source.md'])
    seal(data)
    pc, pb, seeds, _ = project(data, {PATH, 'memories/new-source.md'})
    result = evaluate_impact(pc, pb, seeds, today=TODAY)
    assert not result['ok']
    assert {'memories/new-source.md', SUBJECT} <= set(result['seeds'])
    assert 'memories/old-source.md' in {r['path'] for r in result['blockers']}


def test_bare_declaration_or_frontmatter_cannot_self_certify_review(repo):
    data = prepare(repo)
    b, c, spec, inputs, _ = data
    record = spec['documents'][0]['records'][0]
    record.pop('current_review')
    pc, pb, seeds, _ = project(data)
    assert not evaluate_impact(pc, pb, seeds, today=TODAY)['ok']
    c['nodes'][PATH]['verified_record_reviews'] = {SUBJECT: {'reviewed_on': TODAY.isoformat()}}
    assert not evaluate_impact(c, b, {PATH}, today=TODAY)['ok']


@pytest.mark.parametrize('kind', ['normative_revalidations', 'documentary_edits', 'base_authority_citations'])
@pytest.mark.parametrize('alias', [False, True])
def test_another_qualification_cannot_serve_as_primary_evidence(repo, kind, alias):
    data = prepare(repo)
    b, c, spec, inputs, proof = data
    raw = inputs['current', 'measurement']
    aid = 'another-proof' if alias else 'measurement'
    if alias:
        inputs['current', aid] = raw
        spec['artifacts'].append(dict(id=aid, origin='current', path='references/another-proof.json', sha256=digest(raw.decode())))
    spec['causal_review'] = {kind: [dict(evidence_id=aid)]}
    seal(data)
    # Rejected during qualification, before a malformed later causal plan could
    # accidentally make this test pass for an unrelated schema error.
    with pytest.raises(ValueError, match='circular observation source'):
        project(data)


@pytest.mark.parametrize('disposition', ['updated', 'no_change', 'missing'])
def test_reviewed_changed_consumer_still_needs_actual_causal_disposition(repo, disposition):
    data = prepare(repo)
    b, c, spec, inputs, _ = data
    c['documents']['memories/new-source.md'] += '\nA changed measurement, reflected in the reviewed assertion.\n'
    spec['current_documents_sha256']['memories/new-source.md'] = digest(c['documents']['memories/new-source.md'])
    changed = {PATH, 'memories/new-source.md'}
    seal(data)
    pc, pb, seeds, _ = project(data, changed)
    inventory = census(pc, pb, seeds)
    plan = dict(schema_version='wiki_causal_review.v1', author='writer', pair_sha256=pair_digest(pc, pb, seeds),
        census_sha256=structured_digest(inventory), review_evidence='causal-review', dispositions=[])
    if disposition != 'missing':
        for oid, obligation in inventory['obligations'].items():
            row = inventory['edges'][obligation['edge_id']]
            assert row['consumer'] == SUBJECT
            plan['dispositions'].append(dict(obligation_id=oid, disposition=disposition,
                reason='Complete assertion changed from expectation to measured value against the retained source.'))
    review = dict(schema_version='wiki_causal_review_receipt.v1', author='writer', reviewer='independent-reviewer',
        decision='approved', unresolved_findings=[], plan_sha256=structured_digest({k:v for k,v in plan.items() if k!='review_evidence'}))
    raw = json.dumps(review, sort_keys=True).encode()
    inputs['current', 'causal-review'] = raw
    spec['artifacts'].append(dict(id='causal-review', origin='current', path='references/causal.json', sha256=digest(raw.decode())))
    spec['causal_review'] = plan
    if disposition == 'no_change':
        with pytest.raises(ValueError): project(data, changed)
        return
    pc, pb, seeds, _ = project(data, changed)
    result = evaluate_impact(pc, pb, seeds, today=TODAY)
    assert result['ok'] == (disposition == 'updated')
    if disposition == 'missing': assert any(r['reason'] == 'causal_missing' for r in result['blockers'])


def test_native_report_uses_real_artifacts_and_rejects_later_content(repo):
    data = prepare(repo); seal(data)
    b, c, spec, inputs, _ = data
    for path, text in b['documents'].items(): (repo / path).write_text(text)
    base = commit(repo)
    for path, text in c['documents'].items(): (repo / path).write_text(text)
    for artifact in spec['artifacts']:
        path = repo / artifact['path']; path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(inputs[artifact['origin'], artifact['id']])
    (repo / 'references/records.json').write_text(json.dumps(spec))
    (repo / 'wiki.config.yaml').write_text('audit:\n  freshness_scope: impact\n  freshness_records: references/records.json\n')
    result = repository_report(repo, load_config(repo), base, today=TODAY)
    assert result['ok']
    assert next(r for r in result['included'] if r['path'] == SUBJECT)['state'] == 'fresh'
    (repo / PATH).write_text(c['documents'][PATH] + '\nUnreviewed new assertion.\n')
    with pytest.raises(ValueError, match='snapshot does not match'):
        repository_report(repo, load_config(repo), base, today=TODAY)
