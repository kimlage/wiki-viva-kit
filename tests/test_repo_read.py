from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from wiki_core.repo_read import RepoReadError, read_independent_repo, remote_identity
from wiki_core import repo_read as read_module


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'wiki_repo_read.py'


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'independent'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Fixture')
    git(root, 'config', 'user.email', 'fixture@example.test')
    git(root, 'remote', 'add', 'origin', 'https://example.test/group/project.git')
    (root / 'guide.md').write_text('# Guide\nUseful content.\n', encoding='utf-8')
    git(root, 'add', 'guide.md')
    git(root, 'commit', '-qm', 'synthetic fixture')
    return root


def cli(root, *, identity='example.test/group/project', revision='HEAD', path='guide.md'):
    return subprocess.run([sys.executable, str(SCRIPT), '--repo', str(root), '--identity', identity,
                           '--revision', revision, '--path', path], text=True, capture_output=True, timeout=10)


def test_independent_git_read_has_verified_origin_and_revision(repo):
    result = cli(repo)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data['repository'] == {'identity': 'example.test/group/project', 'remote_name': 'origin',
                                  'transport': 'https', 'identity_evidence': 'configured_origin_not_remote_authentication'}
    assert data['revision'] == git(repo, 'rev-parse', 'HEAD')
    assert data['path'] == 'guide.md'
    assert data['blob'] == git(repo, 'rev-parse', 'HEAD:guide.md')
    assert data['text'] == '# Guide\nUseful content.\n'
    assert 'caller_authorization_required' in data['access']
    assert 'project.git' not in result.stdout


def test_missing_repo_remote_and_wrong_target_are_explicit(repo, tmp_path):
    result = cli(tmp_path / 'missing')
    assert json.loads(result.stderr)['reason'] == 'repository_missing'
    (repo / 'child').mkdir()
    assert json.loads(cli(repo / 'child').stderr)['reason'] == 'repository_root_mismatch'
    assert json.loads(cli(repo, identity='example.test/group/another').stderr)['reason'] == 'repository_identity_mismatch'
    git(repo, 'remote', 'remove', 'origin')
    assert json.loads(cli(repo).stderr)['reason'] == 'origin_remote_unavailable'


@pytest.mark.parametrize('remote', [
    'https://user:password@example.test/group/project.git',
    'https://example.test/group/project.git?token=fake',
    'ssh://someone@example.test/group/project.git',
    'https://example.test/group/%2Fproject.git',
])
def test_remote_credentials_or_unsafe_parts_never_printed(repo, remote):
    git(repo, 'remote', 'set-url', 'origin', remote)
    result = cli(repo)
    assert result.returncode == 1
    assert result.stdout == ''
    assert json.loads(result.stderr)['reason'] == 'remote_invalid_or_unsafe'
    assert remote not in result.stderr


@pytest.mark.parametrize('text', [
    'https://example.test/resource?access_token=fake-secret',
    'https://user:password@example.test/private',
    'https%3A%2F%2Fuser%3Apassword%40example.test%2Fprivate',
    'https://storage.example.test/object?X-Goog-Credential=fake&amp;X-Goog-Signature=fake',
    'https://storage.example.test/object?x%252DgOoG%252DsIgNaTuRe%253Dfake',
    'https://storage.example.test/object?X-Amz-Signature=fake',
    'https://storage.example.test/object?SIG=fake',
])
def test_secret_bearing_content_is_never_returned(repo, text):
    (repo / 'secret.md').write_text(text, encoding='utf-8')
    git(repo, 'add', 'secret.md')
    git(repo, 'commit', '-qm', 'synthetic secret')
    result = cli(repo, path='secret.md')
    assert result.returncode == 1
    assert result.stdout == ''
    assert json.loads(result.stderr)['reason'] == 'selected_content_contains_access_secrets'
    assert text not in result.stderr


def test_explicit_file_revision_and_no_implicit_page_id(repo):
    old = git(repo, 'rev-parse', 'HEAD')
    (repo / 'guide.md').write_text('changed', encoding='utf-8')
    git(repo, 'add', 'guide.md')
    git(repo, 'commit', '-qm', 'change')
    assert read_independent_repo(repo, 'example.test/group/project', old, 'guide.md')['text'].startswith('# Guide')
    with pytest.raises(RepoReadError, match='repository_path_missing_or_unsupported'):
        read_independent_repo(repo, 'example.test/group/project', 'HEAD', 'nonexistent')
    with pytest.raises(RepoReadError, match='repository_revision_or_path_unavailable'):
        read_independent_repo(repo, 'example.test/group/project', 'not-a-ref', 'guide.md')


