"""Synthetic evidence for revision-bound folder guidance, not authorization."""
import subprocess
from pathlib import Path

import pytest

from wiki_core.folder_context import FolderContextError, inspect_folder


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def put(root, path, body):
    dest = root / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding='utf-8')


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Synthetic Tester')
    git(tmp_path, 'config', 'user.email', 'synthetic@example.invalid')
    put(tmp_path, 'AGENTS.md', 'Root instruction')
    put(tmp_path, 'index.md', 'Root index')
    put(tmp_path, 'a/AGENTS.md', 'Context instruction')
    put(tmp_path, 'a/index.md', 'Context index')
    put(tmp_path, 'a/aux/nested/AGENTS.md', 'Nested regular')
    put(tmp_path, 'a/aux/nested/AGENTS.override.md', 'Nested override')
    put(tmp_path, 'a/aux/nested/index.md', 'Nested index')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'synthetic context')
    return tmp_path


def test_nested_chain_uses_git_revision_override_and_reads_indexes(repo):
    sha = git(repo, 'rev-parse', 'HEAD')
    put(repo, 'a/AGENTS.md', 'Uncommitted instruction')
    result = inspect_folder(repo, sha, 'a/aux/nested')
    assert result['revision'] == sha
    assert [c['folder'] for c in result['contexts']] == ['.', 'a', 'a/aux/nested']
    assert [c['instructions']['text'] for c in result['contexts']] == ['Root instruction', 'Context instruction', 'Nested override']
    assert result['index']['text'] == 'Nested index'
    assert all('index' not in c for c in result['contexts'])
    assert result['missing_indexes'] == []
    assert result['complete'] is True
    assert result['active_context'] == 'a/aux/nested'
    assert 'No access' in result['limitations'][1]


def test_missing_index_and_empty_override(repo):
    put(repo, 'a/AGENTS.override.md', ' \n')
    (repo / 'a/index.md').unlink()
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'empty and missing')
    result = inspect_folder(repo, 'HEAD', 'a')
    assert result['contexts'][-1]['instructions']['path'] == 'a/AGENTS.md'
    assert result['index'] is None
    assert result['missing_indexes'] == ['a']
    assert result['complete'] is False


def test_no_context_is_incomplete(repo):
    (repo / 'AGENTS.md').unlink()
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'remove root context')
    result = inspect_folder(repo, 'HEAD', '.')
    assert result['contexts'] == []
    assert result['active_context'] is None
    assert result['complete'] is False


def test_root_entry_map_requires_explicit_declared_selection(repo):
    (repo / 'index.md').unlink()
    put(repo, 'README.md', 'Project entry and wiki map')
    put(repo, 'AGENTS.md', 'Root instruction\n\n## Wiki v2: indexes\n\n- [Index](README.md)\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'root entry')
    assert inspect_folder(repo, 'HEAD', '.')['index'] is None
    result = inspect_folder(repo, 'HEAD', '.', index_path='README.md')
    assert result['index']['path'] == 'README.md'
    assert result['complete'] is True


def test_ancestor_indexes_are_not_read(repo, monkeypatch):
    from wiki_core import folder_context
    original = folder_context._blob
    def guarded(root, sha, path):
        if path in {'index.md', 'a/index.md'}:
            pytest.fail('ancestor index must not be read')
        return original(root, sha, path)
    monkeypatch.setattr(folder_context, '_blob', guarded)
    assert inspect_folder(repo, 'HEAD', 'a/aux/nested')['index']['text'] == 'Nested index'


def test_limit_fails_without_partial_result(repo):
    with pytest.raises(FolderContextError, match='exceeds byte limit'):
        inspect_folder(repo, 'HEAD', 'a', max_instruction_bytes=1)


@pytest.mark.parametrize('path', ['a/AGENTS.md', 'a/index.md'])
def test_secret_in_selected_content_fails_without_disclosing(repo, path):
    secret = 'AKIA' + 'IOSFODNN7EXAMPLE'
    put(repo, path, secret)
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'synthetic secret')
    with pytest.raises(FolderContextError, match='secret detected') as error:
        inspect_folder(repo, 'HEAD', 'a')
    assert secret not in str(error.value)


def test_rejects_untrusted_path_symlink_and_non_root(repo):
    with pytest.raises(FolderContextError):
        inspect_folder(repo, 'HEAD', '../outside')
    with pytest.raises(FolderContextError, match='Git root'):
        inspect_folder(repo / 'a', 'HEAD', '.')
    (repo / 'a/index.md').unlink()
    (repo / 'a/index.md').symlink_to('../index.md')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'symlink index')
    with pytest.raises(FolderContextError, match='regular Git blob'):
        inspect_folder(repo, 'HEAD', 'a')


def test_gitlink_is_not_a_context_tree(repo):
    # A gitlink names an independent repo rather than a directory in this tree.
    sha = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'update-index', '--add', '--cacheinfo', f'160000,{sha},a/independent')
    git(repo, 'commit', '-qm', 'independent repo')
    with pytest.raises(FolderContextError, match='not a Git tree'):
        inspect_folder(repo, 'HEAD', 'a/independent')
