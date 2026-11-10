"""Synthetic Git fixtures for independently admitted, plan-bound kit sync.

The host owns bootstrap, selection and plan approval. A digest is only a
binding, not evidence of independent approval or filesystem enforcement.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from wiki_core.coordination_context import CoordinationBinding


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/wiki_sync_guarded.py'


def git(root: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def init_repo(path: Path) -> None:
    path.mkdir()
    git(path, 'init', '-q')
    git(path, 'config', 'user.name', 'Synthetic')
    git(path, 'config', 'user.email', 'synthetic@example.invalid')


def imported_module():
    spec = importlib.util.spec_from_file_location('guarded_sync_test_module', SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def case(tmp_path: Path):
    if sys.platform == 'win32':
        pytest.skip('guarded sync is not qualified on Windows')
    kit, consumer = tmp_path / 'synthetic-kit', tmp_path / 'synthetic-consumer'
    init_repo(kit)
    init_repo(consumer)
    (kit / 'portable').mkdir()
    (kit / 'portable/alpha.txt').write_text('Synthetic alpha v1\n', encoding='utf-8')
    (kit / 'portable/beta.txt').write_text('Synthetic beta v1\n', encoding='utf-8')
    manifest = kit / 'docs/references/upgrades/sync-manifest.yaml'
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        'schema_version: wiki_viva_sync_manifest.v1\n'
        'portable:\n  allow: ["portable/**"]\n  block: []\n'
        'c2_commands: []\n', encoding='utf-8')
    git(kit, 'add', '.')
    git(kit, 'commit', '-qm', 'synthetic kit')
    (consumer / 'AGENTS.md').write_text('# Synthetic authority\n', encoding='utf-8')
    (consumer / 'index.md').write_text('# Synthetic context\n', encoding='utf-8')
    (consumer / 'portable').mkdir()
    config = {'context_access': {'.': {'owner': 'Synthetic owner', 'policy': {
        'read': ['self'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []}}}}
    (consumer / 'wiki.config.yaml').write_text(yaml.safe_dump(config), encoding='utf-8')
    git(consumer, 'add', '.')
    git(consumer, 'commit', '-qm', 'synthetic approved policy')
    policy_sha = git(consumer, 'rev-parse', 'HEAD')
    git(consumer, 'update-ref', 'refs/remotes/origin/main', policy_sha)
    return {'kit': kit, 'consumer': consumer, 'manifest': manifest,
            'source_sha': git(kit, 'rev-parse', 'HEAD'), 'policy_sha': policy_sha,
            'binding': CoordinationBinding(('.',), 'refs/remotes/origin/main'),
            'config': config, 'module': imported_module()}


def test_windows_refuses_before_root_or_bootstrap(monkeypatch, tmp_path):
    module = imported_module()
    monkeypatch.setattr(module.sys, 'platform', 'win32')

    def unexpected_root(*args, **kwargs):
        raise AssertionError('root or bootstrap inspected on Windows')

    monkeypatch.setattr(module, '_root', unexpected_root)
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main')
    kwargs = dict(context_id='.', approved_revision='a' * 40, source_sha='b' * 40,
                  selection={}, selection_sha256='c' * 64)
    with pytest.raises(module.GuardedSyncError):
        module.prepare_plan(tmp_path / 'kit', tmp_path / 'consumer', binding, **kwargs)
    with pytest.raises(module.GuardedSyncError):
        module.apply_plan(tmp_path / 'kit', tmp_path / 'consumer', binding,
                          expected_plan_sha256='d' * 64, **kwargs)
    with pytest.raises(module.GuardedSyncError):
        module.propose_selection(tmp_path / 'kit', tmp_path / 'consumer', binding,
                                 context_id='.', approved_revision='a' * 40,
                                 source_sha='b' * 40, bootstrap_selection={},
                                 bootstrap_selection_sha256='c' * 64)


def approve_policy(case: dict, *, read_deny=(), write_deny=()):
    config = copy.deepcopy(case['config'])
    config['context_access']['.']['policy']['deny'] = {
        'read': list(read_deny), 'write': list(write_deny)}
    path = case['consumer'] / 'wiki.config.yaml'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    git(case['consumer'], 'add', 'wiki.config.yaml')
    git(case['consumer'], 'commit', '-qm', 'synthetic policy')
    revision = git(case['consumer'], 'rev-parse', 'HEAD')
    git(case['consumer'], 'update-ref', 'refs/remotes/origin/main', revision)
    case['policy_sha'] = revision
    return revision


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selection(case: dict, paths=('kit.lock', 'portable/alpha.txt', 'portable/beta.txt')) -> dict:
    return case['module'].select_contract('.', case['policy_sha'], case['binding'].trusted_ref,
                                           case['source_sha'], sorted(paths))


def selection_hash(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True,
                     separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def prepare(case: dict, selected=None):
    selected = selected if selected is not None else selection(case)
    return case['module'].prepare_plan(
        case['kit'], case['consumer'], case['binding'], context_id='.',
        approved_revision=case['policy_sha'], source_sha=case['source_sha'],
        selection=selected, selection_sha256=selection_hash(selected))


def apply(case: dict, plan_sha: str, selected=None):
    selected = selected if selected is not None else selection(case)
    return case['module'].apply_plan(
        case['kit'], case['consumer'], case['binding'], context_id='.',
        approved_revision=case['policy_sha'], source_sha=case['source_sha'],
        selection=selected, selection_sha256=selection_hash(selected),
        expected_plan_sha256=plan_sha)


def controlled_state(case: dict):
    paths = ('kit.lock', 'portable/alpha.txt', 'portable/beta.txt')
    result = {}
    for rel in paths:
        path = case['consumer'] / rel
        if path.is_symlink():
            result[rel] = ('symlink', os.readlink(path))
        elif path.is_file():
            result[rel] = ('file', path.read_bytes(), path.stat().st_mode & 0o777)
        elif path.exists():
            result[rel] = ('other',)
        else:
            result[rel] = ('missing',)
    return result


def refuse_target_inspection(monkeypatch, *paths: Path):
    """Fail if any target metadata or body is touched before admission."""
    restricted = {str(path) for path in paths}
    original_stat, original_lstat, original_open = Path.stat, Path.lstat, Path.open

    def stat(path, *args, **kwargs):
        if str(path) in restricted:
            raise AssertionError('target metadata inspected before admission')
        return original_stat(path, *args, **kwargs)

    def lstat(path, *args, **kwargs):
        if str(path) in restricted:
            raise AssertionError('target metadata inspected before admission')
        return original_lstat(path, *args, **kwargs)

    def open_(path, *args, **kwargs):
        if str(path) in restricted:
            raise AssertionError('target body opened before admission')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', stat)
    monkeypatch.setattr(Path, 'lstat', lstat)
    monkeypatch.setattr(Path, 'open', open_)


def test_missing_lock_b0_and_exact_approved_plan_apply(case):
    assert not (case['consumer'] / 'kit.lock').exists()
    before = controlled_state(case)
    plan = prepare(case)
    assert controlled_state(case) == before
    assert len(plan['plan_sha256']) == 64
    outcome = apply(case, plan['plan_sha256'])
    assert outcome['external_approval'] == 'not_verified'
    assert outcome['consumer_dirty'] == 'not_inspected'
    assert (case['consumer'] / 'portable/alpha.txt').read_text() == 'Synthetic alpha v1\n'
    assert (case['consumer'] / 'portable/beta.txt').read_text() == 'Synthetic beta v1\n'
    lock = yaml.safe_load((case['consumer'] / 'kit.lock').read_text())
    assert set(lock['managed_files']) == {'portable/alpha.txt', 'portable/beta.txt'}
    assert lock['source_sha'] == case['source_sha']


@pytest.mark.parametrize('deny_field', ['read', 'write'])
def test_denied_lock_refuses_before_lock_metadata_or_body(case, monkeypatch, deny_field):
    approve_policy(case, **{deny_field + '_deny': ['self/kit.lock']})
    refuse_target_inspection(monkeypatch, case['consumer'] / 'kit.lock')
    with pytest.raises(case['module'].GuardedSyncError):
        prepare(case)


def test_denied_target_in_selection_fails_before_any_target_probe(case, monkeypatch):
    approve_policy(case, read_deny=['self/portable/beta.txt'])
    refuse_target_inspection(monkeypatch, case['consumer'] / 'portable/alpha.txt',
                             case['consumer'] / 'portable/beta.txt')
    with pytest.raises(case['module'].GuardedSyncError):
        prepare(case)


def test_lock_cannot_expand_selection_into_denied_target(case, monkeypatch):
    deny = 'restricted/old.txt'
    approve_policy(case, read_deny=['self/restricted'])
    lock = {'schema_version': 'wiki_viva_kit_lock.v1', 'managed_files': {
        deny: {'sha256': '0' * 64, 'mode': '100644'}}}
    (case['consumer'] / 'kit.lock').write_text(yaml.safe_dump(lock), encoding='utf-8')
    refuse_target_inspection(monkeypatch, case['consumer'] / 'portable/alpha.txt',
                             case['consumer'] / 'portable/beta.txt', case['consumer'] / deny)
    selected = selection(case, ('kit.lock', 'portable/alpha.txt', 'portable/beta.txt', deny))
    with pytest.raises(case['module'].GuardedSyncError):
        prepare(case, selected)


def test_candidate_policy_never_authorizes_its_own_selection(case, monkeypatch):
    approve_policy(case, read_deny=['self/portable/beta.txt'])
    candidate = copy.deepcopy(case['config'])
    candidate['context_access']['.']['policy']['deny'] = {}
    (case['consumer'] / 'wiki.config.yaml').write_text(yaml.safe_dump(candidate), encoding='utf-8')
    refuse_target_inspection(monkeypatch, case['consumer'] / 'portable/alpha.txt',
                             case['consumer'] / 'portable/beta.txt')
    with pytest.raises(case['module'].GuardedSyncError):
        prepare(case)


@pytest.mark.parametrize('mutation', ['source', 'lock', 'target', 'selection'])
def test_approved_plan_drift_fails_before_effects(case, mutation):
    plan = prepare(case)
    chosen = selection(case)
    if mutation == 'source':
        (case['kit'] / 'portable/alpha.txt').write_text('Synthetic new source\n')
        git(case['kit'], 'add', '.')
        git(case['kit'], 'commit', '-qm', 'advance synthetic source')
    elif mutation == 'lock':
        (case['consumer'] / 'kit.lock').write_text(
            yaml.safe_dump({'schema_version': 'wiki_viva_kit_lock.v1', 'managed_files': {}}))
    elif mutation == 'target':
        (case['consumer'] / 'portable/alpha.txt').write_text('Synthetic altered target\n')
    else:
        chosen = selection(case, (*chosen['paths'], 'portable/extra.txt'))
    before = controlled_state(case)
    with pytest.raises(case['module'].GuardedSyncError):
        apply(case, plan['plan_sha256'], chosen)
    assert controlled_state(case) == before
    assert not list(case['consumer'].rglob('.wiki-sync-*'))


def test_missing_or_wrong_plan_digest_refused_before_effects(case):
    plan = prepare(case)
    before = controlled_state(case)
    for invalid in ('', '0' * 64, None):
        with pytest.raises((case['module'].GuardedSyncError, TypeError, ValueError)):
            apply(case, invalid)
        assert controlled_state(case) == before
    assert plan['plan_sha256'] != '0' * 64


def test_invalid_selection_digest_refused_before_consumer_lock(case, monkeypatch):
    chosen = selection(case)
    refuse_target_inspection(monkeypatch, case['consumer'] / 'kit.lock',
                             case['consumer'] / 'portable/alpha.txt')
    with pytest.raises(case['module'].GuardedSyncError):
        case['module'].prepare_plan(
            case['kit'], case['consumer'], case['binding'], context_id='.',
            approved_revision=case['policy_sha'], source_sha=case['source_sha'],
            selection=chosen, selection_sha256='0' * 64)


def test_trusted_policy_ref_change_after_b0_fails_before_effects(case):
    plan = prepare(case)
    git(case['consumer'], 'commit', '--allow-empty', '-qm', 'advance synthetic approval')
    git(case['consumer'], 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    before = controlled_state(case)
    with pytest.raises((case['module'].GuardedSyncError, ValueError)):
        apply(case, plan['plan_sha256'])
    assert controlled_state(case) == before


@pytest.mark.parametrize('target', ['kit.lock', 'portable/alpha.txt'])
def test_denied_temporary_effect_fails_before_any_target_probe(case, monkeypatch, target):
    temp = case['module'].temp_path_for(case['source_sha'], target)
    approve_policy(case, write_deny=['self/' + temp])
    refuse_target_inspection(monkeypatch, case['consumer'] / temp,
                             case['consumer'] / 'portable/alpha.txt',
                             case['consumer'] / 'portable/beta.txt')
    with pytest.raises(case['module'].GuardedSyncError):
        prepare(case)


def test_parent_metadata_requires_separate_read_permission(case, monkeypatch):
    selected = selection(case)
    config = copy.deepcopy(case['config'])
    # Only the exact target and temporary paths are granted, not the parent
    # directory's metadata. Bootstrap files are separate approved inputs.
    allowed = ['self/AGENTS.md', 'self/index.md'] + [
        'self/' + path for path in selected['paths'] + selected['temp_paths']]
    config['context_access']['.']['policy']['read'] = allowed
    config['context_access']['.']['policy']['write'] = allowed
    (case['consumer'] / 'wiki.config.yaml').write_text(yaml.safe_dump(config), encoding='utf-8')
    git(case['consumer'], 'add', 'wiki.config.yaml')
    git(case['consumer'], 'commit', '-qm', 'synthetic exact grants without parent metadata')
    case['policy_sha'] = git(case['consumer'], 'rev-parse', 'HEAD')
    git(case['consumer'], 'update-ref', 'refs/remotes/origin/main', case['policy_sha'])
    refuse_target_inspection(monkeypatch, case['consumer'] / 'portable',
                             case['consumer'] / 'portable/alpha.txt',
                             case['consumer'] / 'portable/beta.txt')
    with pytest.raises(case['module'].GuardedSyncError):
        prepare(case)


@pytest.mark.parametrize('target', ['kit.lock', 'portable/alpha.txt'])
def test_temporary_collision_fails_without_effects(case, target):
    temp = case['consumer'] / case['module'].temp_path_for(case['source_sha'], target)
    temp.write_bytes(b'synthetic unrelated file')
    before = controlled_state(case)
    with pytest.raises(case['module'].GuardedSyncError):
        prepare(case)
    assert controlled_state(case) == before
    assert temp.read_bytes() == b'synthetic unrelated file'


def test_missing_parent_fails_without_implicit_mkdir(case):
    (case['consumer'] / 'portable').rmdir()
    with pytest.raises(case['module'].GuardedSyncError):
        prepare(case)
    assert not (case['consumer'] / 'portable').exists()
    assert not (case['consumer'] / 'kit.lock').exists()


def test_c2_command_is_refused_before_lock_inspection(case, monkeypatch):
    manifest = yaml.safe_load(case['manifest'].read_text())
    manifest['c2_commands'] = [['python3', 'arbitrary.py']]
    case['manifest'].write_text(yaml.safe_dump(manifest), encoding='utf-8')
    git(case['kit'], 'add', str(case['manifest'].relative_to(case['kit'])))
    git(case['kit'], 'commit', '-qm', 'add synthetic command')
    case['source_sha'] = git(case['kit'], 'rev-parse', 'HEAD')
    refuse_target_inspection(monkeypatch, case['consumer'] / 'kit.lock')
    with pytest.raises(case['module'].GuardedSyncError):
        prepare(case)


def test_symlink_target_refused_without_effects(case):
    target = case['consumer'] / 'portable/alpha.txt'
    try:
        target.symlink_to(case['consumer'] / 'index.md')
    except (OSError, NotImplementedError):
        pytest.skip('symlink unavailable')
    before = controlled_state(case)
    with pytest.raises(case['module'].GuardedSyncError):
        prepare(case)
    assert controlled_state(case) == before
    assert (case['consumer'] / 'index.md').read_text() == '# Synthetic context\n'


def test_nested_repository_refused_without_effects(case):
    (case['consumer'] / 'portable/.git').mkdir()
    before = controlled_state(case)
    with pytest.raises(case['module'].GuardedSyncError):
        prepare(case)
    assert controlled_state(case) == before


def establish_existing_lock(case):
    plan = prepare(case)
    apply(case, plan['plan_sha256'])
    git(case['consumer'], 'add', 'kit.lock', 'portable')
    git(case['consumer'], 'commit', '-qm', 'synthetic prior adoption')
    case['policy_sha'] = git(case['consumer'], 'rev-parse', 'HEAD')
    git(case['consumer'], 'update-ref', 'refs/remotes/origin/main', case['policy_sha'])


def test_existing_lock_and_changed_source_needs_new_approved_plan(case):
    establish_existing_lock(case)
    (case['kit'] / 'portable/beta.txt').write_text('Synthetic beta v2\n')
    git(case['kit'], 'add', '.')
    git(case['kit'], 'commit', '-qm', 'synthetic new kit')
    case['source_sha'] = git(case['kit'], 'rev-parse', 'HEAD')
    plan = prepare(case)
    apply(case, plan['plan_sha256'])
    assert (case['consumer'] / 'portable/alpha.txt').read_text() == 'Synthetic alpha v1\n'
    assert (case['consumer'] / 'portable/beta.txt').read_text() == 'Synthetic beta v2\n'


def test_reviewable_plan_and_removal_update_lock(case):
    establish_existing_lock(case)
    (case['kit'] / 'portable/beta.txt').unlink()
    git(case['kit'], 'add', '-A')
    git(case['kit'], 'commit', '-qm', 'remove synthetic managed file')
    case['source_sha'] = git(case['kit'], 'rev-parse', 'HEAD')
    unrelated = case['consumer'] / 'portable/unmanaged.txt'
    unrelated.write_text('Synthetic unmanaged WIP\n')

    plan = prepare(case)
    assert plan['c1']['remove_previously_managed'] == ['portable/beta.txt']
    assert plan['desired_states']['portable/beta.txt'] == {'kind': 'missing'}
    assert plan['desired_states']['portable/alpha.txt'] == {
        'kind': 'file', 'sha256': sha(case['kit'] / 'portable/alpha.txt'),
        'mode': '100644', 'size': len(b'Synthetic alpha v1\n'),
        'fs_mode': format((case['consumer'] / 'portable/alpha.txt').stat().st_mode & 0o7777, '04o'),
    }
    apply(case, plan['plan_sha256'])
    assert not (case['consumer'] / 'portable/beta.txt').exists()
    assert unrelated.read_text() == 'Synthetic unmanaged WIP\n'
    lock = yaml.safe_load((case['consumer'] / 'kit.lock').read_text())
    assert lock['source_sha'] == case['source_sha']
    assert lock['managed_files'] == {
        'portable/alpha.txt': {'sha256': sha(case['kit'] / 'portable/alpha.txt'), 'mode': '100644'}
    }


@pytest.mark.parametrize('when', ['before_plan', 'after_plan'])
def test_removal_rejects_divergent_managed_content_without_effects(case, when):
    establish_existing_lock(case)
    (case['kit'] / 'portable/beta.txt').unlink()
    git(case['kit'], 'add', '-A')
    git(case['kit'], 'commit', '-qm', 'remove synthetic managed file')
    case['source_sha'] = git(case['kit'], 'rev-parse', 'HEAD')
    plan = prepare(case) if when == 'after_plan' else None
    target = case['consumer'] / 'portable/beta.txt'
    target.write_text('Synthetic local edit must survive\n')
    before = controlled_state(case)
    with pytest.raises(case['module'].GuardedSyncError):
        if plan is None:
            prepare(case)
        else:
            apply(case, plan['plan_sha256'])
    assert controlled_state(case) == before


@pytest.mark.parametrize('mutation', ['contents', 'mode'])
def test_unchanged_target_state_drift_refuses_all_effects(case, mutation):
    if mutation == 'mode' and os.name == 'nt':
        pytest.skip('portable executable mode is unavailable')
    establish_existing_lock(case)
    (case['kit'] / 'portable/beta.txt').write_text('Synthetic beta v2\n')
    git(case['kit'], 'add', '.')
    git(case['kit'], 'commit', '-qm', 'synthetic new kit')
    case['source_sha'] = git(case['kit'], 'rev-parse', 'HEAD')
    plan = prepare(case)
    unchanged = case['consumer'] / 'portable/alpha.txt'
    if mutation == 'contents':
        unchanged.write_text('Synthetic unrelated edit\n')
    else:
        unchanged.chmod(0o755)
    before = controlled_state(case)
    with pytest.raises(case['module'].GuardedSyncError):
        apply(case, plan['plan_sha256'])
    assert controlled_state(case) == before


def test_selected_staged_divergence_is_not_overwritten(case):
    establish_existing_lock(case)
    target = case['consumer'] / 'portable/alpha.txt'
    target.write_text('Synthetic staged edit\n')
    git(case['consumer'], 'add', 'portable/alpha.txt')
    target.write_text('Synthetic alpha v1\n')
    before_index = git(case['consumer'], 'show', ':portable/alpha.txt')
    before = controlled_state(case)
    with pytest.raises(case['module'].GuardedSyncError):
        prepare(case)
    assert controlled_state(case) == before
    assert git(case['consumer'], 'show', ':portable/alpha.txt') == before_index


def test_git_environment_cannot_redirect_or_execute_path_wrapper(case, tmp_path, monkeypatch):
    other = tmp_path / 'other-repo'
    init_repo(other)
    (other / 'unrelated').write_text('Synthetic other repository\n')
    git(other, 'add', '.')
    git(other, 'commit', '-qm', 'unrelated')
    fake_bin = tmp_path / 'fake-bin'
    fake_bin.mkdir()
    marker = tmp_path / 'unexpected-git-execution'
    fake_git = fake_bin / 'git'
    fake_git.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\nexit 1\n')
    fake_git.chmod(0o755)
    monkeypatch.setenv('PATH', str(fake_bin))
    monkeypatch.setenv('GIT_DIR', str(other / '.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(other))
    monkeypatch.setenv('GIT_INDEX_FILE', str(other / '.git/index'))
    before = controlled_state(case)
    try:
        plan = prepare(case)
    except case['module'].GuardedSyncError:
        pass  # A fail-closed host environment is also acceptable.
    else:
        assert plan['source_sha'] == case['source_sha']
    assert not marker.exists()
    assert controlled_state(case) == before


def test_cli_b0_reports_no_approval_and_rejects_c3(case, tmp_path):
    selected = selection(case)
    path = tmp_path / 'external-selection.json'
    path.write_text(json.dumps(selected), encoding='utf-8')
    args = [sys.executable, str(SCRIPT), '--kit', str(case['kit']),
            '--consumer', str(case['consumer']), '--context', '.',
            '--approved-revision', case['policy_sha'], '--source-sha', case['source_sha'],
            '--selection-file', str(path), '--selection-sha256', selection_hash(selected)]
    env = os.environ.copy()
    env.update(WIKI_COORDINATION_ALLOWED_CONTEXTS='.',
               WIKI_COORDINATION_TRUSTED_REF='refs/remotes/origin/main',
               WIKI_COORDINATION_CONTEXT_MODE='folder')
    before = controlled_state(case)
    b0 = subprocess.run([*args, '--dry-run'], capture_output=True, text=True, env=env)
    assert b0.returncode == 0, b0.stderr
    result = json.loads(b0.stdout)
    assert result['external_approval'] == 'not_verified'
    assert result['consumer_dirty'] == 'not_inspected'
    assert result['mode'] == 'B0'
    assert str(case['consumer']) not in b0.stdout
    assert controlled_state(case) == before
    c3 = subprocess.run([*args, '--c3-command', 'false'], capture_output=True, text=True, env=env)
    assert c3.returncode != 0
    assert controlled_state(case) == before


def test_discovery_admits_lock_before_body_and_never_opens_targets(case, monkeypatch):
    establish_existing_lock(case)
    (case['kit'] / 'portable/beta.txt').unlink()
    git(case['kit'], 'add', '-A')
    git(case['kit'], 'commit', '-qm', 'remove synthetic managed file')
    case['source_sha'] = git(case['kit'], 'rev-parse', 'HEAD')
    bootstrap = selection(case, paths=('kit.lock',))
    original_snapshot = case['module']._snapshot

    def snapshot(root, path):
        if path != 'kit.lock':
            raise AssertionError('discovery inspected a target')
        return original_snapshot(root, path)

    monkeypatch.setattr(case['module'], '_snapshot', snapshot)
    result = case['module'].propose_selection(
        case['kit'], case['consumer'], case['binding'], context_id='.',
        approved_revision=case['policy_sha'], source_sha=case['source_sha'],
        bootstrap_selection=bootstrap, bootstrap_selection_sha256=selection_hash(bootstrap))
    assert result['selection']['paths'] == ['kit.lock', 'portable/alpha.txt', 'portable/beta.txt']
    assert result['selection_sha256'] == selection_hash(result['selection'])
    assert result['external_admission'] == 'not_verified'
    assert result['target_bodies'] == 'not_inspected'


@pytest.mark.parametrize('reason', ['deny', 'digest'])
def test_discovery_refuses_unadmitted_lock_before_open(case, monkeypatch, reason):
    if reason == 'deny':
        approve_policy(case, read_deny=['self/kit.lock'])
    bootstrap = selection(case, paths=('kit.lock',))
    def unexpected_lock(*args, **kwargs):
        raise AssertionError('unadmitted lock was opened')
    monkeypatch.setattr(case['module'], '_lock', unexpected_lock)
    with pytest.raises(case['module'].GuardedSyncError):
        case['module'].propose_selection(
            case['kit'], case['consumer'], case['binding'], context_id='.',
            approved_revision=case['policy_sha'], source_sha=case['source_sha'],
            bootstrap_selection=bootstrap,
            bootstrap_selection_sha256='0' * 64 if reason == 'digest' else selection_hash(bootstrap))


def test_cli_discovery_and_full_plan_are_explicit(case, tmp_path):
    path = tmp_path / 'external-selection.json'
    common = [sys.executable, str(SCRIPT), '--kit', str(case['kit']),
            '--consumer', str(case['consumer']), '--context', '.',
            '--approved-revision', case['policy_sha'], '--source-sha', case['source_sha']]
    env = os.environ.copy()
    env.update(WIKI_COORDINATION_ALLOWED_CONTEXTS='.',
               WIKI_COORDINATION_TRUSTED_REF='refs/remotes/origin/main',
               WIKI_COORDINATION_CONTEXT_MODE='folder')
    before = controlled_state(case)
    no_roots = list(common)
    no_roots[no_roots.index('--kit') + 1] = str(tmp_path / 'missing-kit')
    no_roots[no_roots.index('--consumer') + 1] = str(tmp_path / 'missing-consumer')
    bootstrap_result = subprocess.run([*no_roots, '--bootstrap-selection'],
                                      capture_output=True, text=True, env=env)
    assert bootstrap_result.returncode == 0, bootstrap_result.stderr
    initial = json.loads(bootstrap_result.stdout)
    assert initial['repositories'] == 'not_inspected'
    assert initial['external_admission'] == 'not_verified'
    assert initial['selection'] == selection(case, paths=('kit.lock',))
    path.write_text(json.dumps(initial['selection']), encoding='utf-8')
    args = [*common, '--selection-file', str(path), '--selection-sha256']
    proposed = subprocess.run([*args, initial['selection_sha256'], '--propose-selection'],
                              capture_output=True, text=True, env=env)
    assert proposed.returncode == 0, proposed.stderr
    result = json.loads(proposed.stdout)
    path.write_text(json.dumps(result['selection']), encoding='utf-8')
    full = subprocess.run([*args, result['selection_sha256'], '--dry-run', '--full-plan'],
                          capture_output=True, text=True, env=env)
    assert full.returncode == 0, full.stderr
    output = json.loads(full.stdout)
    assert output['external_approval'] == 'not_verified'
    plan = output['plan']
    assert plan['selection'] == result['selection']
    assert plan['desired_states']['portable/alpha.txt']['sha256'] == sha(case['kit'] / 'portable/alpha.txt')
    assert plan['plan_sha256'] == case['module']._digest({k: v for k, v in plan.items() if k != 'plan_sha256'})
    assert controlled_state(case) == before


def test_new_collision_after_b0_is_not_deleted(case):
    plan = prepare(case)
    collision = case['consumer'] / case['module'].temp_path_for(case['source_sha'], 'kit.lock')
    collision.write_bytes(b'synthetic unrelated file')
    before = controlled_state(case)
    with pytest.raises(case['module'].GuardedSyncError):
        apply(case, plan['plan_sha256'])
    assert controlled_state(case) == before
    assert collision.read_bytes() == b'synthetic unrelated file'


@pytest.mark.parametrize('relative', ['kit.lock', 'portable/alpha.txt'])
def test_hardlinked_lock_or_target_is_refused_before_body_open(case, tmp_path, monkeypatch, relative):
    alias = tmp_path / 'synthetic-outside-scope'
    alias.write_bytes(b'synthetic non-admitted bytes\n')
    target = case['consumer'] / relative
    os.link(alias, target)
    original = os.open

    def guard(path, flags, *args, **kwargs):
        if os.fspath(path) == os.fspath(target):
            raise AssertionError('hardlinked body was opened')
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(case['module'].os, 'open', guard)
    with pytest.raises(case['module'].GuardedSyncError):
        prepare(case)
    assert target.stat().st_nlink == 2
    assert alias.read_bytes() == b'synthetic non-admitted bytes\n'
    assert not list(case['consumer'].rglob('.wiki-sync-*'))


def test_hardlinked_external_selection_is_refused_before_body_open(case, tmp_path, monkeypatch):
    alias = tmp_path / 'synthetic-selection-source'
    alias.write_text(json.dumps(selection(case)), encoding='utf-8')
    path = tmp_path / 'selection.json'
    os.link(alias, path)
    original = os.open

    def guard(candidate, flags, *args, **kwargs):
        if os.fspath(candidate) == os.fspath(path):
            raise AssertionError('hardlinked selection was opened')
        return original(candidate, flags, *args, **kwargs)

    monkeypatch.setattr(case['module'].os, 'open', guard)
    with pytest.raises(case['module'].GuardedSyncError):
        case['module']._selection_file(path, case['kit'], case['consumer'])
    assert path.stat().st_nlink == 2
    assert json.loads(alias.read_text(encoding='utf-8')) == selection(case)


def test_interrupted_second_replace_reports_partial_effects(case, monkeypatch):
    plan = prepare(case)
    original = os.replace
    beta = case['consumer'] / 'portable/beta.txt'

    def replace(source, target, *args, **kwargs):
        if Path(target) == beta:
            raise OSError('synthetic replace failure')
        return original(source, target, *args, **kwargs)

    monkeypatch.setattr(case['module'].os, 'replace', replace)
    with pytest.raises(case['module'].GuardedSyncError, match='partial'):
        apply(case, plan['plan_sha256'])
    assert (case['consumer'] / 'portable/alpha.txt').is_file()
    assert not beta.exists()
    assert not (case['consumer'] / 'kit.lock').exists()
    assert not list(case['consumer'].rglob('.wiki-sync-*'))


def test_source_move_on_final_lock_replace_never_reports_success(case, monkeypatch):
    plan = prepare(case)
    original = os.replace
    lock = case['consumer'] / 'kit.lock'

    def replace(source, target, *args, **kwargs):
        result = original(source, target, *args, **kwargs)
        if Path(target) == lock:
            (case['kit'] / 'portable/beta.txt').write_text('Synthetic new source\n')
            git(case['kit'], 'add', '.')
            git(case['kit'], 'commit', '-qm', 'move source during final replace')
        return result

    monkeypatch.setattr(case['module'].os, 'replace', replace)
    with pytest.raises(case['module'].GuardedSyncError, match='partial'):
        apply(case, plan['plan_sha256'])
    assert git(case['kit'], 'rev-parse', 'HEAD') != case['source_sha']


@pytest.mark.parametrize('mutated', ['unchanged', 'changed'])
@pytest.mark.parametrize('when', ['before_lock', 'after_lock'])
def test_mode_drift_after_effects_fails_before_lock_or_on_final_readback(case, monkeypatch, mutated, when):
    establish_existing_lock(case)
    (case['kit'] / 'portable/beta.txt').write_text('Synthetic beta v2\n')
    git(case['kit'], 'add', '.')
    git(case['kit'], 'commit', '-qm', 'synthetic new kit')
    case['source_sha'] = git(case['kit'], 'rev-parse', 'HEAD')
    plan = prepare(case)
    consumer = case['consumer']
    alpha, beta, lock = consumer / 'portable/alpha.txt', consumer / 'portable/beta.txt', consumer / 'kit.lock'
    previous_lock = lock.read_bytes()
    original = os.replace
    observed = []

    def replace(source, target, *args, **kwargs):
        result = original(source, target, *args, **kwargs)
        target = Path(target)
        observed.append(target)
        trigger = beta if when == 'before_lock' else lock
        if target == trigger:
            (alpha if mutated == 'unchanged' else beta).chmod(0o600)
        return result

    monkeypatch.setattr(case['module'].os, 'replace', replace)
    with pytest.raises(case['module'].GuardedSyncError, match='partial'):
        apply(case, plan['plan_sha256'])
    assert beta.read_text() == 'Synthetic beta v2\n'
    assert alpha.read_text() == 'Synthetic alpha v1\n'
    assert (alpha if mutated == 'unchanged' else beta).stat().st_mode & 0o777 == 0o600
    assert (beta if mutated == 'unchanged' else alpha).stat().st_mode & 0o777 == 0o644
    if when == 'before_lock':
        assert lock not in observed
        assert lock.read_bytes() == previous_lock
    else:
        assert lock in observed
        assert lock.read_bytes() != previous_lock
    assert not list(consumer.rglob('.wiki-sync-*'))
