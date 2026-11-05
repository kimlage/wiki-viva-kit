import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_folder_policy_core import repo
from tests.test_protected_ingestion import (prepared_repo, prepare, record, consolidate, _result_for,
                                            protected_source_stage)
from tests.test_protected_historical_candidates import advance, grant_prior
from wiki_core.coordination_context import CoordinationBinding, ProtectedCoordinationError


def selected_history(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    old = prepare(root, binding, **args, source_context='system')
    old_result = {**_result_for(old['request']), 'claims': ['Historical claim ' + sha]}
    record(root, binding, **args, source_id=old['source_id'], request_id=old['request_id'], results=[old_result])
    binding = grant_prior(binding, args, old, sha)
    new_sha = advance(root); current_args = {**args, 'approved_revision': new_sha}
    pending = prepare(root, binding, **current_args, source_context='system')
    row = pending['request']['chunks'][0]
    candidate = prepare(root, binding, **current_args, source_context='system',
        previous_request_id=old['request_id'], candidate_chunk_ids=[row['chunk_id']])['historical_review']['candidates'][0]
    new_result = {**_result_for(pending['request']), 'claims': ['New independent operator-supplied claim']}
    selection = {'chunk_id': row['chunk_id'], 'previous_request_id': old['request_id'],
        'previous_source_id': old['source_id'], 'previous_result_sha256': candidate['origin']['result_sha256'],
        'decision': 'reviewed', 'reviewer_label': 'synthetic operator', 'note': 'Reviewed against current context.'}
    ids = dict(source_id=pending['source_id'], request_id=pending['request_id'])
    return root, sha, new_sha, binding, current_args, old, old_result, pending, new_result, selection, ids


def test_operator_review_records_new_result_and_provenance_without_copy(prepared_repo):
    root, old_sha, new_sha, binding, args, old, old_result, pending, new_result, selection, ids = selected_history(prepared_repo)
    cache = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache'
    old_path = cache / (old_result['cache_key'] + '.json'); old_bytes = old_path.read_bytes()
    out = record(root, binding, **args, **ids, results=[new_result], historical_reviews=[selection])
    assert out['recorded'] == 1
    current = json.loads((cache / (new_result['cache_key'] + '.json')).read_text())
    assert current['claims'] == ['New independent operator-supplied claim']
    assert current['claims'] != old_result['claims'] and old_path.read_bytes() == old_bytes
    meta = current['protected_historical_review']
    assert meta['status'] == 'reviewed_by_caller' and meta['identity_verification'] == 'not_performed'
    assert meta['factual_verification'] == 'not_asserted' and meta['review_policy_revision'] == new_sha
    assert meta['origin']['policy_revision'] == old_sha and meta['origin']['request_id'] == old['request_id']
    assert meta['origin']['request_source_id'] == old['source_id']
    assert meta['origin']['result_source_id'] == old_result['source_id']
    check = prepare(root, binding, **args, source_context='system')
    assert check['request']['chunks'][0]['result_exists'] is True
    inspected = protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'results',
        'chunk_ids': [pending['request']['chunks'][0]['chunk_id']]})['result']
    assert inspected['results'][0]['result']['protected_historical_review'] == meta
    target = ('memories/system/ingestion/events/2026-11-04-' + hashlib.sha256(ids['source_id'].encode()).hexdigest()
              + '-' + ids['request_id'] + '.md')
    consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
                event_target=target, date=dt.date(2026, 11, 4))
    from wiki_core.frontmatter import parse_frontmatter
    frontmatter, _ = parse_frontmatter(root / target)
    assert frontmatter['historical_reviews'][0]['review'] == meta
    packet = protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'integration', 'candidates': []})['result']['packet']
    assert packet['historical_reviews'][0]['review'] == meta


@pytest.mark.parametrize('change', ['bad_digest', 'bad_previous_source', 'missing_note', 'forged_annotation'])
def test_bad_review_is_rejected_before_current_result_write(prepared_repo, change):
    root, _, _, binding, args, _, _, _, result, selection, ids = selected_history(prepared_repo)
    if change == 'bad_digest': selection['previous_result_sha256'] = '0' * 64
    elif change == 'bad_previous_source': selection['previous_source_id'] = 'different-source'
    elif change == 'missing_note': selection['note'] = ''
    else: result['protected_historical_review'] = {'status': 'reviewed_by_caller'}
    with pytest.raises(ValueError):
        record(root, binding, **args, **ids, results=[result], historical_reviews=[selection])
    assert not (root / 'data/derived/wiki/.wiki-viva-protected/llm-cache' / (result['cache_key'] + '.json')).exists()


def test_missing_host_grant_never_opens_previous_request(prepared_repo, monkeypatch):
    root, _, _, binding, args, old, _, _, result, selection, ids = selected_history(prepared_repo)
    from dataclasses import replace
    binding = replace(binding, previous_request_grants=())
    path = next((root / 'data/derived/wiki/.wiki-viva-protected').rglob('*' + old['request_id'] + '-llm-context-request.json'))
    original = Path.open
    def sentinel(path_, *a, **kw):
        if path_ == path: pytest.fail('historical request opened without a host grant')
        return original(path_, *a, **kw)
    monkeypatch.setattr(Path, 'open', sentinel)
    with pytest.raises(ValueError):
        record(root, binding, **args, **ids, results=[result], historical_reviews=[selection])
    assert not (root / 'data/derived/wiki/.wiki-viva-protected/llm-cache' / (result['cache_key'] + '.json')).exists()


