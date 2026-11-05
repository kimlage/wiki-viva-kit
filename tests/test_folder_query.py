import json
from pathlib import Path

import pytest
import yaml

from tests.test_folder_policy_core import repo, enable_alpha, folder_policy, git, write
from wiki_core.context_packet import qualify_folder_context
from wiki_core.context_policy import PolicyError
from wiki_core.context_selection import authority_digest, normalize_query, reproduce_query, select_query
from wiki_core.repository_reader import RepositoryReader


def page(root, path, page_id, status='active'):
    body = {'page_id': page_id, 'page_type': 'claim', 'status': status, 'amount': 5}
    write(root, path, '---\n' + yaml.safe_dump(body) + '---\nSynthetic.\n')


@pytest.fixture
def query_repo(repo):
    enable_alpha(repo)
    write(repo, 'alpha/collection.md', '---\npage_id: collection\npage_type: context_hub\n---\n# Collection\n')
    page(repo, 'alpha/items/a.md', 'active')
    page(repo, 'alpha/items/b.md', 'inactive', status='inactive')
    page(repo, 'alpha/items/denied.md', 'denied')
    page(repo, 'alpha/items/clone/hidden.md', 'nested-clone')
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    config['context_access']['alpha']['policy']['deny'] = {'read': ['self/items/denied.md']}
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'query fixture')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    git(repo / 'alpha/items/clone', 'init', '-q')
    policy = folder_policy(repo)
    qualify_folder_context(repo, policy, 'alpha', 'alpha/aux', 'alpha/index.md', 100000)
    return repo, policy


def query():
    return {'target': 'alpha/collection.md', 'reason': 'selected', 'use': 'interpretation',
            'classification': 'context', 'query': {'scope': 'alpha/items', 'filters': {'status': 'active'},
            'field': 'amount', 'max_enumerated': 100, 'max_matches': 20, 'max_scan_bytes': 100000}}