def test_ordinary_link_with_noncredential_query_is_readable(repo):
    (repo / 'ordinary.md').write_text('https://example.test/docs?page=2', encoding='utf-8')
    git(repo, 'add', 'ordinary.md')
    git(repo, 'commit', '-qm', 'ordinary link')
    result = cli(repo, path='ordinary.md')
    assert result.returncode == 0
    assert json.loads(result.stdout)['text'].endswith('?page=2')


def test_remote_ssh_identity_and_ambiguous_remote(repo):
    assert remote_identity('git@example.test:group/project.git') == ('example.test/group/project', 'ssh')
    assert remote_identity('ssh://git@example.test/group/project.git') == ('example.test/group/project', 'ssh')
    git(repo, 'remote', 'set-url', '--add', 'origin', 'https://example.test/group/second.git')
    assert json.loads(cli(repo).stderr)['reason'] == 'origin_remote_ambiguous'


def test_environment_cannot_redirect_git_and_replace_refs_are_ignored(repo, tmp_path, monkeypatch):
    old_blob = git(repo, 'rev-parse', 'HEAD:guide.md')
    replacement = subprocess.check_output(['git', '-C', str(repo), 'hash-object', '-w', '--stdin'],
                                          input='replacement', text=True).strip()
    git(repo, 'replace', old_blob, replacement)
    fake = tmp_path / 'other'
    fake.mkdir()
    git(fake, 'init', '-q')
    monkeypatch.setenv('GIT_DIR', str(fake / '.git'))
    result = cli(repo)
    assert result.returncode == 0
    assert json.loads(result.stdout)['text'] == '# Guide\nUseful content.\n'


def test_invalid_arguments_do_not_echo_credential_input():
    credential = 'https://user:password@example.test/private'
    result = subprocess.run([sys.executable, str(SCRIPT), '--unrecognized', credential],
                            text=True, capture_output=True)
    assert result.returncode == 2
    assert json.loads(result.stderr)['reason'] == 'invalid_arguments'
    assert credential not in result.stderr + result.stdout


def test_large_blob_rejected_before_document_is_loaded(repo, monkeypatch):
    (repo / 'large.md').write_text('x' * 2_000_001, encoding='utf-8')
    git(repo, 'add', 'large.md')
    git(repo, 'commit', '-qm', 'large synthetic blob')
    def must_not_read(*args, **kwargs):
        pytest.fail('oversized blob must be rejected before document read')
    monkeypatch.setattr(read_module._LocalRepositoryReader, '_document', must_not_read)
    with pytest.raises(RepoReadError, match='repository_file_too_large'):
        read_independent_repo(repo, 'example.test/group/project', 'HEAD', 'large.md')
    result = cli(repo, path='large.md')
    assert result.returncode == 1 and result.stdout == ''
    assert json.loads(result.stderr)['reason'] == 'repository_file_too_large'


def test_missing_promisor_blob_fails_without_lazy_fetch(repo, tmp_path, monkeypatch):
    blob = git(repo, 'rev-parse', 'HEAD:guide.md')
    obj = repo / '.git' / 'objects' / blob[:2] / blob[2:]
    assert obj.is_file()
    obj.unlink()
    git(repo, 'config', 'remote.origin.promisor', 'true')
    git(repo, 'config', 'remote.origin.partialclonefilter', 'blob:none')
    git(repo, 'config', 'extensions.partialClone', 'origin')
    marker = tmp_path / 'ssh-attempted'
    ssh = tmp_path / 'ssh-stub'
    ssh.write_text('#!/bin/sh\nprintf attempted > "' + str(marker) + '"\nexit 1\n')
    ssh.chmod(0o700)
    git(repo, 'config', 'core.sshCommand', str(ssh))
    git(repo, 'remote', 'set-url', 'origin', 'ssh://git@example.test/group/project.git')
    result = cli(repo)
    assert result.returncode == 1 and result.stdout == ''
    assert json.loads(result.stderr)['reason'] == 'repository_revision_or_path_unavailable'
    assert not marker.exists()
