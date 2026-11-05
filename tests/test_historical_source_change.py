import json
from pathlib import Path

import pytest

from tests.test_folder_policy_core import git, repo
from tests.test_protected_ingestion import prepared_repo, prepare, record, _result_for
from tests.test_protected_historical_candidates import grant_prior
from wiki_core.coordination_context import CoordinationBinding


def setup_changed_source(prepared_repo):
    root, sha = prepared_repo
    text = ''.join(f'Synthetic evidence paragraph {i} with bounded detail.\n' for i in range(1200))
    (root / 'source.txt').write_text(text)
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    before = prepare(root, binding, **args, source_context='system')
    sample = _result_for(before['request'])
    results = [{**sample, **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')}}
               for row in before['request']['chunks']]
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'], results=results)
    binding = grant_prior(binding, args, before, sha)
    (root / 'source.txt').write_text(text + 'A changed trailing paragraph for the new source.\n')
    current = prepare(root, binding, **args, source_context='system')
    previous_row = before['request']['chunks'][0]
    same = [row for row in current['request']['chunks'] if row['chunk_hash_sha256'] == previous_row['chunk_hash_sha256']]
    assert len(same) == 1 and current['source_id'] != before['source_id']
    return root, sha, binding, args, before, current, previous_row, same[0], results[0]


def test_changed_source_unique_identical_chunk_is_historical_candidate(prepared_repo, monkeypatch):
    root, sha, binding, args, before, current, old_row, new_row, result = setup_changed_source(prepared_repo)
    previous_path = next((root / 'data/derived/wiki/.wiki-viva-protected').rglob('*' + before['request_id'] + '-llm-context-request.json'))
    original_open = Path.open; opened = []
    def spy(path, *a, **kw):
        if path == previous_path: opened.append(path)
        return original_open(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', spy)
    no_id = prepare(root, binding, **args, source_context='system', previous_request_id=before['request_id'],
                    candidate_chunk_ids=[new_row['chunk_id']])
    assert no_id['historical_review']['status'] == 'unavailable' and opened == []
    reviewed = prepare(root, binding, **args, source_context='system', previous_request_id=before['request_id'],
                       previous_source_id=before['source_id'], candidate_chunk_ids=[new_row['chunk_id']])
    assert reviewed['historical_review']['status'] == 'review_needed'
    assert reviewed['request']['chunks'][0]['result_exists'] is False
    candidate = reviewed['historical_review']['candidates'][0]
    assert candidate['status'] == 'review_needed' and candidate['result'] == result
    assert candidate['chunk_id'] == new_row['chunk_id'] != old_row['chunk_id']
    assert candidate['origin']['source_id'] == before['source_id']
    assert candidate['origin']['source_hash_sha256'] == before['request']['source_hash_sha256']
    assert candidate['origin']['chunk_id'] == old_row['chunk_id']
    assert candidate['origin']['chunk_hash_sha256'] == new_row['chunk_hash_sha256']
    assert candidate['origin']['source_proof'] == 'retained_capture_not_raw_source'
    new_cache = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache' / (new_row['cache_key'] + '.json')
    assert not new_cache.exists()


def test_changed_source_with_inconsistent_old_capture_stays_pending(prepared_repo, monkeypatch):
    root, sha, binding, args, before, current, old_row, new_row, result = setup_changed_source(prepared_repo)
    directory = root / 'data/derived/wiki/.wiki-viva-protected'
    # Locate the chunks document, not the manifest or extracted text.
    candidates = list(directory.rglob(before['source_id'] + '.json'))
    old_chunks_path = next(path for path in candidates if json.loads(path.read_text()).get('schema_version') == 'wiki_chunks.v1')
    document = json.loads(old_chunks_path.read_text()); document['chunks'][0]['text'] += ' tampered'
    old_chunks_path.write_text(json.dumps(document))
    old_result = directory / 'llm-cache' / (old_row['cache_key'] + '.json')
    original_open = Path.open
    def sentinel(path, *a, **kw):
        if path == old_result: pytest.fail('opened old result without matching retained capture')
        return original_open(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', sentinel)
    outcome = prepare(root, binding, **args, source_context='system', previous_request_id=before['request_id'],
                      previous_source_id=before['source_id'], candidate_chunk_ids=[new_row['chunk_id']])
    assert outcome['historical_review']['status'] == 'unavailable'
    assert outcome['request']['chunks'][0]['result_exists'] is False


def test_duplicate_historical_chunk_is_ambiguous_and_stays_pending(prepared_repo, monkeypatch):
    root, sha = prepared_repo
    paragraph = 'sameword ' * 900
    (root / 'source.txt').write_text(paragraph + '\n\n' + paragraph + '\n')
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    before = prepare(root, binding, **args, source_context='system')
    old_rows = before['request']['chunks']
    assert len(old_rows) == 2 and old_rows[0]['chunk_hash_sha256'] == old_rows[1]['chunk_hash_sha256']
    result = _result_for(before['request'])
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'], results=[result])
    binding = grant_prior(binding, args, before, sha)
    (root / 'source.txt').write_text(paragraph + '\n\n' + paragraph + '\n\nChanged tail.\n')
    pending = prepare(root, binding, **args, source_context='system')
    row = next(item for item in pending['request']['chunks'] if item['chunk_hash_sha256'] == old_rows[0]['chunk_hash_sha256'])
    old_result = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache' / (result['cache_key'] + '.json')
    original = Path.open
    def sentinel(path, *a, **kw):
        if path == old_result: pytest.fail('ambiguous prior result was opened')
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', sentinel)
    outcome = prepare(root, binding, **args, source_context='system', previous_request_id=before['request_id'],
                      previous_source_id=before['source_id'], candidate_chunk_ids=[row['chunk_id']])
    assert outcome['historical_review']['status'] == 'unavailable'
    assert row['result_exists'] is False


def test_changed_chunk_is_not_a_historical_candidate(prepared_repo, monkeypatch):
    root, sha, binding, args, before, current, old_row, new_row, result = setup_changed_source(prepared_repo)
    old_hashes = {row['chunk_hash_sha256'] for row in before['request']['chunks']}
    changed = [row for row in current['request']['chunks'] if row['chunk_hash_sha256'] not in old_hashes]
    assert changed
    old_keys = {row['cache_key'] + '.json' for row in before['request']['chunks']}
    original = Path.open
    def sentinel(path, *a, **kw):
        if path.name in old_keys: pytest.fail('old result opened for a changed chunk')
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', sentinel)
    outcome = prepare(root, binding, **args, source_context='system', previous_request_id=before['request_id'],
                      previous_source_id=before['source_id'], candidate_chunk_ids=[changed[0]['chunk_id']])
    assert outcome['historical_review']['status'] == 'unavailable'
    assert changed[0]['result_exists'] is False


def test_old_capture_change_discards_candidates_without_blocking_current(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha, binding, args, before, current, old_row, new_row, result = setup_changed_source(prepared_repo)
    previous_rows = before['request']['chunks']
    old_hashes = {row['chunk_hash_sha256'] for row in previous_rows}
    selected = [row['chunk_id'] for row in current['request']['chunks'] if row['chunk_hash_sha256'] in old_hashes][:2]
    assert len(selected) == 2
    directory = root / 'data/derived/wiki/.wiki-viva-protected'
    chunks_path = next(path for path in directory.rglob(before['source_id'] + '.json')
                       if json.loads(path.read_text()).get('schema_version') == 'wiki_chunks.v1')
    original = protected._read_json; changed = []; later = []
    first_name = previous_rows[0]['cache_key'] + '.json'; second_name = previous_rows[1]['cache_key'] + '.json'
    def mutate(*a, **kw):
        if a[3].name == second_name and changed: later.append(True)
        value = original(*a, **kw)
        if a[3].name == first_name and not changed:
            with chunks_path.open('a') as stream: stream.write(' ')
            changed.append(True)
        return value
    monkeypatch.setattr(protected, '_read_json', mutate)
    outcome = prepare(root, binding, **args, source_context='system', previous_request_id=before['request_id'],
                      previous_source_id=before['source_id'], candidate_chunk_ids=selected)
    assert changed and later == []
    assert outcome['historical_review']['status'] == 'unavailable'
    assert outcome['request']['pending_llm_calls'] > 0


def test_operator_review_of_unchanged_chunk_in_changed_source_preserves_origin(prepared_repo):
    import datetime as dt
    import hashlib
    from tests.test_protected_ingestion import consolidate, protected_source_stage
    from wiki_core.frontmatter import parse_frontmatter
    root, sha, binding, args, before, current, old_row, new_row, old_result = setup_changed_source(prepared_repo)
    selected = prepare(root, binding, **args, source_context='system', previous_request_id=before['request_id'],
                       previous_source_id=before['source_id'], candidate_chunk_ids=[new_row['chunk_id']])
    candidate = selected['historical_review']['candidates'][0]
    assert selected['request']['chunks'][0]['result_exists'] is False
    new_result = {**_result_for(current['request']), 'claims': ['New caller-supplied interpretation']}
    assert new_result['chunk_id'] == new_row['chunk_id']
    review = {'chunk_id': new_row['chunk_id'], 'previous_request_id': before['request_id'],
        'previous_source_id': before['source_id'], 'previous_result_sha256': candidate['origin']['result_sha256'],
        'decision': 'reviewed', 'reviewer_label': 'synthetic caller', 'note': 'Compared with the current source.'}
    ids = dict(source_id=current['source_id'], request_id=current['request_id'])
    outcome = record(root, binding, **args, **ids, results=[new_result], historical_reviews=[review])
    assert outcome['recorded'] == 1
    cache = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache'
    stored = json.loads((cache / (new_row['cache_key'] + '.json')).read_text())
    assert stored['claims'] == ['New caller-supplied interpretation'] and stored['claims'] != old_result['claims']
    annotation = stored['protected_historical_review']
    assert annotation['status'] == 'reviewed_by_caller'
    assert annotation['identity_verification'] == 'not_performed' and annotation['factual_verification'] == 'not_asserted'
    assert annotation['origin']['source_id'] == before['source_id']
    assert annotation['origin']['source_hash_sha256'] == before['request']['source_hash_sha256']
    assert annotation['origin']['chunk_id'] == old_row['chunk_id']
    assert annotation['origin']['source_proof'] == 'retained_capture_not_raw_source'
    # The other changed-source chunks remain pending until explicitly recorded.
    assert prepare(root, binding, **args, source_context='system')['request']['pending_llm_calls'] > 0
    inspected = protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'results',
        'chunk_ids': [new_row['chunk_id']]})['result']
    assert inspected['results'][0]['result']['protected_historical_review'] == annotation
    remaining = [{**_result_for(current['request']), **{key: row[key] for key in
        ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')}}
        for row in current['request']['chunks'][1:]]
    assert remaining
    record(root, binding, **args, **ids, results=remaining)
    target = ('memories/system/ingestion/events/2026-11-04-' +
              hashlib.sha256(current['source_id'].encode()).hexdigest() + '-' + current['request_id'] + '.md')
    consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
                event_target=target, date=dt.date(2026, 11, 4))
    frontmatter, _ = parse_frontmatter(root / target)
    assert frontmatter['historical_reviews'][0]['review'] == annotation
    packet = protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'integration', 'candidates': []})['result']['packet']
    assert packet['historical_reviews'][0]['review'] == annotation


def test_changed_capture_is_rechecked_before_old_result_open(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha, binding, args, before, current, old_row, new_row, result = setup_changed_source(prepared_repo)
    original_capture = protected._historical_capture
    modified = []
    def change_capture(*a, **kw):
        proof = original_capture(*a, **kw)
        if proof is not None and not modified:
            with proof[2][1][0].open('a') as stream:
                stream.write(' ')
            modified.append(True)
        return proof
    original_read = protected._read_json
    opened = []
    def observe(*a, **kw):
        if a[3].name == old_row['cache_key'] + '.json':
            opened.append(True)
        return original_read(*a, **kw)
    monkeypatch.setattr(protected, '_historical_capture', change_capture)
    monkeypatch.setattr(protected, '_read_json', observe)
    output = prepare(root, binding, **args, source_context='system', previous_request_id=before['request_id'],
                     previous_source_id=before['source_id'], candidate_chunk_ids=[new_row['chunk_id']])
    assert modified and not opened and output['historical_review']['status'] == 'unavailable'


def test_missing_history_blocks_only_affected_reviewed_result(prepared_repo):
    from dataclasses import replace
    from tests.test_protected_ingestion import protected_source_stage
    from wiki_core.coordination_context import ProtectedCoordinationError
    root, sha, binding, args, before, current, old_row, new_row, old_result = setup_changed_source(prepared_repo)
    selected = prepare(root, binding, **args, source_context='system', previous_request_id=before['request_id'],
                       previous_source_id=before['source_id'], candidate_chunk_ids=[new_row['chunk_id']])
    candidate = selected['historical_review']['candidates'][0]
    review = {'chunk_id': new_row['chunk_id'], 'previous_request_id': before['request_id'],
              'previous_source_id': before['source_id'], 'previous_result_sha256': candidate['origin']['result_sha256'],
              'decision': 'reviewed', 'reviewer_label': 'synthetic caller', 'note': 'Reviewed context.'}
    ids = dict(source_id=current['source_id'], request_id=current['request_id'])
    result = {**_result_for(current['request']), 'claims': ['New supplied claim']}
    record(root, binding, **args, **ids, results=[result], historical_reviews=[review])
    unbound = replace(binding, previous_request_grants=())
    outcome = prepare(root, unbound, **args, source_context='system')
    blocked = outcome['request']['chunks'][0]
    assert blocked['result_exists'] is False
    assert blocked['result_blocked_reason'] == 'historical_review_unavailable_preserved'
    assert 'blocked historical annotations' in outcome['result_budget']['coverage']
    other_row = current['request']['chunks'][1]
    other = {**_result_for(current['request']), **{k: other_row[k] for k in
             ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')}}
    assert record(root, unbound, **args, **ids, results=[other])['recorded'] == 1
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, unbound, 'inspect', {**args, **ids, 'view': 'results',
                                                        'chunk_ids': [new_row['chunk_id']]})
    inspected = protected_source_stage(root, unbound, 'inspect', {**args, **ids, 'view': 'results',
                                                               'chunk_ids': [other_row['chunk_id']]})['result']
    assert inspected['results'][0]['result']['chunk_id'] == other_row['chunk_id']
    restored = prepare(root, binding, **args, source_context='system')
    assert restored['request']['chunks'][0]['result_exists'] is True
