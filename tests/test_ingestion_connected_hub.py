"""A registered source keeps its declared routing through folder ingestion."""
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from tests.test_protected_ingestion import prepared_repo
from tests.test_folder_policy_core import repo, write, git
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.ingest.protected import prepare, record, consolidate, inspect


def connected(root):
    pages = {
        'memories/sources/synthetic.md': ('source-synthetic', 'source', {'config_ref': 'memories/config.md'}, ''),
        'memories/config.md': ('config', 'source_config', {'input_channel_ref': 'memories/channel.md'}, ''),
        'memories/channel.md': ('channel', 'input_channel', {'target_pages': ['memories/hub.md']}, ''),
        'memories/hub.md': ('hub', 'context_hub', {}, '[Consumer](consumer.md)\n[Other](other.md)\n'),
        'memories/consumer.md': ('consumer', 'concept', {'source_refs': ['source-synthetic']}, ''),
        'memories/unlinked.md': ('unlinked', 'concept', {'source_refs': ['source-synthetic']}, ''),
        'memories/by-path.md': ('by-path', 'concept', {'source_refs': ['memories/sources/synthetic.md']}, ''),
        'memories/requirement.md': ('requirement', 'concept', {'information_requirements': [{
            'target': 'memories/sources/synthetic.md', 'fields': ['*'],
            'temporal': 'current', 'max_age_days': 30}]}, ''),
        'memories/other.md': ('other', 'concept', {}, ''),
    }
    for path, (page_id, page_type, fields, body) in pages.items():
        write(root, path, '---\n' + yaml.safe_dump({'page_id': page_id, 'page_type': page_type, **fields})
              + '---\n# ' + page_id + '\n' + body)
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'connected source and subjects')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=git(root, 'rev-parse', 'HEAD'),
        entry_folder='.', entry_index='index.md', source_ref='source.txt',
        context_selection={'source_page': 'memories/sources/synthetic.md', 'omit_root_entity': True})
    return binding, args


def test_source_connections_discover_hub_consumers_and_survive_readback(prepared_repo):
    root, _ = prepared_repo
    binding, args = connected(root)
    prepared = prepare(root, binding, **args, source_context='system')
    request = prepared['request']
    selection = request['source_authorization']['context_selection']
    assert selection['source_config'] == 'memories/config.md'
    assert selection['input_channel'] == 'memories/channel.md'
    assert request['target_pages'] == ['memories/hub.md']
    sample = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    row = request['chunks'][0]
    result = {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
        **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
        'perspectives_required': [], 'perspectives': {}, 'entities': [], 'claims': []}
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    assert record(root, binding, **args, **ids, results=[result])['recorded'] == 1
    event = ('memories/system/ingestion/events/2026-11-04-'
        + hashlib.sha256(ids['source_id'].encode()).hexdigest() + '-' + ids['request_id'] + '.md')
    output = consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
        event_target=event, date=dt.date(2026, 11, 4))
    assert output['integration'] == 'pending review and incorporation'
    readback = inspect(root, binding, **args, **ids, view='integration', candidates=[])
    impact = readback['packet']['impact']
    assert impact['must_update'] == ['memories/hub.md']
    assert impact['should_review'] == ['memories/by-path.md', 'memories/consumer.md', 'memories/requirement.md', 'memories/unlinked.md']
    assert 'memories/other.md' not in impact['must_update'] + impact['should_review']
    assert {row['path'] for row in readback['packet']['candidate_provenance']} == {
        'memories/hub.md', 'memories/by-path.md', 'memories/consumer.md', 'memories/other.md',
        'memories/requirement.md', 'memories/unlinked.md'}


def test_connected_configuration_is_authorized_before_read_or_capture(prepared_repo, monkeypatch):
    root, _ = prepared_repo
    binding, args = connected(root)
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access']['.']['policy']['deny'] = {'read': ['memories/config.md']}
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'deny configuration')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    args['approved_revision'] = git(root, 'rev-parse', 'HEAD')
    from wiki_core.repository_reader import RepositoryReader
    original = RepositoryReader.read
    def guarded(reader, ref, *a, **kw):
        assert ref != 'memories/config.md', 'denied configuration body opened'
        return original(reader, ref, *a, **kw)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    monkeypatch.setattr('wiki_core.ingest.protected._capture', lambda *a, **kw: pytest.fail('source captured'))
    with pytest.raises(ValueError):
        prepare(root, binding, **args, source_context='system')
    assert not (root / 'data/derived').exists()


def test_discovery_does_not_open_denied_consumer(prepared_repo, monkeypatch):
    root, _ = prepared_repo
    binding, args = connected(root)
    write(root, 'memories/private.md', '---\npage_id: private\npage_type: concept\nsource_refs: [source-synthetic]\n---\n')
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access']['.']['policy']['deny'] = {'read': ['memories/private.md']}
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'deny consumer')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    args['approved_revision'] = git(root, 'rev-parse', 'HEAD')
    request = prepare(root, binding, **args, source_context='system')['request']
    from wiki_core.ingest.protected import _authority, _connected_candidates
    from wiki_core.repository_reader import RepositoryReader
    original = RepositoryReader.read
    def guarded(reader, ref, *a, **kw):
        assert ref != 'memories/private.md', 'denied consumer body opened'
        return original(reader, ref, *a, **kw)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    _, policy, _, _ = _authority(root, binding, '.', args['approved_revision'], '.', 'index.md', 100000)
    refs, missing = _connected_candidates(root, policy, '.', '.', args['approved_revision'], request, [])
    assert 'memories/unlinked.md' in refs
    assert 'memories/private.md' not in refs
    assert missing
