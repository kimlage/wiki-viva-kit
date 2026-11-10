"""Synthetic proposal audit: unchanged denied files must never be read."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from wiki_core.coordination_context import CoordinationBinding
from wiki_core.repository_reader import RepositoryReader

ROOT = Path(__file__).resolve().parents[1]
TRUSTED_REF = 'refs/remotes/origin/main'
BRANCH = 'wiki/synthetic-proposal'
DENIED = [f'restricted/entry-{index}.json' for index in range(5)]
DENIED_IGNORE = 'restricted/.gitignore'
CODE = 'technical/tool.py'
POLICY = 'wiki.config.yaml'
MARKER = 'SYNTHETIC_DENIED_CONTENT_SHOULD_NOT_BE_READ'


def git(root: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def proposal(tmp_path):
    root = tmp_path / 'synthetic'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Synthetic')
    git(root, 'config', 'user.email', 'synthetic@example.invalid')
    (root / 'AGENTS.md').write_text('# Approved synthetic instructions\n')
    (root / 'index.md').write_text('# Approved synthetic index\n')
    (root / 'technical').mkdir()
    (root / CODE).write_text('VALUE = 1\n')
    (root / 'restricted').mkdir()
    for path in DENIED:
        (root / path).write_text(json.dumps({'synthetic': MARKER}) + '\n')
    (root / DENIED_IGNORE).write_text('# synthetic denied ignore file\n')
    config = {'context_access': {'.': {'owner': 'Synthetic owner', 'policy': {
        'read': ['self'], 'write': ['self'], 'capabilities': [],
        'deny': {'read': ['self/restricted']}, 'publication': []}}}}
    (root / POLICY).write_text(yaml.safe_dump(config))
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'approved synthetic base')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', TRUSTED_REF, base)
    git(root, 'checkout', '-qb', BRANCH)
    (root / CODE).write_text('VALUE = 2\n')
    # Candidate may propose changing policy, but cannot authorize its own scan.
    proposed_config = copy.deepcopy(config)
    proposed_config['context_access']['.']['policy']['deny'] = {}
    (root / POLICY).write_text(yaml.safe_dump(proposed_config))
    git(root, 'add', CODE, POLICY)
    git(root, 'commit', '-qm', 'synthetic candidate')
    head = git(root, 'rev-parse', 'HEAD')
    return {'root': root, 'base': base, 'head': head,
            'binding': CoordinationBinding(('.',), TRUSTED_REF),
            'config': config}


@pytest.fixture
def module():
    path = ROOT / 'scripts/wiki_audit_proposal.py'
    spec = importlib.util.spec_from_file_location('wiki_audit_proposal_synthetic', path)
    assert spec is not None and spec.loader is not None
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def changes(case):
    result = subprocess.run(['git', '-C', str(case['root']), 'diff', '--no-renames',
                             '--name-status', '-z', case['base'], case['head']],
                            check=True, capture_output=True).stdout.split(b'\0')
    if result[-1:] == [b'']:
        result.pop()
    assert len(result) % 2 == 0
    return sorted([{'status': result[i].decode(), 'path': result[i + 1].decode()}
                   for i in range(0, len(result), 2)], key=lambda row: row['path'])


def selection_sha(case, *, revision=None, head=None, branch=BRANCH, rows=None,
                  trusted_ref=TRUSTED_REF):
    obj = {'schema_version': 'wiki.proposal-secrets-selection/v1', 'context_id': '.',
           'policy_revision': revision or case['base'], 'trusted_ref': trusted_ref,
           'base': case['base'], 'head': head or case['head'], 'branch': branch,
           'changes': changes(case) if rows is None else rows}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def run(module, case, **override):
    args = {'context_id': '.', 'approved_revision': case['base'], 'base': case['base'],
            'head': case['head'], 'branch': BRANCH,
            'selection_sha256': (override['selection_sha256'] if 'selection_sha256' in override
                                 else selection_sha(case))}
    args.update(override)
    return module.audit_proposal(case['root'], case['binding'], **args)


def amend(case, *paths):
    # The temporary fixture contains only synthetic content. Adding the whole
    # fixture also handles deletions that `git rm` has already staged.
    git(case['root'], 'add', '-A')
    git(case['root'], 'commit', '--amend', '--no-edit', '-q')
    case['head'] = git(case['root'], 'rev-parse', 'HEAD')


def spy_documents(monkeypatch):
    opened = []
    original = RepositoryReader._document
    def observed(reader, path, *args, **kwargs):
        opened.append((reader.revision, path))
        return original(reader, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, '_document', observed)
    return opened


def test_proposal_scans_approved_diff_without_opening_unchanged_denied_blobs(module, proposal, monkeypatch):
    opened = spy_documents(monkeypatch)
    output = run(module, proposal)
    assert output['scope'] == 'proposal_changed_git_blobs'
    assert output['state'] == 'completed'
    assert output['global_audit'] == 'not_performed'
    assert output['intermediate_history'] == 'not_inspected'
    assert output['deleted_prior_nonbootstrap_bodies'] == 'not_inspected'
    assert output['unchanged_nonbootstrap_bodies'] == 'not_inspected'
    assert output['bootstrap_policy_and_context_bodies'] == 'read_external_authority_not_verified'
    assert output['working_tree_boundary_metadata'] == 'inspected'
    assert output['scanned_count'] == 2
    assert not any(path in {*DENIED, DENIED_IGNORE} for _, path in opened)
    assert MARKER not in json.dumps(output)
    assert any(path == CODE for _, path in opened)


def test_candidate_policy_cannot_authorize_denied_changed_file(module, proposal, monkeypatch):
    (proposal['root'] / DENIED[0]).write_text('{"synthetic":"candidate changed"}\n')
    amend(proposal, DENIED[0])
    opened = spy_documents(monkeypatch)
    with pytest.raises(ValueError) as failure:
        run(module, proposal)
    assert not any(path in {CODE, POLICY, *DENIED} for _, path in opened)
    assert DENIED[0] not in str(failure.value)
    assert MARKER not in str(failure.value)


@pytest.mark.parametrize('mode', ['missing_binding', 'stale_revision', 'wrong_head', 'wrong_branch', 'wrong_digest'])
def test_authority_or_selection_drift_refuses_before_target_reads(module, proposal, monkeypatch, mode):
    opened = spy_documents(monkeypatch)
    kwargs = {}
    if mode == 'missing_binding':
        proposal['binding'] = None
    elif mode == 'stale_revision':
        git(proposal['root'], 'update-ref', TRUSTED_REF, proposal['head'])
    elif mode == 'wrong_head':
        kwargs['head'] = proposal['base']
    elif mode == 'wrong_branch':
        kwargs['branch'] = 'wiki/not-the-proposal'
    else:
        kwargs['selection_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        run(module, proposal, **kwargs)
    assert not any(path in {CODE, POLICY, *DENIED} for _, path in opened)


def test_deletion_is_reported_without_claiming_a_head_blob(module, proposal):
    git(proposal['root'], 'rm', '-q', CODE)
    amend(proposal, CODE)
    output = run(module, proposal)
    assert output['state'] == 'completed'
    assert output['global_audit'] == 'not_performed'
    assert output['deleted_count'] == 1
    assert output['scanned_count'] == 1


def test_rename_is_an_addition_and_deletion_not_a_hidden_source_read(module, proposal, monkeypatch):
    git(proposal['root'], 'mv', CODE, 'technical/renamed.py')
    amend(proposal, CODE, 'technical/renamed.py')
    rows = changes(proposal)
    assert {'status': 'D', 'path': CODE} in rows
    assert {'status': 'A', 'path': 'technical/renamed.py'} in rows
    opened = spy_documents(monkeypatch)
    output = run(module, proposal)
    assert output['deleted_count'] == 1 and output['scanned_count'] == 2
    assert not any(path == CODE for _, path in opened)


@pytest.mark.parametrize('body', [b'bad\x00binary', b'bad\xffutf8', b'x' * 2_000_001],
                         ids=['nul-binary', 'invalid-utf8', 'too-large'])
def test_unsupported_blob_fails_instead_of_claiming_coverage(module, proposal, body):
    (proposal['root'] / CODE).write_bytes(body)
    amend(proposal, CODE)
    with pytest.raises(ValueError):
        run(module, proposal)


def test_symlink_candidate_fails_instead_of_being_silently_skipped(module, proposal):
    path = proposal['root'] / 'technical/link.py'
    try:
        path.symlink_to('tool.py')
    except (NotImplementedError, OSError):
        pytest.skip('symlinks unavailable')
    amend(proposal, 'technical/link.py')
    with pytest.raises(ValueError):
        run(module, proposal)


def test_secret_finding_refuses_clean_result(module, proposal):
    (proposal['root'] / CODE).write_text('synthetic = "' + 'AKIA' + 'IOSFODNN7EXAMPLE' + '"\n')
    amend(proposal, CODE)
    output = run(module, proposal)
    assert output['state'] == 'failed' and output['secret_findings'] > 0


def test_gitlink_candidate_is_not_silently_skipped(module, proposal):
    git(proposal['root'], 'update-index', '--add', '--cacheinfo',
        f"160000,{proposal['base']},technical/nested")
    git(proposal['root'], 'commit', '--amend', '--no-edit', '-q')
    proposal['head'] = git(proposal['root'], 'rev-parse', 'HEAD')
    with pytest.raises(ValueError):
        run(module, proposal)


def test_mode_only_change_is_in_selected_diff(module, proposal):
    path = proposal['root'] / CODE
    path.write_text('VALUE = 1\n')
    git(proposal['root'], 'add', CODE)
    git(proposal['root'], 'update-index', '--chmod=+x', CODE)
    git(proposal['root'], 'commit', '--amend', '--no-edit', '-q')
    proposal['head'] = git(proposal['root'], 'rev-parse', 'HEAD')
    assert {'status': 'M', 'path': CODE} in changes(proposal)
    output = run(module, proposal)
    assert output['state'] == 'completed' and output['scanned_count'] == 2


def test_exact_blob_alias_of_denied_input_is_refused_before_target_reads(module, proposal, monkeypatch):
    root = proposal['root']
    # All data in this repository is synthetic. This models an untrusted tree
    # mapping the same Git object to a permitted path without reading it.
    (root / CODE).write_bytes((root / DENIED[0]).read_bytes())
    amend(proposal, CODE)
    assert git(root, 'rev-parse', f"{proposal['base']}:{DENIED[0]}") == git(root, 'rev-parse', f"{proposal['head']}:{CODE}")
    opened = spy_documents(monkeypatch)
    with pytest.raises(ValueError):
        run(module, proposal)
    assert not any(path in {CODE, POLICY, *DENIED} for _, path in opened)


@pytest.mark.parametrize('moving_ref', ['branch', 'trusted'])
def test_ref_movement_during_target_read_invalidates_result(module, proposal, monkeypatch, moving_ref):
    original = RepositoryReader._document
    moved = []
    def observed(reader, path, *args, **kwargs):
        if path == CODE and not moved:
            ref = 'refs/heads/' + BRANCH if moving_ref == 'branch' else TRUSTED_REF
            target = proposal['base'] if moving_ref == 'branch' else proposal['head']
            git(proposal['root'], 'update-ref', ref, target)
            moved.append(ref)
        return original(reader, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, '_document', observed)
    with pytest.raises(ValueError):
        run(module, proposal)
    assert moved, 'the test must actually move the bound ref during the scan'


@pytest.mark.parametrize('ending', [b'\n', b'\r\n', b''], ids=['lf', 'crlf', 'eof'])
def test_lfs_pointer_fails_instead_of_claiming_content_scan(module, proposal, ending):
    (proposal['root'] / CODE).write_bytes(b'version https://git-lfs.github.com/spec/v1' + ending)
    amend(proposal, CODE)
    with pytest.raises(ValueError):
        run(module, proposal)


def test_intermediate_commit_is_not_silently_claimed_as_scanned(module, proposal):
    root = proposal['root']
    (root / CODE).write_text('synthetic = "' + 'AKIA' + 'IOSFODNN7EXAMPLE' + '"\n')
    git(root, 'add', CODE)
    git(root, 'commit', '-qm', 'synthetic intermediate only')
    (root / CODE).write_text('VALUE = 2\n')
    git(root, 'add', CODE)
    git(root, 'commit', '-qm', 'restore final content')
    proposal['head'] = git(root, 'rev-parse', 'HEAD')
    output = run(module, proposal)
    assert output['state'] == 'completed'
    assert output['intermediate_history'] == 'not_inspected'
    assert output['global_audit'] == 'not_performed'


def test_deletion_only_reports_prior_body_not_inspected(module, proposal):
    root = proposal['root']
    base_config = subprocess.run(['git', '-C', str(root), 'show', f"{proposal['base']}:{POLICY}"],
                                 check=True, capture_output=True).stdout
    (root / POLICY).write_bytes(base_config)
    git(root, 'rm', '-q', CODE)
    amend(proposal, POLICY)
    assert changes(proposal) == [{'status': 'D', 'path': CODE}]
    output = run(module, proposal)
    assert output['state'] == 'completed'
    assert output['scanned_count'] == 0 and output['deleted_count'] == 1
    assert output['deleted_prior_nonbootstrap_bodies'] == 'not_inspected'
    assert output['global_audit'] == 'not_performed'


def test_unsupported_changed_suffix_fails_without_opening_target_bodies(module, proposal, monkeypatch):
    (proposal['root'] / 'technical/unexamined.bin').write_bytes(b'synthetic-binary')
    amend(proposal, 'technical/unexamined.bin')
    opened = spy_documents(monkeypatch)
    with pytest.raises(ValueError):
        run(module, proposal)
    assert not any(path in {CODE, POLICY, *DENIED} for _, path in opened)


def test_cli_runs_exact_approved_synthetic_selection(proposal):
    import sys
    env = os.environ.copy()
    for key in ('WIKI_COORDINATION_MANIFEST', 'WIKI_COORDINATION_CONTEXT_MODE',
                'WIKI_COORDINATION_REPOSITORY_GRANTS'):
        env.pop(key, None)
    env.update({'WIKI_COORDINATION_ALLOWED_CONTEXTS': '.',
                'WIKI_COORDINATION_TRUSTED_REF': TRUSTED_REF,
                'WIKI_INSTALLED_CONTENT_ROOT': str(proposal['root'])})
    result = subprocess.run([
        sys.executable, str(ROOT / 'scripts/wiki_audit_proposal.py'), '--context', '.',
        '--approved-revision', proposal['base'], '--base', proposal['base'],
        '--head', proposal['head'], '--branch', BRANCH, '--selection-sha256', selection_sha(proposal),
    ], capture_output=True, text=True, env=env, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
    output = json.loads(result.stdout)
    assert output['state'] == 'completed' and output['scope'] == 'proposal_changed_git_blobs'
    assert output['global_audit'] == 'not_performed'
    assert output['working_tree_proposal_bodies'] == 'not_inspected'
    assert MARKER not in result.stdout


def test_deleted_bootstrap_instruction_is_reported_as_authorized_bootstrap_read(module, proposal, monkeypatch):
    root = proposal['root']
    git(root, 'rm', '-q', 'AGENTS.md')
    amend(proposal, 'AGENTS.md')
    opened = spy_documents(monkeypatch)
    output = run(module, proposal)
    assert (proposal['base'], 'AGENTS.md') in opened
    assert output['bootstrap_policy_and_context_bodies'] == 'read_external_authority_not_verified'
    assert output['deleted_prior_nonbootstrap_bodies'] == 'not_inspected'
    assert output['normative_review'] == 'not_performed'
    assert output['global_audit'] == 'not_performed'


def test_git_environment_cannot_redirect_qualified_tree(module, proposal, tmp_path, monkeypatch):
    approved_digest = selection_sha(proposal)
    other = tmp_path / 'other-synthetic'
    other.mkdir()
    git(other, 'init', '-q')
    git(other, 'config', 'user.name', 'Synthetic')
    git(other, 'config', 'user.email', 'synthetic@example.invalid')
    (other / 'not-the-source.txt').write_text('synthetic other repository\n')
    git(other, 'add', '.')
    git(other, 'commit', '-qm', 'other repo')
    monkeypatch.setenv('GIT_DIR', str(other / '.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(other))
    monkeypatch.setenv('GIT_INDEX_FILE', str(other / '.git' / 'index'))
    monkeypatch.setenv('PATH', str(tmp_path / 'no-git-here'))
    output = run(module, proposal, selection_sha256=approved_digest)
    assert output['state'] == 'completed'
    assert output['base'] == proposal['base'] and output['head'] == proposal['head']
    assert output['scanned_count'] == 2 and output['global_audit'] == 'not_performed'


@pytest.mark.skipif(os.name == 'nt', reason='synthetic shell fsmonitor fixture is POSIX-only')
def test_local_fsmonitor_hook_is_not_invoked(module, proposal, tmp_path):
    import shlex
    approved_digest = selection_sha(proposal)
    marker = tmp_path / 'fsmonitor-invoked'
    hook = tmp_path / 'synthetic-fsmonitor'
    hook.write_text('#!/bin/sh\nprintf synthetic > ' + shlex.quote(str(marker)) + '\nexit 1\n')
    hook.chmod(0o755)
    git(proposal['root'], 'config', 'core.fsmonitor', str(hook))
    # Prove the synthetic hook is usable before verifying the protected route.
    git(proposal['root'], 'status', '--porcelain')
    assert marker.exists()
    marker.unlink()
    output = run(module, proposal, selection_sha256=approved_digest)
    assert output['state'] == 'completed'
    assert not marker.exists()