def test_historical_change_after_record_blocks_review_use(prepared_repo):
    root, _, _, binding, args, _, old_result, pending, result, selection, ids = selected_history(prepared_repo)
    record(root, binding, **args, **ids, results=[result], historical_reviews=[selection])
    path = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache' / (old_result['cache_key'] + '.json')
    path.write_text(json.dumps({**old_result, 'synthetic_changed': True}))
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'results',
            'chunk_ids': [pending['request']['chunks'][0]['chunk_id']]})


def test_trusted_local_cli_records_explicit_review(prepared_repo):
    from dataclasses import asdict
    root, _, sha, binding, args, _, _, pending, result, selection, ids = selected_history(prepared_repo)
    env = {key: value for key, value in os.environ.items() if not key.startswith('WIKI_COORDINATION_')}
    env.update(WIKI_COORDINATION_ALLOWED_CONTEXTS='.',
        WIKI_COORDINATION_PREVIOUS_REQUEST_GRANTS=json.dumps([asdict(binding.previous_request_grants[0])]))
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_coordination.py'
    payload = {'entry_folder': args['entry_folder'], 'entry_index': args['entry_index'], 'source_ref': args['source_ref'],
        'context_selection': {'omit_root_entity': True}, **ids, 'results': [result], 'historical_reviews': [selection]}
    completed = subprocess.run([sys.executable, str(script), '--root', str(root), '--context-id', '.',
        '--approved-revision', sha, '--source-stage', 'record'], input=json.dumps(payload), text=True,
        capture_output=True, check=True, env=env)
    assert json.loads(completed.stdout)['result']['recorded'] == 1
    current = protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'results',
        'chunk_ids': [pending['request']['chunks'][0]['chunk_id']]})['result']['results'][0]['result']
    assert current['protected_historical_review']['status'] == 'reviewed_by_caller'


def test_reviewed_result_does_not_infer_old_grant_from_receipt(prepared_repo, monkeypatch):
    from dataclasses import replace
    root, _, _, binding, args, old, _, pending, result, selection, ids = selected_history(prepared_repo)
    record(root, binding, **args, **ids, results=[result], historical_reviews=[selection])
    old_path = next((root / 'data/derived/wiki/.wiki-viva-protected').rglob('*' + old['request_id'] + '-llm-context-request.json'))
    no_grant = replace(binding, previous_request_grants=())
    original = Path.open
    def sentinel(path, *a, **kw):
        if path == old_path: pytest.fail('previous request opened without current host grant')
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', sentinel)
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, no_grant, 'inspect', {**args, **ids, 'view': 'results',
            'chunk_ids': [pending['request']['chunks'][0]['chunk_id']]})


def test_historical_result_changed_before_record_is_not_written(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, _, _, binding, args, _, old_result, _, result, selection, ids = selected_history(prepared_repo)
    prior = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache' / (old_result['cache_key'] + '.json')
    original = protected._historical_candidate
    changed = []
    def mutate(*a, **kw):
        value = original(*a, **kw)
        prior.write_text(json.dumps({**old_result, 'synthetic_changed': True}))
        changed.append(True)
        return value
    monkeypatch.setattr(protected, '_historical_candidate', mutate)
    with pytest.raises(protected.ProtectedPartialError):
        record(root, binding, **args, **ids, results=[result], historical_reviews=[selection])
    assert changed and not (prior.parent / (result['cache_key'] + '.json')).exists()


def test_reviewed_result_is_not_offered_as_candidate_in_third_revision(prepared_repo):
    root, old_sha, middle_sha, binding, args, old, old_result, middle, result, selection, ids = selected_history(prepared_repo)
    record(root, binding, **args, **ids, results=[result], historical_reviews=[selection])
    cache = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache'
    middle_path = cache / (result['cache_key'] + '.json')
    middle_bytes = middle_path.read_bytes()
    assert 'protected_historical_review' in json.loads(middle_bytes)
    # Only B is granted as a prior request for C; neither a receipt nor the B
    # annotation grants access to A or proves a chain of independent reviews.
    binding_for_middle = grant_prior(binding, args, middle, middle_sha)
    latest_sha = advance(root, 'gamma/unrelated.md')
    latest_args = {**args, 'approved_revision': latest_sha}
    latest = prepare(root, binding_for_middle, **latest_args, source_context='system')
    row = latest['request']['chunks'][0]
    outcome = prepare(root, binding_for_middle, **latest_args, source_context='system',
                      previous_request_id=middle['request_id'], candidate_chunk_ids=[row['chunk_id']])
    assert outcome['historical_review']['status'] == 'unavailable'
    assert row['result_exists'] is False
    assert middle_path.read_bytes() == middle_bytes
