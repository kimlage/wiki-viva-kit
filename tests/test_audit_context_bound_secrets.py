"""Synthetic, host-bound secret-gate checks; no consumer data or credentials."""
from __future__ import annotations

import builtins
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import scripts.wiki_audit as audit
from wiki_core.context_packet import qualify_folder_context
from wiki_core.context_policy import load_policy
from wiki_core.git_env import local_git_tree


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()


@pytest.fixture
def case(tmp_path, monkeypatch):
    root = tmp_path / 'synthetic-wiki'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Synthetic')
    git(root, 'config', 'user.email', 'synthetic@example.invalid')
    (root / 'AGENTS.md').write_text('# Synthetic instructions\n')
    (root / 'index.md').write_text('# Synthetic index\n')
    (root / 'public.md').write_text('# Synthetic allowed document\n')
    (root / 'restricted').mkdir()
    (root / 'restricted' / 'example.md').write_text('# Synthetic denied document\n')
    grant = {'read': ['self'], 'write': ['self'], 'capabilities': [],
             'deny': {'read': ['self/restricted']}, 'publication': []}
    config = {'context_access': {'.': {'owner': 'Synthetic owner', 'policy': grant}}}
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'synthetic approved baseline')
    revision = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', revision)
    monkeypatch.setattr(audit, 'ROOT', root)
    monkeypatch.setenv('WIKI_COORDINATION_ALLOWED_CONTEXTS', '.')
    monkeypatch.setenv('WIKI_COORDINATION_TRUSTED_REF', 'refs/remotes/origin/main')
    monkeypatch.delenv('WIKI_COORDINATION_CONTEXT_MODE', raising=False)
    monkeypatch.delenv('WIKI_COORDINATION_MANIFEST', raising=False)
    monkeypatch.delenv('WIKI_COORDINATION_REPOSITORY_GRANTS', raising=False)
    return {'root': root, 'revision': revision, 'config': config}


def commit_policy(case, *, deny=None):
    root, config = case['root'], case['config']
    config['context_access']['.']['policy']['deny'] = {'read': deny or []}
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'synthetic policy update')
    revision = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', revision)
    case['revision'] = revision
    return revision


