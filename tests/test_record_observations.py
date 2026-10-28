"""Bounded observations retain expired siblings and real factual dependencies."""
import copy
import datetime as dt
import json

import pytest

from test_document_records import declaration, graph, TODAY
from test_freshness_impact import page, repo
from wiki_core.document_records import digest, node_id, project_records, structured_digest
from wiki_core.freshness_impact import evaluate_impact


def prepared(repo, *, context=False, whole=False, mode='h2_v1'):
    page(repo, 'old-source', stale=True)
    page(repo, 'new-source')
    p = page(repo, 'log', stale=True, body='# Log\n\n## Old record\n\n[Old](old-source.md).\n\n')
    if whole:
        page(repo, 'consumer', body='The complete result requires [log](log.md).')
    base = graph(repo)
    p.write_text(p.read_text() + '## New record\n\n[New reading](new-source.md): measured value 7.\n')
    current = graph(repo)
    contract = declaration(base, current)
    contract.update(schema_version='document_record.v2', document_modes={'memories/log.md': 'h2_v1'})
    record = contract['documents'][0]['records'][0]
    if mode == 'explicit_view_v2':
        record.pop('heading')
        record['selectors'] = {'base': None, 'current': {'kind': 'h2', 'heading': 'New record'}}
        contract['document_modes']['memories/log.md'] = mode
    else:
        assert mode == 'h2_v1'
    record['current_evidence'] = ['measurement']
    record['current_observation'] = 'observation-review'
    if context:
        record['context_records'] = ['remainder']
    source = b'{"measurement":7,"observed_on":"2026-10-18"}'
    receipt = dict(schema_version='wiki_record_observation.v1', document='memories/log.md', record_id='entry-0',
        document_sha256=digest(current['documents']['memories/log.md']), record_sha256=record['current_sha256'],
        observed_on=TODAY.isoformat(), scope='Only the new measured value; old contractual terms remain unverified.',
        contexts={'remainder': digest(base['documents']['memories/log.md'])} if context else {},
        sources=[dict(id='measurement', sha256=digest(source.decode()), purpose='Original retained measurement.')],
        review=dict(author='writer', reviewer='independent-reviewer', decision='approved', unresolved_findings=[]))
    inputs = {('current', 'measurement'): source}
    contract['artifacts'] = [dict(id='measurement', origin='current', path='references/measurement.json', sha256=digest(source.decode()))]
    return base, current, contract, inputs, receipt


def seal(contract, inputs, receipt):
    record = contract['documents'][0]['records'][0]
    receipt['declaration_sha256'] = structured_digest({k: v for k, v in record.items() if k != 'current_observation'})
    raw = json.dumps(receipt, sort_keys=True).encode()
    inputs['current', 'observation-review'] = raw
    contract['artifacts'] = [a for a in contract['artifacts'] if a['id'] != 'observation-review']
    contract['artifacts'].append(dict(id='observation-review', origin='current', path='references/review.json', sha256=digest(raw.decode())))


def run(prepared, today=TODAY):
    b, c, contract, inputs, receipt = prepared
    seal(contract, inputs, receipt)
    c, b, seeds, _ = project_records(c, b, {'memories/log.md'}, contract, artifact_inputs=inputs)
    return c, b, evaluate_impact(c, b, seeds, today=today)


def test_reviewed_observation_has_own_date_without_renewing_page(repo):
    c, b, result = run(prepared(repo))
    assert result['ok']
    record = node_id('memories/log.md', 'entry-0')
    assert result['seeds'] == [record]
    assert c['nodes'][record]['updated_at'] == TODAY.isoformat()
    assert c['nodes']['memories/log.md']['updated_at'] == b['nodes']['memories/log.md']['updated_at'] == '2026-01-01'
    assert c['nodes'][node_id('memories/log.md', 'remainder')]['updated_at'] == '2026-01-01'
    assert 'memories/old-source.md' in {r['path'] for r in result['unrelated_debt']}


@pytest.mark.parametrize('kind', ['context', 'whole', 'stale_source', 'mixed_delta', 'expired', 'future'])
@pytest.mark.parametrize('mode', ['h2_v1', 'explicit_view_v2'])
def test_observation_never_clears_other_factual_obligations(repo, kind, mode):
    data = prepared(repo, context=kind == 'context', whole=kind == 'whole', mode=mode)
    b, c, contract, inputs, receipt = data
    if kind == 'stale_source':
        c['nodes']['memories/new-source.md']['updated_at'] = '2026-01-01'
    if kind == 'mixed_delta':
        c['documents']['memories/log.md'] += '# Uncovered assertion\nAdditional changed assertion.\n'
        contract['current_documents_sha256']['memories/log.md'] = digest(c['documents']['memories/log.md'])
        receipt['document_sha256'] = contract['current_documents_sha256']['memories/log.md']
        with pytest.raises(ValueError, match='complete independent H2 delta'):
            run(data)
        return
    today = TODAY + dt.timedelta(days=31) if kind == 'expired' else TODAY - dt.timedelta(days=1) if kind == 'future' else TODAY
    _, _, result = run(data, today=today)
    assert not result['ok']
    if kind in {'context', 'whole'}:
        assert 'memories/old-source.md' in {r['path'] for r in result['blockers']}
    if kind == 'future':
        assert next(r for r in result['blockers'] if r['path'].endswith('::record:entry-0'))['state'] == 'unknown'


