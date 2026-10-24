"""Qualification syntax and real canonical receipt proof, without gate stubs."""
import copy
import datetime as dt

import pytest

import wiki_core.action_contribution as port
from wiki_core.action_transition import (_parse_document, _render_document, append_contribution_log,
    integrate_action_body, transition_action_page)
from wiki_core.config import load_config
from wiki_core.contribution_records import _canonical_log_effect
from wiki_core.document_records import digest, edge_digest, project_records, sections
from wiki_core.freshness_impact import authored_graph, evaluate_impact
from test_action_contribution import fixture, review
from test_document_records import setup_increment
from test_freshness_impact import page, repo  # noqa: F401 - shared synthetic repo fixture


@pytest.mark.parametrize('mutation', ['valid', 'v1', 'base', 'navigation', 'provenance',
    'consumption', 'evidence', 'empty_evidence', 'alias_hash', 'bad_hash', 'unknown', 'boolean'])
def test_effect_qualification_is_explicit_and_strict(repo, mutation):
    base, current, contract = setup_increment(repo, consumer=True)
    contract.update(schema_version='document_record.v2',
                    document_modes={'memories/log.md': 'h2_v1'})
    edge, = [e for e in current['edges'] if e['source'] == 'memories/consumer.md'
             and e['target'] == 'memories/log.md']
    binding = dict(origin='current', edge_sha256=edge_digest(edge), consumer_record='document',
        role='change_target', contribution_effect='canonical_log_annotation',
        prerequisite_document_sha256=digest(current['documents']['memories/log.md']),
        rationale='The independently authored obligation requires the new canonical effect.')
    contract['bindings'] = [binding]
    if mutation == 'v1':
        contract['schema_version'] = 'document_record.v1'
    elif mutation == 'base':
        binding['origin'] = 'base'
    elif mutation in {'navigation', 'provenance', 'consumption'}:
        binding['role'] = mutation
    elif mutation in {'evidence', 'empty_evidence'}:
        binding['evidence'] = ['old-observation'] if mutation == 'evidence' else []
    elif mutation == 'alias_hash':
        binding['target_document_sha256'] = binding['prerequisite_document_sha256']
    elif mutation == 'bad_hash':
        binding['prerequisite_document_sha256'] = 'unbound'
    elif mutation in {'unknown', 'boolean'}:
        binding['contribution_effect'] = True if mutation == 'boolean' else 'any_log_write'
    if mutation == 'valid':
        # Syntax alone grants no renewal: ordinary projection still checks the
        # literal prerequisite guard; only the port can prove the new effect.
        project_records(current, base, {'memories/log.md'}, contract)
        binding['prerequisite_document_sha256'] = '0' * 64
        with pytest.raises(ValueError, match='snapshot mismatch'):
            project_records(current, base, {'memories/log.md'}, contract)
    else:
        with pytest.raises(ValueError, match='invalid canonical contribution effect'):
            project_records(current, base, {'memories/log.md'}, contract)


@pytest.mark.parametrize('mutation', ['valid', 'v1', 'null', 'empty', 'extra', 'missing_binding',
    'remainder', 'duplicate', 'evidence', 'effect', 'alias', 'navigation', 'foreign_log',
    'different_field', 'different_kind', 'different_endpoint', 'changed_guard'])
