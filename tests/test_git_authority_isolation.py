"""Adversarial Git configuration cannot redirect revision-bound wiki reads."""
from pathlib import Path
import subprocess

import pytest
import yaml

from wiki_core.context_integration import _git as integration_git
from wiki_core.context_policy import PolicyError, git_file, load_policy
from wiki_core.repository_reader import RepositoryReadError, RepositoryReader
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.repo_read import read_independent_repo
from wiki_core import git_env
from wiki_core import context_policy
from wiki_core.git_safety import GitSafetyError
from wiki_core.process_safety import ProcessSafetyError


def git(root, *args, input=None):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, input=input).strip()


def setup_repo(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Fixture')
    git(root, 'config', 'user.email', 'fixture@example.test')
    doc = {'schema_version': 'wiki.context/v1', 'id': 'root', 'parent': None,
           'root': '.', 'purpose': 'synthetic', 'owner': 'operator',
           'instructions': [], 'skills': [], 'templates': [],
           'policy': {'read': ['self'], 'write': ['self'], 'capabilities': [],
                      'deny': {}, 'publication': []}, 'imports': [], 'exports': []}
    (root / 'context.yaml').write_text(yaml.safe_dump(doc), encoding='utf-8')
    (root / 'page.md').write_text('Original synthetic content.\n', encoding='utf-8')
    (root / 'AGENTS.md').write_text('Read the index.\n', encoding='utf-8')
    (root / 'README.md').write_text('Synthetic root index.\n', encoding='utf-8')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'fixture')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    return doc


def replace_blob(root: Path, path: str, text: str):
    blob = git(root, 'rev-parse', 'HEAD:' + path)
    replacement = git(root, 'hash-object', '-w', '--stdin', input=text)
    git(root, 'replace', blob, replacement)


def test_replace_refs_cannot_change_authority_or_revision_bound_text(tmp_path):
    repo = tmp_path / 'wiki'
    doc = setup_repo(repo)
    head = git(repo, 'rev-parse', 'HEAD')
    replace_blob(repo, 'page.md', 'Altered content.\n')
    doc['policy']['read'] = []
    replace_blob(repo, 'context.yaml', yaml.safe_dump(doc))
    # Git without the shared environment sees the replacements.
    assert git(repo, 'show', 'HEAD:page.md') == 'Altered content.'
    reader = RepositoryReader(repo, head)
    assert reader.read('page.md')['text'] == 'Original synthetic content.\n'
    assert git_file(repo, head, 'page.md') == b'Original synthetic content.\n'
    assert load_policy(repo, head).effective['root']['read'] == ['.']
    assert integration_git(repo, 'show', 'HEAD:page.md') == b'Original synthetic content.\n'


