import copy
import datetime as dt
from pathlib import Path

import pytest
import yaml

from tests.test_folder_policy_core import git, repo, write
from tests.test_protected_ingestion import prepared_repo, prepare, record, _nested_integrator_repo, _result_for
from tests.test_protected_historical_candidates import grant_prior
from wiki_core.context_policy import load_policy
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.ingest.historical_candidates import selected_grants


@pytest.mark.parametrize('direction', ['source_export', 'instruction_import'])
def test_expired_redundant_connection_does_not_hide_candidate(prepared_repo, direction):
    root, _ = prepared_repo
    sha = _nested_integrator_repo(root)
    binding = CoordinationBinding(('alpha', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='alpha', approved_revision=sha, entry_folder='alpha', entry_index='alpha/index.md',
                source_ref='alpha/source.txt', artifact_context='.')
    before = prepare(root, binding, **args, source_context='alpha')
    result = _result_for(before['request'])
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'], results=[result])
    binding = grant_prior(binding, args, before, sha)
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    if direction == 'source_export':
        rule = next(item for item in config['context_access']['alpha']['exports'] if item['selector'] == 'alpha/source.txt')
        parties = [('alpha', 'exports'), ('.', 'imports')]
    else:
        rule = next(item for item in config['context_access']['.']['exports'] if item['selector'] == 'AGENTS.md')
        parties = [('.', 'exports'), ('alpha', 'imports')]
    expired = {**copy.deepcopy(rule), 'expires': '2000-01-01'}
    for party, side in parties:
        config['context_access'][party][side].append(copy.deepcopy(expired))
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'add expired redundant connection')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD'); new_sha = git(root, 'rev-parse', 'HEAD')
    pending = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='alpha')
    current = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='alpha',
        previous_request_id=before['request_id'], candidate_chunk_ids=[pending['request']['chunks'][0]['chunk_id']])
    assert current['historical_review']['status'] == 'review_needed'
    assert current['historical_review']['candidates'][0]['result'] == result
    assert current['request']['chunks'][0]['result_exists'] is False
    if direction == 'instruction_import':
        assert current['historical_review']['candidates'][0]['origin']['authority_metadata_changed'] is True


def test_live_connection_expiration_is_inclusive_and_preserved(prepared_repo):
    root, _ = prepared_repo
    sha = _nested_integrator_repo(root)
    binding = CoordinationBinding(('alpha', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    request = prepare(root, binding, context_id='alpha', approved_revision=sha, entry_folder='alpha',
        entry_index='alpha/index.md', source_ref='alpha/source.txt', artifact_context='.', source_context='alpha')['request']
    policy = load_policy(root, sha, 'wiki.config.yaml')
    selected = selected_grants(policy, request, today=dt.date(2099, 1, 1))
    bilateral = [item for item in selected if item['producer'] != item['reader']]
    assert bilateral and all(item['bilateral_valid_through'] == '2099-01-01' for item in bilateral)
    with pytest.raises(ValueError, match='selected grant unavailable'):
        selected_grants(policy, request, today=dt.date(2099, 1, 2))


def test_different_scopes_with_same_selected_read_decisions_keep_candidate(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    before = prepare(root, binding, **args, source_context='system')
    result = _result_for(before['request'])
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'], results=[result])
    binding = grant_prior(binding, args, before, sha)
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access']['.']['policy']['read'] = ['AGENTS.md', 'index.md', 'source.txt', 'alpha',
        'data/derived/wiki/.wiki-viva-protected']
    write(root, 'wiki.config.yaml', yaml.safe_dump(config)); git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'narrow unselected read scopes'); git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    new_sha = git(root, 'rev-parse', 'HEAD')
    pending = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system')
    current = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system',
        previous_request_id=before['request_id'], candidate_chunk_ids=[pending['request']['chunks'][0]['chunk_id']])
    candidate = current['historical_review']['candidates'][0]
    assert current['historical_review']['status'] == 'review_needed'
    assert candidate['origin']['authority_metadata_changed'] is True
    assert candidate['result'] == result and current['request']['chunks'][0]['result_exists'] is False