def test_folder_query_excludes_denied_and_nested_before_blob_reads(query_repo, monkeypatch):
    root, policy = query_repo
    opened = []
    original = RepositoryReader.read
    def spy(self, path, **kwargs):
        opened.append(path)
        return original(self, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    reader = RepositoryReader(root, 'HEAD')
    receipt, anchor, members = select_query(policy, 'alpha', reader, query())
    assert receipt['authority_format'] == 'folder'
    assert receipt['coverage'] == 'authorized_owner_scope_excluding_nested_repositories_and_symlinks'
    assert [item['path'] for item in members] == ['alpha/items/a.md']
    assert receipt['enumerated'] == 2
    assert 'alpha/items/denied.md' not in opened
    assert 'alpha/items/clone/hidden.md' not in opened
    assert anchor['path'] == 'alpha/collection.md'


def test_folder_query_requires_prequalified_binding_and_matching_repo(query_repo, tmp_path, monkeypatch):
    root, policy = query_repo
    unqualified = folder_policy(root)
    reader = RepositoryReader(root, 'HEAD')
    monkeypatch.setattr(RepositoryReader, 'read', lambda *a, **kw: pytest.fail('unexpected blob read'))
    with pytest.raises(PolicyError, match='qualified folder authority unavailable'):
        select_query(unqualified, 'alpha', reader, query())
    other = tmp_path / 'other-repository'; other.mkdir()
    git(other, 'init', '-q'); git(other, 'config', 'user.name', 'Synthetic'); git(other, 'config', 'user.email', 'synthetic@example.invalid')
    write(other, 'other.md', '# Other\n'); git(other, 'add', '.'); git(other, 'commit', '-qm', 'other')
    with pytest.raises(PolicyError, match='qualified folder authority unavailable'):
        select_query(policy, 'alpha', RepositoryReader(other, 'HEAD'), query())


def test_folder_query_rechecks_trusted_ref_before_each_body(query_repo, monkeypatch):
    root, policy = query_repo
    reader = RepositoryReader(root, 'HEAD')
    future = git(root, 'commit-tree', 'HEAD^{tree}', '-p', 'HEAD', '-m', 'future')
    opened = []
    original = RepositoryReader.read
    def move_after_anchor(self, path, **kwargs):
        opened.append(path)
        item = original(self, path, **kwargs)
        if path == 'alpha/collection.md': git(root, 'update-ref', 'refs/remotes/origin/main', future)
        return item
    monkeypatch.setattr(RepositoryReader, 'read', move_after_anchor)
    with pytest.raises(PolicyError, match='policy changed during selection'):
        select_query(policy, 'alpha', reader, query())
    assert opened == ['alpha/collection.md']


def test_folder_query_rechecks_ref_after_blob_size_before_content(query_repo, monkeypatch):
    root, policy = query_repo
    reader = RepositoryReader(root, 'HEAD')
    future = git(root, 'commit-tree', 'HEAD^{tree}', '-p', 'HEAD', '-m', 'future')
    opened = []
    original_read = RepositoryReader.read
    original_size = RepositoryReader.blob_size
    def move_after_size(self, path):
        size = original_size(self, path)
        if path == 'alpha/items/a.md': git(root, 'update-ref', 'refs/remotes/origin/main', future)
        return size
    def spy_read(self, path, **kwargs):
        opened.append(path)
        return original_read(self, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'blob_size', move_after_size)
    monkeypatch.setattr(RepositoryReader, 'read', spy_read)
    with pytest.raises(PolicyError, match='policy changed during selection'):
        select_query(policy, 'alpha', reader, query())
    assert 'alpha/items/a.md' not in opened


def test_folder_query_rejects_symlinked_anchor_before_read(query_repo, monkeypatch):
    root, policy = query_repo
    anchor = root / 'alpha/collection.md'
    anchor.unlink()
    anchor.symlink_to('index.md')
    reader = RepositoryReader(root, 'HEAD')
    monkeypatch.setattr(RepositoryReader, 'read', lambda *a, **kw: pytest.fail('unexpected blob read'))
    with pytest.raises(PolicyError, match='query anchor unavailable'):
        select_query(policy, 'alpha', reader, query())


def test_folder_query_replays_only_explicit_current_folder_authority(query_repo, monkeypatch):
    root, policy = query_repo
    reader = RepositoryReader(root, 'HEAD')
    receipt, _, _ = select_query(policy, 'alpha', reader, query())
    opened = []
    original = RepositoryReader.read
    def spy(self, path, **kwargs):
        opened.append(path)
        return original(self, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(PolicyError, match='requires requalification'):
        reproduce_query(policy, 'alpha', reader, query(), policy_revision=receipt['policy_revision'],
                        expected_authority=receipt['authority_digest'])
    with pytest.raises(PolicyError, match='requires requalification'):
        reproduce_query(policy, 'alpha', reader, query(), policy_revision='0' * 40,
                        expected_authority=receipt['authority_digest'], authority_format='folder')
    assert opened == []
    replay, _, _ = reproduce_query(policy, 'alpha', reader, query(), policy_revision=receipt['policy_revision'],
                                   expected_authority=receipt['authority_digest'], authority_format='folder')
    assert replay == receipt


def test_folder_authority_digest_cannot_be_relabelled_as_v1(query_repo, monkeypatch):
    _root, policy = query_repo
    folder = authority_digest(policy, 'alpha', normalize_query(query()))
    monkeypatch.setattr(policy, 'format_version', None)
    v1 = authority_digest(policy, 'alpha', normalize_query(query()))
    assert folder != v1
    monkeypatch.setattr(RepositoryReader, 'read', lambda *a, **kw: pytest.fail('unexpected blob read'))
    with pytest.raises(PolicyError, match='authority format differs'):
        reproduce_query(policy, 'alpha', None, query(), policy_revision=policy.policy_revision,
                        expected_authority=folder, authority_format='folder')


def test_dynamic_audit_marks_legacy_receipt_unknown_without_read(repo, monkeypatch):
    from wiki_core.dynamic_query_audit import revalidate_affected
    from wiki_core.frontmatter import parse_frontmatter
    enable_alpha(repo)
    page(repo, 'alpha/consumer.md', 'consumer')
    page(repo, 'beta/hidden.md', 'hidden')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'consumers'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(repo, 'rev-parse', 'HEAD')
    policy = folder_policy(repo)
    qualify_folder_context(repo, policy, 'alpha', 'alpha/aux', 'alpha/index.md', 100000)
    documents = {name: (repo / name).read_text() for name in ('alpha/consumer.md', 'beta/hidden.md')}
    graph = {'documents': documents, 'nodes': {name: parse_frontmatter(text)[0] for name, text in documents.items()}}
    monkeypatch.setattr(RepositoryReader, 'read', lambda *a, **kw: pytest.fail('unexpected blob read'))
    affected = [{'path': name, 'requirement': {}, 'origin': 'current'} for name in documents]
    outcomes = revalidate_affected(repo, base=sha, head=sha, context_id='alpha', affected=affected,
                                   changed=set(), current=graph, policy=policy)
    assert outcomes == [{'path': 'alpha/consumer.md', 'state': 'unknown',
                         'reason': 'dynamic_query_requalification_required', 'seed': 'alpha/consumer.md'}]
    assert 'beta' not in json.dumps(outcomes)
