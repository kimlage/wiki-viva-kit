"""A registered source keeps its declared routing through folder ingestion."""
import pytest
import yaml

from tests.test_protected_ingestion import AQAL_REFS, prepared_repo
from tests.test_folder_policy_core import repo, write, git
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.ingest.protected import prepare


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
        entry_folder='.', entry_index='index.md', source_ref='source.txt', perspective_refs=AQAL_REFS,
        context_selection={'source_page': 'memories/sources/synthetic.md', 'omit_root_entity': True})
    return binding, args


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