def test_current_deny_blocks_before_source_or_historical_request(prepared_repo, monkeypatch):
    root, _ = prepared_repo
    sha = _nested_integrator_repo(root)
    binding = CoordinationBinding(('alpha', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='alpha', approved_revision=sha, entry_folder='alpha', entry_index='alpha/index.md',
                source_ref='alpha/source.txt', artifact_context='.')
    before = prepare(root, binding, **args, source_context='alpha')
    binding = grant_prior(binding, args, before, sha)
    previous_path = next((root / 'data/derived/wiki/.wiki-viva-protected').rglob('*' + before['request_id'] + '-llm-context-request.json'))
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access']['alpha']['policy'].setdefault('deny', {}).setdefault('read', []).append('self/source.txt')
    write(root, 'wiki.config.yaml', yaml.safe_dump(config)); git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'deny selected source'); git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    new_sha = git(root, 'rev-parse', 'HEAD'); original = Path.open
    def sentinel(path, *a, **kw):
        if path in (previous_path, root / 'alpha/source.txt'):
            pytest.fail('denied source or historical request opened')
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', sentinel)
    with pytest.raises(ValueError):
        prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='alpha',
            previous_request_id=before['request_id'], candidate_chunk_ids=[before['request']['chunks'][0]['chunk_id']])


def test_date_rollover_stops_before_next_historical_body(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    (root / 'source.txt').write_text(''.join(f'Synthetic evidence {i} with bounded detail.\n' for i in range(500)))
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    before = prepare(root, binding, **args, source_context='system'); rows = before['request']['chunks'][:2]
    assert len(rows) == 2
    sample = _result_for(before['request'])
    results = [{**sample, **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')}} for row in rows]
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'], results=results)
    binding = grant_prior(binding, args, before, sha)
    write(root, 'beta/unrelated.md', '# Unrelated\n'); git(root, 'add', 'beta/unrelated.md')
    git(root, 'commit', '-qm', 'unrelated folder'); git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    new_sha = git(root, 'rev-parse', 'HEAD')
    pending = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system')
    old_day = dt.date.today(); advanced = []; later_opened = []; original = protected._read_json
    monkeypatch.setattr(protected, '_candidate_authorization_day',
                        lambda: old_day + dt.timedelta(days=1) if advanced else old_day)
    def rollover(*a, **kw):
        if a[3].name == rows[1]['cache_key'] + '.json' and advanced:
            later_opened.append(True)
        value = original(*a, **kw)
        if a[3].name == rows[0]['cache_key'] + '.json':
            advanced.append(True)
        return value
    monkeypatch.setattr(protected, '_read_json', rollover)
    current = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system',
        previous_request_id=before['request_id'], candidate_chunk_ids=[row['chunk_id'] for row in pending['request']['chunks'][:2]])
    assert advanced and later_opened == []
    assert current['historical_review']['status'] == 'unavailable'
    assert current['request']['pending_llm_calls'] > 0


def test_expiry_during_candidate_stops_current_request(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, _ = prepared_repo
    sha = _nested_integrator_repo(root)
    (root / 'alpha/source.txt').write_text(''.join(f'Synthetic evidence {i} with bounded detail.\n' for i in range(500)))
    binding = CoordinationBinding(('alpha', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='alpha', approved_revision=sha, entry_folder='alpha', entry_index='alpha/index.md',
                source_ref='alpha/source.txt', artifact_context='.')
    before = prepare(root, binding, **args, source_context='alpha'); rows = before['request']['chunks'][:2]
    assert len(rows) == 2
    sample = _result_for(before['request'])
    results = [{**sample, **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')}} for row in rows]
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'], results=results)
    binding = grant_prior(binding, args, before, sha)
    write(root, 'beta/unrelated.md', '# Unrelated\n'); git(root, 'add', 'beta/unrelated.md')
    git(root, 'commit', '-qm', 'unrelated folder'); git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    new_sha = git(root, 'rev-parse', 'HEAD')
    pending = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='alpha')
    last_valid = dt.date(2099, 1, 1); advanced = []; later_opened = []; original = protected._read_json
    monkeypatch.setattr(protected, '_candidate_authorization_day',
                        lambda: last_valid + dt.timedelta(days=1) if advanced else last_valid)
    def rollover(*a, **kw):
        if a[3].name == rows[1]['cache_key'] + '.json' and advanced:
            later_opened.append(True)
        value = original(*a, **kw)
        if a[3].name == rows[0]['cache_key'] + '.json':
            advanced.append(True)
        return value
    monkeypatch.setattr(protected, '_read_json', rollover)
    with pytest.raises(protected.ProtectedPartialError):
        prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='alpha',
            previous_request_id=before['request_id'], candidate_chunk_ids=[row['chunk_id'] for row in pending['request']['chunks'][:2]])
    assert advanced and later_opened == []