@pytest.mark.parametrize('fault', ['no_receipt', 'record_hash', 'document_hash', 'source_hash', 'empty_sources', 'missing_source',
    'context_omitted', 'self_review', 'unresolved_review', 'future_recording', 'wrong_record', 'normative', 'v1', 'unchanged', 'policy', 'unknown_window'])
@pytest.mark.parametrize('mode', ['h2_v1', 'explicit_view_v2'])
def test_observation_fails_closed(repo, fault, mode):
    data = prepared(repo, context=fault == 'context_omitted', mode=mode)
    b, c, contract, inputs, receipt = data
    record = contract['documents'][0]['records'][0]
    if fault == 'no_receipt': record['current_observation'] = 'absent'
    elif fault == 'record_hash': receipt['record_sha256'] = '0' * 64
    elif fault == 'document_hash': receipt['document_sha256'] = '0' * 64
    elif fault == 'source_hash': receipt['sources'][0]['sha256'] = '0' * 64
    elif fault == 'empty_sources': receipt['sources'] = []
    elif fault == 'missing_source': record['current_evidence'] = []
    elif fault == 'context_omitted': receipt['contexts'] = {}
    elif fault == 'self_review': receipt['review']['reviewer'] = 'writer'
    elif fault == 'unresolved_review': receipt['review']['unresolved_findings'] = ['not reviewed']
    elif fault == 'future_recording': receipt['observed_on'] = '2026-10-19'
    elif fault == 'wrong_record': receipt['record_id'] = 'remainder'
    elif fault == 'normative': record['epistemic_status'] = 'decision'
    elif fault == 'v1':
        contract['schema_version'] = 'document_record.v1'
        if 'selectors' in record:
            selector = record.pop('selectors')['current']
            record['heading'] = selector['heading']
            if 'leading_blank_lines' in selector:
                record['leading_blank_lines'] = selector['leading_blank_lines']
    elif fault == 'unchanged':
        b = copy.deepcopy(c); data = b, c, contract, inputs, receipt
        contract['base_documents_sha256'] = copy.deepcopy(contract['current_documents_sha256'])
        record['base_sha256'] = record['current_sha256']
    elif fault == 'policy': c['nodes']['memories/log.md']['stale_after_days'] = 365
    elif fault == 'unknown_window':
        for g in (b, c): g['nodes']['memories/log.md']['stale_after_days'] = None
    with pytest.raises(ValueError): run(data)


def test_changed_existing_observation_preserves_base_date(repo):
    data = prepared(repo)
    b, c, contract, inputs, receipt = data
    text = c['documents']['memories/log.md'].replace('measured value 7', 'measured value 3')
    (repo / 'memories/log.md').write_text(text)
    b = graph(repo)
    contract['base_documents_sha256'] = {p: digest(t) for p, t in b['documents'].items()}
    from wiki_core.document_records import sections
    contract['documents'][0]['records'][0]['base_sha256'] = digest(sections(text)[1]['New record'][2])
    current, base, result = run((b, c, contract, inputs, receipt))
    assert result['ok']
    nid = node_id('memories/log.md', 'entry-0')
    assert base['nodes'][nid]['updated_at'] == '2026-01-01'
    assert current['nodes'][nid]['updated_at'] == TODAY.isoformat()


@pytest.mark.parametrize('fault', ['context', 'selector', 'snapshot', 'proof_bytes', 'source_bytes', 'self_source', 'base_self_source', 'declaration_date'])
@pytest.mark.parametrize('mode', ['h2_v1', 'explicit_view_v2'])
def test_receipt_cannot_be_replayed_or_replace_its_source(repo, fault, mode):
    b, c, contract, inputs, receipt = prepared(repo, mode=mode)
    record = contract['documents'][0]['records'][0]
    if fault in {'self_source', 'base_self_source'}:
        source = (c if fault == 'self_source' else b)['documents']['memories/log.md'].encode()
        inputs['current', 'measurement'] = source
        contract['artifacts'][0]['sha256'] = digest(source.decode())
        receipt['sources'][0]['sha256'] = digest(source.decode())
    seal(contract, inputs, receipt)
    if fault == 'context': record['context_records'] = ['remainder']
    elif fault == 'selector': record['rationale'] += ' Newly claims a different semantic boundary.'
    elif fault == 'snapshot': c['documents']['memories/new-source.md'] += '\nChanged source.\n'
    elif fault == 'proof_bytes': inputs['current', 'observation-review'] += b' '
    elif fault == 'source_bytes': inputs['current', 'measurement'] += b' '
    elif fault == 'declaration_date': record['recorded_on'] = '2026-10-19'
    with pytest.raises(ValueError):
        project_records(c, b, {'memories/log.md'}, contract, artifact_inputs=inputs)


