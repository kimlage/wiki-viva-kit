"""Qualification syntax and real canonical receipt proof, without gate stubs."""
import copy

import pytest

import wiki_core.action_contribution as port
from wiki_core.action_transition import (_parse_document, append_contribution_log,
    integrate_action_body, transition_action_page)
from wiki_core.config import load_config
from wiki_core.contribution_records import _canonical_log_effect
from wiki_core.document_records import digest, edge_digest, project_records
from test_action_contribution import fixture, review
from test_document_records import setup_increment
from test_freshness_impact import repo  # noqa: F401 - shared synthetic repo fixture


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


def test_new_receipt_and_log_proof_preserves_dialogue_suffix_and_refuses_forgery(tmp_path):
    action, request = fixture(tmp_path)
    path, log = 'memories/actions/example.md', 'memories/system/log.md'
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
    append_contribution_log(tmp_path, log, path, material, fm['action_state_history'][-1]['at'])
    final = {'documents': {path: action.read_text(), log: (tmp_path / log).read_text()}}
    _canonical_log_effect(documents, final, path, log, identity)
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
    # The same effect cannot prove a second transaction on top of itself.
    with pytest.raises(ValueError, match='canonical_log_effect_unproved'):
        _canonical_log_effect(final['documents'], final, path, log, identity)