def test_canonical_annotation_context_requires_exact_qualified_event(repo, mutation):
    event = page(repo, 'historical-event', stale=True, consolidated_into=['memories/log.md'])
    event.write_text(event.read_text().replace('page_type: project', 'page_type: ingestion_event'))
    base, current, contract = setup_increment(repo)
    contract.update(schema_version='document_record.v2', document_modes={'memories/log.md': 'h2_v1'})
    raw, = [e for e in current['edges'] if e.get('path') == 'memories/historical-event.md'
            and e.get('field') == 'consolidated_into']
    if mutation == 'different_field':
        raw['field'] = 'source_refs'
    elif mutation == 'different_kind':
        current['nodes']['memories/historical-event.md']['page_type'] = 'project'
    elif mutation == 'different_endpoint':
        raw['source'] = 'memories/old-source.md'
    binding = dict(origin='current', edge_sha256=edge_digest(raw), consumer_record='entry-0',
        role='change_target', prerequisite_document_sha256=digest(current['documents']['memories/historical-event.md']),
        rationale='This event names a historical destination, not the source of this later entry.')
    contract['bindings'] = [binding]
    qualification = dict(edge_sha256=binding['edge_sha256'], consumer_record='entry-0',
        rationale='Only the fixed receipt-backed canonical preparation annotation has the same destination context.')
    context = dict(log_path='memories/log.md', bindings=[qualification])
    contract['canonical_log_annotation_context'] = context
    if mutation == 'v1':
        contract['schema_version'] = 'document_record.v1'
    elif mutation == 'null':
        contract['canonical_log_annotation_context'] = None
    elif mutation == 'empty':
        context['bindings'] = []
    elif mutation == 'extra':
        qualification['any_future_record'] = True
    elif mutation == 'missing_binding':
        contract['bindings'] = []
    elif mutation == 'remainder':
        qualification['consumer_record'] = binding['consumer_record'] = 'remainder'
    elif mutation == 'duplicate':
        context['bindings'].append(copy.deepcopy(qualification))
    elif mutation == 'evidence':
        binding['evidence'] = []
    elif mutation == 'effect':
        binding['contribution_effect'] = 'canonical_log_annotation'
    elif mutation == 'alias':
        binding['target_document_sha256'] = binding['prerequisite_document_sha256']
    elif mutation == 'navigation':
        binding['role'] = 'navigation'
    elif mutation == 'foreign_log':
        context['log_path'] = 'memories/old-source.md'
    elif mutation == 'changed_guard':
        binding['prerequisite_document_sha256'] = '0' * 64
    if mutation == 'valid':
        projected, _, _, _ = project_records(current, base, {'memories/log.md'}, contract)
        # Qualification itself does not erase the historical remainder's dependency.
        assert any(e['type'] == 'impact' and e['target'] == 'memories/log.md::record:remainder'
                   for e in projected['edges'])
    else:
        with pytest.raises(ValueError, match='canonical log annotation context|snapshot mismatch'):
            project_records(current, base, {'memories/log.md'}, contract)
def test_context_policy_does_not_qualify_an_arbitrary_new_record(repo):
    event = page(repo, 'historical-event', stale=True, consolidated_into=['memories/log.md'])
    event.write_text(event.read_text().replace('page_type: project', 'page_type: ingestion_event'))
    base, current, contract = setup_increment(repo)
    contract.update(schema_version='document_record.v2', document_modes={'memories/log.md': 'h2_v1'})
    raw, = [e for e in current['edges'] if e.get('field') == 'consolidated_into']
    contract['bindings'] = [dict(origin='current', edge_sha256=edge_digest(raw), consumer_record='entry-0',
        role='change_target', prerequisite_document_sha256=digest(event.read_text()),
        rationale='The reviewed existing observation did not consume this historical destination event.')]
    contract['canonical_log_annotation_context'] = dict(log_path='memories/log.md', bindings=[dict(
        edge_sha256=edge_digest(raw), consumer_record='entry-0',
        rationale='Only a future receipt-proved canonical annotation has this bounded qualification.')])
    path = repo / 'memories/log.md'
    path.write_text(path.read_text() + '\n## Arbitrary later assertion\n\nAn unproved later observation.\n')
    final = authored_graph(repo, load_config(repo))
    contract['current_documents_sha256']['memories/log.md'] = digest(path.read_text())
    available = sections(path.read_text())[1]
    prior = contract['documents'][0]['records'][0]
    prior['current_sha256'] = digest(available[prior['heading']][2])
    contract['documents'][0]['records'].append({**prior, 'id': 'unproved',
        'heading': 'Arbitrary later assertion', 'base_sha256': None,
        'current_sha256': digest(available['Arbitrary later assertion'][2]),
        'rationale': 'This test assertion has no canonical receipt or occurrence qualification.'})
    projected, projected_base, changes, _ = project_records(final, base, {'memories/log.md'}, contract)
    result = evaluate_impact(projected, projected_base, changes, today=dt.date(2026, 10, 18))
    assert not result['ok']
    assert 'memories/historical-event.md' in {row['path'] for row in result['blockers']}