def test_explicit_view_observation_keeps_raw_obligation_without_causal_review(repo):
    b, c, contract, inputs, receipt = prepared(repo)
    record = contract['documents'][0]['records'][0]
    record.pop('heading')
    record['selectors'] = {'base': None, 'current': {'kind': 'h2', 'heading': 'New record'}}
    contract['document_modes']['memories/log.md'] = 'explicit_view_v2'
    current, base, result = run((b, c, contract, inputs, receipt))
    nid = node_id('memories/log.md', 'entry-0')
    assert nid in current['verified_record_observations']
    assert nid not in base['nodes']
    assert 'memories/log.md' not in current['verified_precise_component_seeds']
    assert current['nodes']['memories/log.md']['updated_at'] == base['nodes']['memories/log.md']['updated_at']
    assert not result['ok']
    assert any(row['path'] == 'memories/log.md' for row in result['blockers'])


def test_frontmatter_cannot_forge_observation_freshness(repo):
    p = page(repo, 'log', stale=True, body='# Log\n\nOld assertion.\n',
             verified_record_observations={'fake': {'observed_on': TODAY.isoformat()}})
    base = graph(repo)
    p.write_text(p.read_text() + '\nChanged assertion.\n')
    current = graph(repo)
    result = evaluate_impact(current, base, {'memories/log.md'}, today=TODAY)
    assert not result['ok']


def test_qualified_record_is_bound_in_causal_pair(repo):
    from wiki_core.causal_review import pair_digest
    c, b, result = run(prepared(repo))
    before = pair_digest(c, b, result['seeds'])
    node = node_id('memories/log.md', 'entry-0')
    c['verified_record_observations'][node]['receipt_sha256'] = '0' * 64
    assert pair_digest(c, b, result['seeds']) != before


def structured_source(data, *, same_document, alias=False):
    b, c, contract, inputs, receipt = data
    path = 'memories/log.md' if same_document else 'memories/new-source.md'
    event = {'event_id': 'retained-reading', 'value': 7}
    # This event already exists in BASE; the observation adds only its H2.
    for origin, g in (('base', b), ('current', c)):
        g['documents'][path] = g['documents'][path].replace(
            '---\n', '---\nmeasurements: ' + json.dumps([event]) + '\n', 1)
        contract[f'{origin}_documents_sha256'][path] = digest(g['documents'][path])
    receipt['document_sha256'] = digest(c['documents']['memories/log.md'])
    source = dict(id='measurement', origin='current', document=path, field='measurements',
                  match_key='event_id', match_value='retained-reading', sha256=structured_digest(event))
    contract['artifacts'] = [source]
    inputs.pop(('current', 'measurement'))
    if alias:
        contract['artifacts'].append(dict(source, id='declared-original'))
        contract['artifacts'][0] = dict(id='measurement', origin='current',
            path='references/alias.json', sha256=structured_digest(event))
        inputs['current', 'measurement'] = json.dumps(event, sort_keys=True, separators=(',', ':')).encode()
    receipt['sources'][0]['sha256'] = structured_digest(event)
    return data


@pytest.mark.parametrize('alias', [False, True])
def test_own_structured_event_is_not_an_independent_observation_source(repo, alias):
    data = structured_source(prepared(repo), same_document=True, alias=alias)
    with pytest.raises(ValueError, match='circular observation source'):
        run(data)


def test_structured_evidence_from_another_document_remains_supported(repo):
    _, _, result = run(structured_source(prepared(repo), same_document=False))
    assert result['ok']


def test_alias_of_a_causal_review_receipt_is_not_a_source(repo):
    data = prepared(repo)
    b, c, contract, inputs, receipt = data
    source = inputs['current', 'measurement']
    contract['artifacts'].append(dict(id='causal-review', origin='current',
        path='references/causal-review.json', sha256=digest(source.decode())))
    inputs['current', 'causal-review'] = source
    contract['causal_review'] = {'review_evidence': 'causal-review'}
    with pytest.raises(ValueError, match='circular observation source'):
        run(data)
