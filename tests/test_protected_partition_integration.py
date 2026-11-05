"""A source-scoped protected cache works without a global cache grant."""
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from tests.test_folder_policy_core import git, repo, write
from tests.test_protected_ingestion import prepared_repo
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.ingest.cache_partition import partition_component
from wiki_core.ingest.protected import prepare, record, inspect, consolidate


def test_source_partition_lifecycle_and_another_source_stays_denied(prepared_repo):
    root, _ = prepared_repo
    write(root, 'source2.txt', 'A second synthetic source.\n')
    part = 'data/derived/wiki/.wiki-viva-protected/' + partition_component('.', '.', 'source.txt')
    other = 'data/derived/wiki/.wiki-viva-protected/' + partition_component('.', '.', 'source2.txt')
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['llm'] = {'protected_cache_mode': 'by_source_v1'}
    config['context_access']['.']['policy']['read'] = [
        'AGENTS.md', 'index.md', 'alpha', 'source.txt', 'source2.txt',
        'memories/sources/synthetic.md', 'memories/system/ingestion/events', part,
    ]
    config['context_access']['.']['policy']['write'] = ['alpha', 'memories/system/ingestion/events', part]
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'authorize one synthetic source partition')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                source_ref='source.txt', context_selection={'omit_root_entity': True})
    prepared = prepare(root, binding, **args, source_context='system')
    request = prepared['request']
    assert (root / part / 'source-manifests' / (prepared['source_id'] + '.json')).is_file()
    row = request['chunks'][0]
    sample = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
              'perspectives_required': request['perspectives_required'], 'perspectives': {}}
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    assert record(root, binding, **args, **ids, results=[result])['recorded'] == 1
    observed = inspect(root, binding, **args, **ids, view='results', chunk_ids=[row['chunk_id']])
    assert observed['view'] == 'results'
    event = ('memories/system/ingestion/events/2026-11-05-'
             + hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    proposal = consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
                           event_target=event, date=dt.date(2026, 11, 5))
    assert proposal['integration'] == 'pending review and incorporation'
    with pytest.raises(ValueError):
        prepare(root, binding, **{**args, 'source_ref': 'source2.txt'}, source_context='system')
    with pytest.raises(ValueError):
        inspect(root, binding, **{**args, 'source_ref': 'source2.txt'}, **ids,
                view='results', chunk_ids=[row['chunk_id']])
    assert not (root / other).exists()

