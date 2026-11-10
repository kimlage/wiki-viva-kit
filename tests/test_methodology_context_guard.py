"""Synthetic methodology readset tests, not a global audit or host proof."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.test_coverage import _scaffold_valid_repo, cov
from wiki_core.context_policy import PolicyError
from wiki_core.coordination_context import CoordinationBinding


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          text=True, capture_output=True).stdout.strip()


@pytest.fixture
def make_repo(tmp_path):
    def make(*, deny=()):
        root = tmp_path / 'synthetic'
        root.mkdir()
        _scaffold_valid_repo(root)
        (root / 'AGENTS.md').write_text('Synthetic instructions.\n')
        (root / 'index.md').write_text('Synthetic index.\n')
        (root / '.gitignore').write_text('data/derived/\n')
        config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
        config['context_access'] = {'.': {'owner': 'Synthetic', 'policy': {
            'read': ['self'], 'write': ['self'], 'deny': {'read': list(deny)},
            'capabilities': [], 'publication': []}}}
        (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
        git(root, 'init', '-q')
        git(root, 'config', 'user.name', 'Synthetic')
        git(root, 'config', 'user.email', 'synthetic@example.invalid')
        git(root, 'add', '.')
        git(root, 'commit', '-qm', 'synthetic base')
        base = git(root, 'rev-parse', 'HEAD')
        git(root, 'update-ref', 'refs/remotes/origin/main', base)
        git(root, 'checkout', '-qb', 'wiki/synthetic')
        binding = CoordinationBinding(('.',), 'refs/remotes/origin/main')
        args = dict(context_id='.', approved_revision=base, base=base, head=base,
                    branch='wiki/synthetic', normative_paths=['wiki.config.yaml'])
        return root, binding, args
    return make


def planned(root, binding, args):
    snapshot, selection, _, _ = cov.methodology_selection(root, binding, **args)
    return dict(inventory_sha256=snapshot['inventory_sha256'], selection_sha256=selection['selection_sha256'])


def run(root, binding, args, hashes, admit=lambda _: True):
    return cov.guarded_methodology(root, binding, **args, **hashes, admit=admit)


def no_target_reads(monkeypatch):
    from wiki_core import audit_r1_inventory
    original = audit_r1_inventory._worktree_bytes
    def bootstrap_only(root, row):
        assert row['path'] == 'wiki.config.yaml', 'target body read'
        return original(root, row)
    monkeypatch.setattr(audit_r1_inventory, '_worktree_bytes', bootstrap_only)


def test_admitted_real_check_has_methodology_only_coverage(make_repo, monkeypatch):
    root, binding, args = make_repo()
    hashes = planned(root, binding, args)
    monkeypatch.setattr(cov, 'ROOT', root)
    result = run(root, binding, args, hashes)
    assert result['state'] == 'completed'
    assert result['result']['complete'] is True
    assert result['scope'] == 'methodology_only'
    assert result['global_audit'] == 'not_performed'
    assert result['bootstrap'] == result['host_admission'] == 'external_not_verified'
    assert result['live_observation'] == 'not_verified'


def test_denied_required_file_refuses_before_any_target_body(make_repo, monkeypatch):
    root, binding, args = make_repo(deny=['self/memories/sources/wiki-viva-methodology-v5.md'])
    no_target_reads(monkeypatch)
    with pytest.raises(PolicyError, match='selection unavailable'):
        planned(root, binding, args)


def test_missing_required_input_refuses_before_target_bodies(make_repo, monkeypatch):
    root, binding, args = make_repo()
    (root / 'memories/sources/wiki-viva-methodology-v5.md').unlink()
    no_target_reads(monkeypatch)
    with pytest.raises(PolicyError, match='required input'):
        planned(root, binding, args)


def test_stale_selection_refuses_before_target_bodies(make_repo, monkeypatch):
    root, binding, args = make_repo()
    hashes = planned(root, binding, args)
    (root / 'memories/operations.md').write_text('changed after plan')
    no_target_reads(monkeypatch)
    with pytest.raises(PolicyError, match='selection changed'):
        run(root, binding, args, hashes)


def test_unadmitted_selection_refuses_before_target_bodies(make_repo, monkeypatch):
    root, binding, args = make_repo()
    hashes = planned(root, binding, args)
    no_target_reads(monkeypatch)
    with pytest.raises(PolicyError, match='admission unavailable'):
        run(root, binding, args, hashes, admit=lambda _: False)


def test_denied_conditional_cache_refuses_before_target_bodies(make_repo, monkeypatch):
    root, binding, args = make_repo(deny=['self/data/derived/wiki/llm-cache'])
    request = root / 'data/derived/wiki/extraction-events/fake-llm-context-request.json'
    cache = root / 'data/derived/wiki/llm-cache' / ('a' * 64 + '.json')
    request.parent.mkdir(parents=True, exist_ok=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    request.write_text(json.dumps({'chunks': [{'cache_key': 'a' * 64}]}))
    cache.write_text('{}')
    no_target_reads(monkeypatch)
    with pytest.raises(PolicyError, match='selection unavailable'):
        planned(root, binding, args)


def test_conditional_request_and_ignored_cache_are_selected_and_used(make_repo, monkeypatch):
    root, binding, args = make_repo()
    request = root / 'data/derived/wiki/extraction-events/fake-llm-context-request.json'
    cache = root / 'data/derived/wiki/llm-cache' / ('a' * 64 + '.json')
    request.parent.mkdir(parents=True, exist_ok=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    request.write_text(json.dumps({'chunks': [{'cache_key': 'a' * 64}]}))
    cache.write_text(json.dumps({'synthetic': 'invalid result'}))
    snapshot, selection, _, _ = cov.methodology_selection(root, binding, **args)
    selected = {item['path'] for item in selection['inputs']}
    assert request.relative_to(root).as_posix() in selected
    assert cache.relative_to(root).as_posix() in selected
    assert cache.relative_to(root).as_posix() in snapshot['ignored']
    seen = []
    original = cov._SelectedReads.read_bytes
    def instrument(self, path):
        seen.append(Path(path).relative_to(root).as_posix())
        return original(self, path)
    monkeypatch.setattr(cov._SelectedReads, 'read_bytes', instrument)
    result = run(root, binding, args, dict(inventory_sha256=snapshot['inventory_sha256'],
                                         selection_sha256=selection['selection_sha256']))
    assert result['state'] == 'failed'
    assert cache.relative_to(root).as_posix() in seen
    assert any(x['name'] == 'llm_context_pending' for x in result['result']['errors'])


def test_cli_plan_then_check_uses_explicit_host_binding(make_repo):
    root, _, args = make_repo()
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_check_methodology_coverage.py'
    env = dict(os.environ, WIKI_INSTALLED_CONTENT_ROOT=str(root),
               WIKI_COORDINATION_ALLOWED_CONTEXTS='.',
               WIKI_COORDINATION_TRUSTED_REF='refs/remotes/origin/main',
               WIKI_COORDINATION_CONTEXT_MODE='folder')
    command = [sys.executable, str(script), '--check', '--context-guard', '.',
               '--context-policy-revision', args['base'], '--context-base', args['base'],
               '--context-head', args['head'], '--context-branch', args['branch'],
               '--context-normative', 'wiki.config.yaml']
    plan = subprocess.run(command + ['--context-plan'], env=env, check=True, text=True, capture_output=True)
    result = json.loads(plan.stdout)
    assert result['state'] == 'selection_only'
    checked = subprocess.run(command + ['--context-inventory-sha256', result['inventory_sha256'],
                             '--context-selection-sha256', result['selection']['selection_sha256']],
                             env=env, check=True, text=True, capture_output=True)
    assert json.loads(checked.stdout)['state'] == 'completed'
