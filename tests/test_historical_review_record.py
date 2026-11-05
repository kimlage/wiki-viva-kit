"""Retired annotations stay on disk but cannot satisfy a current request."""
import datetime as dt
import hashlib
import json

import pytest

from tests.test_folder_policy_core import repo
from tests.test_protected_ingestion import prepared_repo, prepare, record, consolidate, protected_source_stage, _result_for
from wiki_core.coordination_context import CoordinationBinding, ProtectedCoordinationError


def test_annotated_result_is_preserved_and_unavailable(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    result = _result_for(prepared['request'])
    record(root, binding, **args, **ids, results=[result])
    cache_file = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache' / (result['cache_key'] + '.json')
    from wiki_core.consolidate import deep_read_complete
    assert deep_read_complete(prepared['request'], cache_file.parent)
    result['protected_historical_review'] = {'status': 'reviewed_by_caller'}
    cache_file.write_text(json.dumps(result))
    original = cache_file.read_bytes()
    assert not deep_read_complete(prepared['request'], cache_file.parent)

    row = prepare(root, binding, **args, source_context='system')['request']['chunks'][0]
    assert row['result_exists'] is False
    assert row['result_blocked_reason'] == 'historical_review_unavailable_preserved'
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'results', 'chunk_ids': [row['chunk_id']]})
    event = ('memories/system/ingestion/events/2026-11-04-' + hashlib.sha256(ids['source_id'].encode()).hexdigest()
             + '-' + ids['request_id'] + '.md')
    with pytest.raises(ValueError):
        consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
                    event_target=event, date=dt.date(2026, 11, 4))
    assert cache_file.read_bytes() == original
    assert not (root / event).exists()


def test_retired_selectors_are_rejected(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                source_ref='source.txt', source_context='system')
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'prepare', {**args, 'previous_request_id': '0' * 64,
                                                         'candidate_chunk_ids': ['chunk']})
