"""A source-scoped protected cache works without a global cache grant."""
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from tests.test_folder_policy_core import git, repo, write
from tests.test_protected_ingestion import prepared_repo, _nested_integrator_repo, _result_for
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


def test_nested_integrator_partition_rechecks_both_actors(prepared_repo, monkeypatch):
    from wiki_core.traversal import is_protected_artifact

    root, _ = prepared_repo
    _nested_integrator_repo(root)
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    part = 'data/derived/wiki/.wiki-viva-protected/' + partition_component('alpha', '.', 'alpha/source.txt')
    config['llm'] = {'protected_cache_mode': 'by_source_v1'}
    config['context_access']['.']['policy']['read'] = [
        'AGENTS.md', 'index.md', 'alpha', 'memories/sources/synthetic.md',
        'memories/system/ingestion/events', part]
    config['context_access']['.']['policy']['write'] = ['alpha', 'memories/system/ingestion/events', part]
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'authorize nested partition')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('alpha', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='alpha', approved_revision=sha, entry_folder='alpha',
                entry_index='alpha/index.md', source_ref='alpha/source.txt', artifact_context='.',
                context_selection={'omit_root_entity': True})
    prepared = prepare(root, binding, **args, source_context='alpha')
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    assert record(root, binding, **args, **ids, results=[_result_for(prepared['request'])])['recorded'] == 1
    row = prepared['request']['chunks'][0]
    assert inspect(root, binding, **args, **ids, view='results', chunk_ids=[row['chunk_id']])['results']
    event = ('memories/system/ingestion/events/2026-11-05-'
             + hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    assert consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
                       event_target=event, date=dt.date(2026, 11, 5))['integration'] == 'pending review and incorporation'

    original_open = Path.open
    def no_protected_read(path, *values, **kwargs):
        if is_protected_artifact(path):
            pytest.fail('protected artifact opened after authority changed')
        return original_open(path, *values, **kwargs)
    monkeypatch.setattr(Path, 'open', no_protected_read)
    with pytest.raises(ValueError):
        record(root, binding, **{k: v for k, v in args.items() if k != 'artifact_context'}, **ids, results=[])

    for context, key in [('.', 'imports'), ('alpha', 'exports')]:
        config['context_access'][context][key] = [rule for rule in config['context_access'][context][key]
                                                   if rule['selector'] != 'alpha/source.txt']
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'revoke source connection')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    with pytest.raises(ValueError):
        record(root, binding, **{**args, 'approved_revision': git(root, 'rev-parse', 'HEAD')}, **ids, results=[])