def test_inherited_git_dir_and_worktree_cannot_redirect_explicit_root(tmp_path, monkeypatch):
    repo, other = tmp_path / 'wiki', tmp_path / 'other'
    setup_repo(repo)
    setup_repo(other)
    (other / 'page.md').write_text('Wrong repository.\n', encoding='utf-8')
    git(other, 'add', 'page.md')
    git(other, 'commit', '-qm', 'other')
    expected = git(repo, 'rev-parse', 'HEAD')
    monkeypatch.setenv('GIT_DIR', str(other / '.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(other))
    monkeypatch.setenv('GIT_OBJECT_DIRECTORY', str(other / '.git' / 'objects'))
    reader = RepositoryReader(repo)
    assert reader.revision == expected
    assert reader.read('page.md')['text'] == 'Original synthetic content.\n'
    assert load_policy(repo, expected).policy_revision == expected
    assert integration_git(repo, 'rev-parse', 'HEAD').decode().strip() == expected


def test_missing_promisor_objects_do_not_spawn_ssh(tmp_path, monkeypatch):
    repo = tmp_path / 'wiki'
    setup_repo(repo)
    page_blob = git(repo, 'rev-parse', 'HEAD:page.md')
    policy_blob = git(repo, 'rev-parse', 'HEAD:context.yaml')
    for blob in (page_blob, policy_blob):
        (repo / '.git' / 'objects' / blob[:2] / blob[2:]).unlink()
    git(repo, 'remote', 'add', 'origin', 'ssh://git@example.test/fixture/repo.git')
    git(repo, 'config', 'remote.origin.promisor', 'true')
    git(repo, 'config', 'remote.origin.partialclonefilter', 'blob:none')
    git(repo, 'config', 'extensions.partialClone', 'origin')
    marker = tmp_path / 'ssh-attempted'
    ssh = tmp_path / 'ssh-stub'
    ssh.write_text('#!/bin/sh\nprintf attempted > "' + str(marker) + '"\nexit 1\n')
    ssh.chmod(0o700)
    git(repo, 'config', 'core.sshCommand', str(ssh))
    reader = RepositoryReader(repo, 'HEAD')
    with pytest.raises(RepositoryReadError):
        reader.read('page.md')
    with pytest.raises(PolicyError):
        load_policy(repo, 'HEAD')
    assert not marker.exists()


def test_fake_git_and_trace_environment_cannot_intercept_v2_or_repo_reader(tmp_path, monkeypatch):
    repo = tmp_path / 'wiki'
    setup_repo(repo)
    git(repo, 'remote', 'add', 'origin', 'https://example.test/fixture/repo.git')
    fake_dir = tmp_path / 'bin'
    fake_dir.mkdir()
    marker = tmp_path / 'fake-git-ran'
    fake = fake_dir / 'git'
    fake.write_text('#!/bin/sh\nprintf attempted > "' + str(marker) + '"\nexit 1\n')
    fake.chmod(0o700)
    trace = tmp_path / 'trace'
    monkeypatch.setenv('PATH', str(fake_dir))
    monkeypatch.setenv('GIT_TRACE', str(trace))
    monkeypatch.setenv('GIT_TRACE2_EVENT', str(trace))
    monkeypatch.setenv('GIT_CURL_VERBOSE', '1')
    assert load_folder_policy_v2(repo, 'HEAD').policy_revision == RepositoryReader(repo).revision
    assert read_independent_repo(repo, 'example.test/fixture/repo', 'HEAD', 'page.md')['text'].startswith('Original')
    assert not marker.exists()
    assert not trace.exists()


def test_windows_git_uses_fixed_locations_and_never_path(monkeypatch):
    monkeypatch.setattr(git_env.sys, 'platform', 'win32')
    seen = []
    def probe(candidate):
        seen.append(candidate)
        return candidate if len(seen) == 2 else None
    monkeypatch.setattr(git_env, '_existing_windows_git', probe)
    monkeypatch.setenv('PATH', r'C:\untrusted')
    assert git_env.local_git_executable() == git_env._WINDOWS_GIT_PATHS[1]
    assert seen == list(git_env._WINDOWS_GIT_PATHS)
    seen.clear()
    env = git_env.local_git_environment()
    assert r'C:\untrusted' not in env['PATH']
    assert env['SystemRoot'] == r'C:\Windows'
    assert env['GIT_NO_LAZY_FETCH'] == '1'
    assert env['GIT_ALLOW_PROTOCOL'] == ''
    monkeypatch.setattr(git_env, '_existing_windows_git', lambda _: None)
    with pytest.raises(GitSafetyError, match='trusted Git for Windows'):
        git_env.local_git_executable()


def test_nonwindows_git_uses_resolved_system_executable(monkeypatch):
    monkeypatch.setattr(git_env.sys, 'platform', 'linux')
    monkeypatch.setattr(git_env, 'resolved_git_executable', lambda: '/usr/bin/git')
    monkeypatch.setenv('PATH', '/untrusted')
    assert git_env.local_git_executable() == '/usr/bin/git'


def test_unsupported_git_option_fails_before_command(tmp_path, monkeypatch):
    repo = tmp_path / 'wiki'
    setup_repo(repo)
    marker = tmp_path / 'unprotected-command'
    stub = tmp_path / 'old-git'
    stub.write_text('#!/bin/sh\nif [ "$1" = "--no-lazy-fetch" ]; then exit 129; fi\n'
                    'printf attempted > "' + str(marker) + '"\nexit 0\n')
    stub.chmod(0o700)
    from wiki_core import repository_reader, context_policy
    monkeypatch.setattr(repository_reader, 'local_git_executable', lambda: str(stub))
    monkeypatch.setattr(context_policy, 'local_git_executable', lambda: str(stub))
    with pytest.raises(RepositoryReadError):
        RepositoryReader(repo)
    with pytest.raises(PolicyError):
        load_policy(repo, 'HEAD')
    assert not marker.exists()


def test_reader_rejects_large_blob_before_cat_file_body(tmp_path, monkeypatch):
    repo = tmp_path / 'wiki'
    setup_repo(repo)
    (repo / 'large.md').write_text('x' * 2_000_001, encoding='utf-8')
    git(repo, 'add', 'large.md')
    git(repo, 'commit', '-qm', 'large')
    reader = RepositoryReader(repo, 'HEAD')
    original = reader._git
    def guarded(*args):
        if args[:2] == ('cat-file', 'blob'):
            pytest.fail('blob body was loaded before size check')
        return original(*args)
    monkeypatch.setattr(reader, '_git', guarded)
    with pytest.raises(RepositoryReadError, match='repository file too large'):
        reader.read('large.md')


def test_policy_file_rejects_large_blob_before_show(tmp_path, monkeypatch):
    repo = tmp_path / 'wiki'
    setup_repo(repo)
    (repo / 'large.yaml').write_text('x' * 2_000_001, encoding='utf-8')
    git(repo, 'add', 'large.yaml')
    git(repo, 'commit', '-qm', 'large')
    original = context_policy._git
    def guarded(root, *args):
        if args and args[0] == 'show':
            pytest.fail('policy blob body was loaded before size check')
        return original(root, *args)
    monkeypatch.setattr(context_policy, '_git', guarded)
    with pytest.raises(PolicyError, match='Git object exceeds size limit'):
        context_policy.git_file(repo, 'HEAD', 'large.yaml')


def test_recursive_tree_output_limit_rejects_overflow_without_partial_result(tmp_path, monkeypatch):
    if git_env.sys.platform == 'win32':
        pytest.skip('pre-allocation tree bound is not yet implemented on Windows')
    repo = tmp_path / 'wiki'
    setup_repo(repo)
    tree = subprocess.check_output(['/usr/bin/git', '-C', str(repo), 'ls-tree', '-r', '-z', 'HEAD'])
    names = subprocess.check_output(['/usr/bin/git', '-C', str(repo), 'ls-tree', '-r', '-z', '--name-only', 'HEAD'])
    monkeypatch.setattr(git_env, 'GIT_TREE_OUTPUT_LIMIT', min(len(tree), len(names)) - 1)
    with pytest.raises(RepositoryReadError, match='tree enumeration unavailable or exceeded limit'):
        RepositoryReader(repo)
    with pytest.raises(PolicyError, match='tree enumeration unavailable or exceeded limit'):
        load_policy(repo, 'HEAD')
    monkeypatch.setattr(git_env, 'GIT_TREE_OUTPUT_LIMIT', len(tree))
    assert set(RepositoryReader(repo).paths) == {'AGENTS.md', 'README.md', 'context.yaml', 'page.md'}


def test_recursive_tree_timeout_fails_closed(tmp_path, monkeypatch):
    if git_env.sys.platform == 'win32':
        pytest.skip('POSIX bounded process timeout test')
    repo = tmp_path / 'wiki'
    setup_repo(repo)
    def timeout(*args, **kwargs):
        raise ProcessSafetyError('timeout', 'synthetic timeout')
    monkeypatch.setattr(git_env, 'run_bounded_process', timeout)
    with pytest.raises(RepositoryReadError, match='tree enumeration unavailable or exceeded limit'):
        RepositoryReader(repo)
    with pytest.raises(PolicyError, match='tree enumeration unavailable or exceeded limit'):
        load_policy(repo, 'HEAD')


def test_promisor_uploadpack_positive_control_and_v2_packet_fail_closed(tmp_path):
    repo = tmp_path / 'wiki'
    setup_repo(repo)
    (repo / 'AGENTS.md').write_text('Read the index.\n\n## Wiki v2: indexes\n\n- [Index](README.md)\n', encoding='utf-8')
    controls = {'schema_version': 'wiki.folder-controls/v2', 'controls': {
        '.': {'policy': {'read': ['self'], 'write': ['self'], 'capabilities': [],
                         'deny': {}, 'publication': []}, 'imports': [], 'exports': []}}}
    (repo / 'wiki-context-controls.yaml').write_text(yaml.safe_dump(controls), encoding='utf-8')
    git(repo, 'add', 'wiki-context-controls.yaml', 'AGENTS.md')
    git(repo, 'commit', '-qm', 'controls')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    blob = git(repo, 'rev-parse', 'HEAD:page.md')
    (repo / '.git' / 'objects' / blob[:2] / blob[2:]).unlink()
    remote = tmp_path / 'remote.git'
    remote.mkdir()
    git(remote, 'init', '--bare', '-q')
    marker = tmp_path / 'uploadpack-attempted'
    stub = tmp_path / 'uploadpack-stub'
    stub.write_text('#!/bin/sh\nprintf attempted > "' + str(marker) + '"\nexit 1\n')
    stub.chmod(0o700)
    git(repo, 'remote', 'add', 'origin', remote.as_uri())
    git(repo, 'config', 'protocol.file.allow', 'always')
    git(repo, 'config', 'remote.origin.uploadpack', str(stub))
    git(repo, 'config', 'remote.origin.promisor', 'true')
    git(repo, 'config', 'remote.origin.partialclonefilter', 'blob:none')
    git(repo, 'config', 'extensions.partialClone', 'origin')
    # Positive control proves this local fake promisor actually executes the
    # stub without the hardened environment; it never uses a network remote.
    subprocess.run(['/usr/bin/git', '-C', str(repo), 'cat-file', '-s', blob],
                   capture_output=True, timeout=10)
    assert marker.exists()
    marker.unlink()
    # Independent fallback: even if a Git version ignored the environment
    # lazy-fetch flag, its protocol allowlist denies the local upload-pack.
    env = git_env.local_git_environment()
    env.pop('GIT_NO_LAZY_FETCH')
    env['GIT_PROTOCOL_FROM_USER'] = '1'
    subprocess.run([git_env.local_git_executable(), '-C', str(repo), 'cat-file', '-s', blob],
                   env=env, capture_output=True, timeout=10)
    assert not marker.exists()
    policy = load_folder_policy_v2(repo, 'HEAD')
    evidence = [{'path': 'page.md', 'producer_folder': '.', 'reason': 'fixture',
                 'use': 'interpret', 'classification': 'internal'}]
    with pytest.raises((PolicyError, RepositoryReadError)):
        build_folder_packet_v2(repo, policy, '.', 10000, content_revision='HEAD', index_path='README.md',
                               task_id='x', goal='x', output='x', integrator='x', evidence=evidence)
    assert not marker.exists()