@pytest.mark.parametrize('base_history', ['absent', 'null', 'empty'])
@pytest.mark.parametrize('legacy', [False, True])
def test_new_receipt_and_log_proof_preserves_dialogue_suffix_and_refuses_forgery(tmp_path, base_history, legacy):
    action, request = fixture(tmp_path)
    path, log = 'memories/actions/example.md', 'memories/system/log.md'
    if base_history != 'absent':
        values, body = _parse_document(action.read_text())
        values['action_state_history'] = None if base_history == 'null' else []
        action.write_text(_render_document(values, body))
    documents = {path: action.read_text(), log: (tmp_path / log).read_text()}
    # These are real canonical writers. The fixture's gate scripts are never
    # executed and do not qualify the separate real-producer integration test.
    transition_action_page(tmp_path, action, 'open', dialogue_event={
        'event_id': 'effect-question', 'kind': 'question', 'coordinator': 'research',
        'text': 'Which synthetic source?'}, dialogue_actor='coordinator:research',
        expected_sha256=digest(action.read_text()))
    transition_action_page(tmp_path, action, 'open', dialogue_event={
        'event_id': 'effect-answer', 'kind': 'answer', 'coordinator': 'research',
        'text': 'The retained synthetic source.', 'reply_to': 'effect-question'},
        expected_sha256=digest(action.read_text()))
    material = port.digest(request)
    identity = port._support_identity(request, material, review(request))
    _, body = _parse_document(request['files'][0]['text'])
    integrate_action_body(tmp_path, action, body, expected_sha256=digest(action.read_text()),
                          contribution=identity)
    fm, _ = _parse_document(action.read_text())
    append_contribution_log(tmp_path, log, path, material, fm['action_state_history'][-1]['at'], legacy=legacy)
    final = {'documents': {path: action.read_text(), log: (tmp_path / log).read_text()}}
    assert _canonical_log_effect(documents, final, path, log, identity)['legacy'] is legacy
    for mutation in ('absent', 'material_sha256', 'effect_key', 'task_ref', 'run_ref',
                     'session_ref', 'review', 'log_missing', 'log_extra', 'history'):
        candidate, expected = copy.deepcopy(final), copy.deepcopy(identity)
        if mutation == 'absent':
            expected = None
        elif mutation in identity:
            expected[mutation] = 'forged'
        elif mutation == 'log_missing':
            candidate['documents'][log] = documents[log]
        elif mutation == 'log_extra':
            candidate['documents'][log] += '\nAn unproved annotation.\n'
        else:
            candidate['documents'][path] = candidate['documents'][path].replace('body_integration', 'contract_update')
        with pytest.raises(ValueError, match='canonical_log_effect_unproved'):
            _canonical_log_effect(documents, candidate, path, log, expected)
    for invalid in (False, 0, 'empty', {}):
        invalid_documents = dict(documents)
        values, body = _parse_document(documents[path])
        values['action_state_history'] = invalid
        invalid_documents[path] = _render_document(values, body)
        with pytest.raises(ValueError, match='canonical_log_effect_unproved'):
            _canonical_log_effect(invalid_documents, final, path, log, identity)
    # The same effect cannot prove a second transaction on top of itself.
    with pytest.raises(ValueError, match='canonical_log_effect_unproved'):
        _canonical_log_effect(final['documents'], final, path, log, identity)