def selection_digest(root, revision, *, context='.', trusted_ref='refs/remotes/origin/main'):
    names = set()
    for args in (('ls-files', '-z'), ('ls-files', '--others', '--exclude-standard', '-z')):
        data = local_git_tree(root, '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
                              '-c', 'core.hooksPath=/dev/null', '-c', 'core.useReplaceRefs=false', *args)
        names.update(os.fsdecode(raw) for raw in data.split(b'\0') if raw)
    candidates = [rel for rel in sorted(names) if not rel.startswith(audit.SECRET_SCAN_SKIP_PREFIXES)
                  and Path(rel).suffix.lower() in audit.TEXT_SCAN_SUFFIXES]
    identity = {'schema_version': 'wiki.audit-secrets-selection/v1', 'context_id': context,
                'policy_revision': revision, 'trusted_ref': trusted_ref,
                'check': 'secrets', 'paths': candidates}
    payload = json.dumps(identity, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def invoke(case, monkeypatch, *extra, guard='.', revision=None, selection='auto'):
    args = ['wiki_audit.py', *extra]
    if guard is not None:
        approved = revision or case['revision']
        args += ['--context-guard', guard, '--context-policy-revision', approved]
        if selection == 'auto':
            # Denied policy is rejected before inventory; no metadata bootstrap
            # is needed to supply this intentionally invalid placeholder.
            policy = case['config']['context_access']['.']['policy']
            selection = ('0' * 64 if policy.get('deny', {}).get('read')
                         else selection_digest(case['root'], approved, context=guard))
        if selection is not None:
            args += ['--context-selection-sha256', selection]
    monkeypatch.setattr(sys, 'argv', args)
    try:
        return audit.main()
    except SystemExit as exc:
        return exc.code


def test_denied_selected_document_blocks_before_any_scan(case, monkeypatch, capsys):
    root = case['root']
    policy = load_policy(root, case['revision'], 'wiki.config.yaml')
    qualify_folder_context(root, policy, '.', '.', 'index.md', 100_000)
    assert not policy.permits('.', 'read', 'restricted/example.md')
    assert policy.permits('.', 'read', 'public.md')
    opened = []
    original = audit.scan_file
    monkeypatch.setattr(audit, 'scan_file', lambda path: (opened.append(Path(path)), original(path))[1])
    status = invoke(case, monkeypatch, '--only', 'secrets')
    output = capsys.readouterr().out.lower()
    assert status != 0
    assert not opened, 'the complete selection must qualify before any body scan'
    assert 'coverage' in output and ('unavailable' in output or 'incomplete' in output)
    assert '0 error(s)' not in output


def test_approved_full_selection_scans_tracked_and_untracked(case, monkeypatch, capsys):
    root = case['root']
    commit_policy(case)
    (root / 'untracked.txt').write_text('Synthetic untracked fixture\n')
    opened = []
    original = audit.scan_file
    monkeypatch.setattr(audit, 'scan_file', lambda path: (opened.append(Path(path)), original(path))[1])
    assert invoke(case, monkeypatch, '--only', 'secrets', '--check') == 0
    assert {root / 'public.md', root / 'restricted/example.md', root / 'untracked.txt'} <= set(opened)
    capsys.readouterr()


def test_secret_finding_still_fails_gate(case, monkeypatch, capsys):
    commit_policy(case)
    # Split the public synthetic pattern so the test file is not itself a secret.
    (case['root'] / 'public.md').write_text('synthetic key: ' + 'AKIA' + 'IOSFODNN7EXAMPLE' + '\n')
    assert invoke(case, monkeypatch, '--only', 'secrets', '--check') != 0
    assert 'secret' in capsys.readouterr().out.lower()


@pytest.mark.parametrize('condition', ['missing_binding', 'stale_revision', 'wrong_context'])
def test_binding_and_current_approved_revision_are_required(case, monkeypatch, capsys, condition):
    opened = []
    monkeypatch.setattr(audit, 'scan_file', lambda path: opened.append(Path(path)) or [])
    old = case['revision']
    if condition == 'missing_binding':
        monkeypatch.delenv('WIKI_COORDINATION_ALLOWED_CONTEXTS')
    elif condition == 'stale_revision':
        commit_policy(case)
    else:
        monkeypatch.setenv('WIKI_COORDINATION_ALLOWED_CONTEXTS', 'unrelated')
    assert invoke(case, monkeypatch, '--only', 'secrets', revision=old) != 0
    assert opened == []
    assert '0 error(s)' not in capsys.readouterr().out.lower()


@pytest.mark.parametrize('extra', [(), ('--only', 'old_paths'), ('--only', 'secrets', '--public-export')])
def test_narrow_route_refuses_global_other_checks_and_public_export(case, monkeypatch, capsys, extra):
    opened = []
    monkeypatch.setattr(audit, 'scan_file', lambda path: opened.append(Path(path)) or [])
    assert invoke(case, monkeypatch, *extra) != 0
    assert not opened
    assert '0 error(s)' not in capsys.readouterr().out.lower()


def test_guarded_cli_refuses_all_unqualified_legacy_checks_before_bootstrap(case, monkeypatch, capsys):
    """The guarded route never silently falls back to real legacy readers."""
    root = case['root']
    (root / '.gitignore').write_text('ignored/\n')
    git(root, 'add', '.gitignore')
    git(root, 'commit', '-qm', 'synthetic intermediate message')
    (root / 'public.md').write_text('synthetic staged input\n')
    git(root, 'add', 'public.md')
    (root / 'public.md').write_text('synthetic unstaged input\n')
    (root / 'ignored').mkdir()
    (root / 'ignored' / 'sample.txt').write_text('synthetic ignored input\n')

    def unexpected(*_args, **_kwargs):
        pytest.fail('unqualified check reached bootstrap or target content')

    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if path.is_relative_to(root):
            unexpected()
        return original_open(path, *args, **kwargs)

    def guarded_file_open(original):
        def invoke(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(file))
                if path.is_absolute() and path.is_relative_to(root):
                    unexpected()
            return original(file, *args, **kwargs)
        return invoke

    monkeypatch.setattr(Path, 'open', guarded_open)
    monkeypatch.setattr(builtins, 'open', guarded_file_open(builtins.open))
    monkeypatch.setattr(os, 'open', guarded_file_open(os.open))
    monkeypatch.setattr(audit, 'load_config', unexpected)
    monkeypatch.setattr(audit, '_audit_git_inventory', unexpected)
    monkeypatch.setattr(audit, '_context_bound_audit_inventory', unexpected)
    monkeypatch.setattr(audit, '_audit_read_text', unexpected)
    monkeypatch.setattr(audit, '_audit_read_bytes', unexpected)
    monkeypatch.setattr(subprocess, 'run', unexpected)
    monkeypatch.setattr(subprocess, 'check_output', unexpected)
    monkeypatch.setattr(subprocess, 'Popen', unexpected)
    checks = [name for name in audit.CHECK_NAMES if name != 'secrets']
    assert 'action_state_transitions' in checks and 'source_lifecycle_transitions' in checks
    for args in [(), *(('--only', name) for name in checks),
                 ('--only', 'secrets,action_state_transitions')]:
        assert invoke(case, monkeypatch, *args) != 0
        output = capsys.readouterr().out.lower()
        assert 'coverage unavailable' in output and 'not completed' in output
        assert '0 error(s)' not in output


def test_other_owner_not_inferred_from_root_context(case, monkeypatch, capsys):
    root, config = case['root'], case['config']
    config['context_access']['.']['policy']['deny'] = {'read': []}
    config['context_access']['owned'] = {'owner': 'Another synthetic owner', 'policy': {
        'read': ['self'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []}}
    (root / 'owned').mkdir()
    (root / 'owned/AGENTS.md').write_text('# Synthetic child instructions\n')
    (root / 'owned/index.md').write_text('# Synthetic child index\n')
    (root / 'owned/document.md').write_text('# Synthetic child document\n')
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'synthetic separate owner')
    case['revision'] = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', case['revision'])
    opened = []
    monkeypatch.setattr(audit, 'scan_file', lambda path: opened.append(Path(path)) or [])
    assert invoke(case, monkeypatch, '--only', 'secrets') != 0
    assert opened == []
    assert '0 error(s)' not in capsys.readouterr().out.lower()


def test_symlink_candidate_fails_before_any_scan(case, monkeypatch, capsys):
    root = case['root']
    commit_policy(case)
    try:
        (root / 'linked.md').symlink_to(root / 'public.md')
    except (OSError, NotImplementedError):
        pytest.skip('symlink creation is unavailable on this host')
    opened = []
    monkeypatch.setattr(audit, 'scan_file', lambda path: opened.append(Path(path)) or [])
    assert invoke(case, monkeypatch, '--only', 'secrets') != 0
    assert opened == []
    assert '0 error(s)' not in capsys.readouterr().out.lower()


def test_tracked_candidate_deleted_during_scan_fails_coverage(case, monkeypatch, capsys):
    root = case['root']
    commit_policy(case)
    selected = root / 'restricted/example.md'
    scanned = []
    original = audit.scan_file
    def concurrent_delete(path):
        scanned.append(Path(path))
        if len(scanned) == 1:
            selected.unlink()
        return original(path)
    monkeypatch.setattr(audit, 'scan_file', concurrent_delete)
    assert invoke(case, monkeypatch, '--only', 'secrets') != 0
    assert scanned, 'the synthetic deletion occurs after a legitimate scan starts'
    output = capsys.readouterr().out.lower()
    assert 'coverage' in output and ('unavailable' in output or 'incomplete' in output)
    assert '0 error(s)' not in output


def test_tracked_candidate_absent_before_scan_fails_without_any_scan(case, monkeypatch, capsys):
    commit_policy(case)
    (case['root'] / 'restricted/example.md').unlink()
    scanned = []
    monkeypatch.setattr(audit, 'scan_file', lambda path: scanned.append(Path(path)) or [])
    assert invoke(case, monkeypatch, '--only', 'secrets') != 0
    assert not scanned
    output = capsys.readouterr().out.lower()
    assert 'coverage' in output and ('unavailable' in output or 'incomplete' in output)


def test_denied_untracked_text_blocks_before_any_scan(case, monkeypatch, capsys):
    root = case['root']
    git(root, 'rm', '-q', 'restricted/example.md')
    git(root, 'commit', '-qm', 'remove synthetic tracked restricted item')
    case['revision'] = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', case['revision'])
    (root / 'restricted').mkdir(exist_ok=True)
    (root / 'restricted/untracked.txt').write_text('synthetic untracked denied input\n')
    scanned = []
    monkeypatch.setattr(audit, 'scan_file', lambda path: scanned.append(Path(path)) or [])
    assert invoke(case, monkeypatch, '--only', 'secrets') != 0
    assert not scanned
    output = capsys.readouterr().out.lower()
    assert 'coverage' in output and ('unavailable' in output or 'incomplete' in output)


def test_deny_refuses_before_git_inventory_or_denied_ignore_read(case, monkeypatch, capsys):
    root = case['root']
    ignore = root / 'restricted/.gitignore'
    ignore.write_text('synthetic-ignored.txt\n')
    git(root, 'add', 'restricted/.gitignore')
    git(root, 'commit', '-qm', 'synthetic denied ignore file')
    case['revision'] = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', case['revision'])
    inventory_calls, scanned, direct_reads = [], [], []
    original_inventory = audit._context_bound_audit_inventory
    original_text, original_bytes = Path.read_text, Path.read_bytes
    def inventory_spy():
        inventory_calls.append(True)
        return original_inventory()
    def read_text_spy(path, *args, **kwargs):
        if path == ignore:
            direct_reads.append('text')
        return original_text(path, *args, **kwargs)
    def read_bytes_spy(path, *args, **kwargs):
        if path == ignore:
            direct_reads.append('bytes')
        return original_bytes(path, *args, **kwargs)
    monkeypatch.setattr(audit, '_context_bound_audit_inventory', inventory_spy)
    monkeypatch.setattr(audit, 'scan_file', lambda path: scanned.append(Path(path)) or [])
    monkeypatch.setattr(Path, 'read_text', read_text_spy)
    monkeypatch.setattr(Path, 'read_bytes', read_bytes_spy)
    assert invoke(case, monkeypatch, '--only', 'secrets') != 0
    assert inventory_calls == []
    assert scanned == [] and direct_reads == []
    output = capsys.readouterr().out.lower()
    assert 'coverage' in output and ('unavailable' in output or 'incomplete' in output)
    assert '0 error(s)' not in output


def test_deny_outside_candidate_inventory_still_fails_before_inventory(case, monkeypatch, capsys):
    commit_policy(case, deny=['self/not-in-inventory'])
    inventory_calls, scanned = [], []
    original_inventory = audit._context_bound_audit_inventory
    def inventory_spy():
        inventory_calls.append(True)
        return original_inventory()
    monkeypatch.setattr(audit, '_context_bound_audit_inventory', inventory_spy)
    monkeypatch.setattr(audit, 'scan_file', lambda path: scanned.append(Path(path)) or [])
    assert invoke(case, monkeypatch, '--only', 'secrets') != 0
    assert inventory_calls == [] and scanned == []
    output = capsys.readouterr().out.lower()
    assert 'coverage' in output and ('unavailable' in output or 'incomplete' in output)


def test_contaminated_git_environment_cannot_replace_authorized_inventory(case, monkeypatch, capsys):
    root = case['root']
    commit_policy(case)
    other = root.parent / 'different-synthetic-repository'
    other.mkdir()
    git(other, 'init', '-q')
    git(other, 'config', 'user.name', 'Synthetic')
    git(other, 'config', 'user.email', 'synthetic@example.invalid')
    (other / 'other.txt').write_text('synthetic unrelated text\n')
    git(other, 'add', '.')
    git(other, 'commit', '-qm', 'other synthetic repository')
    fakebin = root.parent / 'synthetic-path'
    fakebin.mkdir()
    marker = root.parent / 'fake-git-ran'
    fakegit = fakebin / 'git'
    fakegit.write_text('#!/bin/sh\nprintf fake > "' + str(marker) + '"\nexit 0\n')
    fakegit.chmod(0o755)
    monkeypatch.setenv('GIT_DIR', str(other / '.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(other))
    monkeypatch.setenv('GIT_INDEX_FILE', str(other / '.git/index'))
    monkeypatch.setenv('PATH', str(fakebin))
    scanned = []
    original = audit.scan_file
    def record(path):
        scanned.append(Path(path))
        return original(path)
    monkeypatch.setattr(audit, 'scan_file', record)
    status = invoke(case, monkeypatch, '--only', 'secrets')
    output = capsys.readouterr().out.lower()
    assert not marker.exists(), 'an executable inherited from PATH must not run'
    if status == 0:
        assert root / 'public.md' in scanned
        assert root / 'restricted/example.md' in scanned
        assert 'not a global audit' in output
    else:
        assert 'coverage' in output and ('unavailable' in output or 'incomplete' in output)
        assert '0 error(s)' not in output


def test_local_git_fsmonitor_hook_cannot_execute(case, monkeypatch, capsys):
    if sys.platform == 'win32':
        pytest.skip('synthetic POSIX fsmonitor hook is not executable on Windows')
    root = case['root']
    commit_policy(case)
    hook = root.parent / 'synthetic-fsmonitor-hook'
    marker = root.parent / 'synthetic-fsmonitor-ran'
    hook.write_text('#!/bin/sh\nprintf invoked > "' + str(marker) + '"\nexit 1\n')
    hook.chmod(0o755)
    git(root, 'config', 'core.fsmonitor', str(hook))
    # Prove the local Git setup is capable of executing the hook before the
    # guarded audit, so the negative assertion is meaningful.
    git(root, 'status', '--porcelain')
    if not marker.exists():
        pytest.skip('this Git does not invoke the synthetic fsmonitor hook')
    marker.unlink()
    status = invoke(case, monkeypatch, '--only', 'secrets')
    output = capsys.readouterr().out.lower()
    assert not marker.exists(), 'the guarded audit must not invoke fsmonitor hooks'
    if status != 0:
        assert 'coverage' in output and ('unavailable' in output or 'incomplete' in output)
    else:
        assert 'not a global audit' in output


def test_untracked_nested_repository_blocks_before_any_scan(case, monkeypatch, capsys):
    root = case['root']
    commit_policy(case)
    nested = root / 'synthetic-nested'
    nested.mkdir()
    git(nested, 'init', '-q')
    (nested / 'content.md').write_text('# Synthetic nested repository content\n')
    inventory = git(root, 'ls-files', '--others', '--exclude-standard', '-z')
    assert 'synthetic-nested/' in inventory
    scanned = []
    monkeypatch.setattr(audit, 'scan_file', lambda path: scanned.append(Path(path)) or [])
    assert invoke(case, monkeypatch, '--only', 'secrets') != 0
    assert scanned == []
    output = capsys.readouterr().out.lower()
    assert 'coverage' in output and ('unavailable' in output or 'incomplete' in output)
    assert '0 error(s)' not in output


@pytest.mark.parametrize('selection', [None, '0' * 64])
def test_missing_or_wrong_approved_selection_refuses_before_scan(case, monkeypatch, capsys, selection):
    commit_policy(case)
    scanned = []
    monkeypatch.setattr(audit, 'scan_file', lambda path: scanned.append(Path(path)) or [])
    assert invoke(case, monkeypatch, '--only', 'secrets', selection=selection) != 0
    assert scanned == []
    assert 'coverage unavailable' in capsys.readouterr().out.lower()


def test_expanded_inventory_requires_new_approval_before_scan(case, monkeypatch, capsys):
    commit_policy(case)
    approved = selection_digest(case['root'], case['revision'])
    (case['root'] / 'additional-untracked.txt').write_text('Synthetic added selection\n')
    scanned = []
    monkeypatch.setattr(audit, 'scan_file', lambda path: scanned.append(Path(path)) or [])
    assert invoke(case, monkeypatch, '--only', 'secrets', selection=approved) != 0
    assert scanned == []
    assert 'coverage unavailable' in capsys.readouterr().out.lower()


def test_policy_revision_change_invalidates_prior_selection_approval(case, monkeypatch, capsys):
    commit_policy(case)
    approved = selection_digest(case['root'], case['revision'])
    case['config']['synthetic_change'] = 'different approved policy revision'
    (case['root'] / 'wiki.config.yaml').write_text(yaml.safe_dump(case['config']))
    git(case['root'], 'add', 'wiki.config.yaml')
    git(case['root'], 'commit', '-qm', 'new synthetic approved revision')
    case['revision'] = git(case['root'], 'rev-parse', 'HEAD')
    git(case['root'], 'update-ref', 'refs/remotes/origin/main', case['revision'])
    scanned = []
    monkeypatch.setattr(audit, 'scan_file', lambda path: scanned.append(Path(path)) or [])
    assert invoke(case, monkeypatch, '--only', 'secrets', selection=approved) != 0
    assert scanned == []
    assert 'coverage unavailable' in capsys.readouterr().out.lower()


def test_trusted_ref_change_invalidates_prior_selection_approval(case, monkeypatch, capsys):
    commit_policy(case)
    approved = selection_digest(case['root'], case['revision'])
    git(case['root'], 'update-ref', 'refs/remotes/origin/other', case['revision'])
    monkeypatch.setenv('WIKI_COORDINATION_TRUSTED_REF', 'refs/remotes/origin/other')
    scanned = []
    monkeypatch.setattr(audit, 'scan_file', lambda path: scanned.append(Path(path)) or [])
    assert invoke(case, monkeypatch, '--only', 'secrets', selection=approved) != 0
    assert scanned == []
    assert 'coverage unavailable' in capsys.readouterr().out.lower()


def test_global_git_exclude_does_not_silently_expand_approved_selection(case, monkeypatch, capsys):
    root = case['root']
    commit_policy(case)
    approved = selection_digest(root, case['revision'])
    excluded = root / 'synthetic-global-excluded.txt'
    excluded.write_text('Synthetic untracked content\n')
    global_ignore = root.parent / 'synthetic-global-ignore'
    global_ignore.write_text('synthetic-global-excluded.txt\n')
    global_config = root.parent / 'synthetic-global-gitconfig'
    git(root, 'config', '--file', str(global_config), 'core.excludesFile', str(global_ignore))
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(global_config))
    legacy = git(root, 'ls-files', '--others', '--exclude-standard')
    assert 'synthetic-global-excluded.txt' not in legacy
    scanned = []
    monkeypatch.setattr(audit, 'scan_file', lambda path: scanned.append(Path(path)) or [])
    assert invoke(case, monkeypatch, '--only', 'secrets', selection=approved) != 0
    assert scanned == []
    assert 'coverage unavailable' in capsys.readouterr().out.lower()
