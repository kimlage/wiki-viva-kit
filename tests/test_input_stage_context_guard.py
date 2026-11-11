"""Synthetic input-stage admission tests; no global audit or host proof.

The proposed in-process interface follows the existing methodology guard:
``input_stage_selection`` returns (inventory, selection, config, approved
config); ``guarded_input_stage`` accepts the two digests, exact extra paths and
an external whole-selection admission callback. Names may be adapted to the
shared implementation; neither a digest nor these tests grant access.
"""

from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import wiki_input_stage as cli
from tests.test_input_stage import _fixture_repo, _source_config_page
from wiki_core.config import load_config
from wiki_core.context_policy import PolicyError
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.input_stage import write_input_stage


def git(root: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def make_repo(tmp_path):
    def make(*, deny=(), conditional_ref=False, missing_config_ref=False,
             missing_root=False, invalid_config_ref=False):
        root = tmp_path / 'synthetic'
        root.mkdir()
        original = _fixture_repo(root)
        (root / 'AGENTS.md').write_text('Synthetic instructions.\n')
        (root / 'index.md').write_text('Synthetic index.\n')
        (root / '.gitignore').write_text('data/derived/\n')
        (root / 'restricted').mkdir()
        (root / 'restricted/unrelated.json').write_text('{"synthetic": true}\n')
        wip = root / 'memories/example/wip.md'
        wip.write_text('# Synthetic note\n')
        if conditional_ref or missing_config_ref or invalid_config_ref:
            source = root / 'memories/sources/team-handbook.md'
            before = source.read_text()
            ref = ('restricted/missing.md' if missing_config_ref else
                   'auxiliary/invalid.yaml' if invalid_config_ref else 'auxiliary/external.yaml')
            after = before.replace('config_ref: memories/sources/config/team-handbook.md',
                                   'config_ref: ' + ref)
            assert after != before
            source.write_text(after)
            if not missing_config_ref:
                target = root / ref
                target.parent.mkdir()
                target.write_text('---\npage_type: not_source_config\n---\n' if invalid_config_ref else
                                  _source_config_page('synthetic-external', 'source-team-handbook'))
        config = {'contexts': list(original.contexts),
                  'default_context': original.default_context,
                  'root_entity': original.root_entity,
                  'context_access': {'.': {'owner': 'Synthetic', 'policy': {
                      'read': ['self'], 'write': ['self'], 'deny': {'read': list(deny)},
                      'capabilities': [], 'publication': []}}}}
        if missing_root:
            config['root_entity'] = {**original.root_entity, 'page': 'memories/example/missing-root.md'}
        (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
        # Generate synthetic output before installing spies and before the Git
        # baseline, so the real check has something meaningful to compare.
        write_input_stage(root, load_config(root), generated_at='2026-06-25')
        git(root, 'init', '-q')
        git(root, 'config', 'user.name', 'Synthetic')
        git(root, 'config', 'user.email', 'synthetic@example.invalid')
        git(root, 'add', '.')
        git(root, 'commit', '-qm', 'synthetic approved base')
        base = git(root, 'rev-parse', 'HEAD')
        git(root, 'update-ref', 'refs/remotes/origin/main', base)
        git(root, 'checkout', '-qb', 'wiki/synthetic')
        binding = CoordinationBinding(('.',), 'refs/remotes/origin/main')
        args = dict(context_id='.', approved_revision=base, base=base, head=base,
                    branch='wiki/synthetic', normative_paths=['wiki.config.yaml'])
        return root, binding, args
    return make


def plan(root, binding, args, *, extra_paths=()):
    inventory, selection, _, _ = cli.input_stage_selection(
        root, binding, **args, extra_paths=list(extra_paths))
    return inventory, selection


def execute(root, binding, args, inventory, selection, *, extra_paths=(), admit=lambda _: True):
    return cli.guarded_input_stage(
        root, binding, **args, extra_paths=list(extra_paths),
        inventory_sha256=inventory['inventory_sha256'],
        selection_sha256=selection['selection_sha256'], admit=admit)


def forbid_body(monkeypatch, target: Path):
    """Spies cover common Python opens, not every system-level read route."""
    original_path_open = Path.open
    original_os_open = os.open
    def path_open(path, mode='r', *args, **kwargs):
        if path == target and ('r' in mode or '+' in mode):
            pytest.fail('unadmitted target body was opened')
        return original_path_open(path, mode, *args, **kwargs)
    def os_open(path, flags, *args, **kwargs):
        if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)) == target and (flags & os.O_ACCMODE) != os.O_WRONLY:
            pytest.fail('unadmitted target body was opened')
        return original_os_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', path_open)
    monkeypatch.setattr(os, 'open', os_open)


def assert_limited(result):
    assert result['scope'] == 'input_stage_only'
    assert result['global_audit'] == 'not_performed'
    assert result['bootstrap'] == result['host_admission'] == 'external_not_verified'
    assert result['live_observation'] == 'not_verified'
    assert result['cleanup'] == 'external_not_verified'
    assert result['gate_state'] == 'blocked_external_qualification'
    assert result['coverage']['index'] == 'metadata_only'
    assert result['coverage']['history'] == 'bootstrap_commit_objects_may_include_messages_not_audited'
    assert result['coverage']['composition'] == 'not_qualified'
    if result['state'] == 'partial':
        assert result['coverage']['worktree'] == 'partial_or_unknown_selected_bodies'
        assert result['coverage']['ignored'] == 'partial_or_unknown_selected_bodies'
    else:
        assert result['coverage']['worktree'] == 'selected_bodies_only'
        assert result['coverage']['ignored'] == 'selected_bodies_only'


def test_required_denied_markdown_refuses_before_body(make_repo, monkeypatch):
    root, binding, args = make_repo(deny=['self/memories/input-channels/team-docs.md'])
    target = root / 'memories/input-channels/team-docs.md'
    forbid_body(monkeypatch, target)
    with pytest.raises(PolicyError):
        plan(root, binding, args)


def test_plan_does_not_open_nonbootstrap_target_bodies(make_repo, monkeypatch):
    root, binding, args = make_repo()
    from wiki_core import audit_r1_inventory
    original = audit_r1_inventory._worktree_bytes
    def bootstrap_only(repo, row):
        assert row['path'] == 'wiki.config.yaml', 'plan opened target body'
        return original(repo, row)
    monkeypatch.setattr(audit_r1_inventory, '_worktree_bytes', bootstrap_only)
    original_open = Path.open
    def no_memory_body(path, mode='r', *values, **kwargs):
        if path.is_relative_to(root / 'memories') and ('r' in mode or '+' in mode):
            pytest.fail('plan opened memory body')
        return original_open(path, mode, *values, **kwargs)
    monkeypatch.setattr(Path, 'open', no_memory_body)
    inventory, selection = plan(root, binding, args)
    assert inventory['inventory_sha256'] and selection['inputs']


def test_whole_selection_admitted_before_any_target_body(make_repo, monkeypatch):
    root, binding, args = make_repo()
    inventory, selection = plan(root, binding, args)
    from wiki_core import audit_r1_inventory
    original = audit_r1_inventory._worktree_bytes
    admitted = []
    attempted = []
    def admit(value):
        assert value == selection
        admitted.append(True)
        return True
    def after_admission(repo, row):
        if row['path'] != 'wiki.config.yaml':
            assert admitted, 'selected target was opened before whole-selection admission'
            attempted.append(row['path'])
        return original(repo, row)
    monkeypatch.setattr(audit_r1_inventory, '_worktree_bytes', after_admission)
    result = execute(root, binding, args, inventory, selection, admit=admit)
    assert admitted and attempted and result['state'] == 'completed'
    assert_limited(result)


def test_unrelated_denied_body_is_untouched_and_real_check_completes(make_repo, monkeypatch):
    root, binding, args = make_repo(deny=['self/restricted'])
    target = root / 'restricted/unrelated.json'
    forbid_body(monkeypatch, target)
    inventory, selection = plan(root, binding, args)
    assert 'restricted/unrelated.json' not in {item['path'] for item in selection['inputs']}
    monkeypatch.setattr(cli, 'ROOT', root)
    result = execute(root, binding, args, inventory, selection)
    assert result['state'] == 'completed'
    assert result['result']['complete'] is True
    assert_limited(result)


def test_conditional_ref_requires_selection_then_real_check_completes(make_repo, monkeypatch):
    root, binding, args = make_repo(conditional_ref=True)
    target = root / 'auxiliary/external.yaml'
    forbid_body(monkeypatch, target)
    inventory, selection = plan(root, binding, args)
    assert 'auxiliary/external.yaml' not in {item['path'] for item in selection['inputs']}
    monkeypatch.setattr(cli, 'ROOT', root)
    partial = execute(root, binding, args, inventory, selection)
    assert partial['state'] == 'partial'
    assert partial['source_bodies_validated'] > 0
    assert partial['source_body_attempts_may_have_read_bytes'] >= partial['source_bodies_validated']
    assert_limited(partial)
    # Reconciliation and a NEW selection are required; no prior result is
    # composed into the new execution or treated as gate coverage.
    monkeypatch.undo()
    inventory, selection = plan(root, binding, args, extra_paths=['auxiliary/external.yaml'])
    monkeypatch.setattr(cli, 'ROOT', root)
    assert 'auxiliary/external.yaml' in {item['path'] for item in selection['inputs']}
    result = execute(root, binding, args, inventory, selection,
                     extra_paths=['auxiliary/external.yaml'])
    assert result['state'] == 'completed' and result['result']['complete'] is True
    assert_limited(result)


def test_explicit_missing_config_ref_never_falls_back_to_completed(make_repo, monkeypatch):
    root, binding, args = make_repo(missing_config_ref=True, deny=['self/restricted'])
    # The unguarded compatibility path retains its existing fallback; the
    # protected reader must not present that fallback as complete coverage.
    from wiki_core.source_config import find_source_config
    legacy = find_source_config(root, load_config(root), 'memories/sources/team-handbook.md')
    assert legacy is not None
    forbid_body(monkeypatch, root / 'restricted/missing.md')
    inventory, selection = plan(root, binding, args)
    result = execute(root, binding, args, inventory, selection)
    assert result['state'] == 'partial'
    assert_limited(result)


def test_explicit_invalid_config_ref_never_falls_back_to_completed(make_repo):
    root, binding, args = make_repo(invalid_config_ref=True)
    extra = ['auxiliary/invalid.yaml']
    inventory, selection = plan(root, binding, args, extra_paths=extra)
    result = execute(root, binding, args, inventory, selection, extra_paths=extra)
    assert result['state'] == 'partial'
    assert_limited(result)


def test_missing_explicit_root_refuses_before_selected_bodies(make_repo, monkeypatch):
    root, binding, args = make_repo(missing_root=True)
    forbid_body(monkeypatch, root / 'memories/input-channels/team-docs.md')
    with pytest.raises(PolicyError, match='required input'):
        plan(root, binding, args)


def test_staged_unstaged_and_ignored_cache_are_bound(make_repo, monkeypatch):
    root, binding, args = make_repo()
    wip = root / 'memories/example/wip.md'
    wip.write_text('# Synthetic staged note\n')
    git(root, 'add', str(wip.relative_to(root)))
    wip.write_text('# Synthetic unstaged note\n')
    inventory, selection = plan(root, binding, args)
    selected = {item['path'] for item in selection['inputs']}
    cache = 'data/derived/wiki/input-stage/input-catalog.json'
    assert 'memories/example/wip.md' in selected and cache in selected
    assert cache in inventory['ignored']
    monkeypatch.setattr(cli, 'ROOT', root)
    result = execute(root, binding, args, inventory, selection)
    assert result['state'] == 'completed' and result['result']['complete'] is True
    assert {item['path'] for item in result['readset']} >= {'memories/example/wip.md', cache}
    assert_limited(result)


def test_missing_host_admission_refuses_before_selected_body(make_repo, monkeypatch):
    root, binding, args = make_repo()
    inventory, selection = plan(root, binding, args)
    target = root / 'memories/input-channels/team-docs.md'
    forbid_body(monkeypatch, target)
    with pytest.raises(PolicyError):
        execute(root, binding, args, inventory, selection, admit=lambda _: False)


def test_changed_selection_refuses_before_selected_body(make_repo, monkeypatch):
    root, binding, args = make_repo()
    inventory, selection = plan(root, binding, args)
    target = root / 'memories/input-channels/team-docs.md'
    target.write_text(target.read_text() + '\nSynthetic changed content.\n')
    forbid_body(monkeypatch, target)
    with pytest.raises(PolicyError, match='selection changed'):
        execute(root, binding, args, inventory, selection)


def test_denied_conditional_reference_is_never_opened(make_repo, monkeypatch):
    root, binding, args = make_repo(conditional_ref=True, deny=['self/auxiliary'])
    target = root / 'auxiliary/external.yaml'
    forbid_body(monkeypatch, target)
    inventory, selection = plan(root, binding, args)
    result = execute(root, binding, args, inventory, selection)
    assert result['state'] == 'partial'
    assert_limited(result)
    with pytest.raises(PolicyError):
        plan(root, binding, args, extra_paths=['auxiliary/external.yaml'])


def test_conditional_reference_cannot_probe_outside_repository(make_repo, monkeypatch, tmp_path):
    root, binding, args = make_repo()
    outside = tmp_path / 'synthetic-outside.md'
    outside.write_text('# Synthetic outside\n')
    source = root / 'memories/sources/team-handbook.md'
    source.write_text(source.read_text().replace(
        'config_ref: memories/sources/config/team-handbook.md',
        'config_ref: ../synthetic-outside.md'))
    inventory, selection = plan(root, binding, args)
    original = Path.resolve
    def reject_escape(path, *values, **kwargs):
        if '..' in path.parts:
            pytest.fail('outside reference was probed')
        return original(path, *values, **kwargs)
    monkeypatch.setattr(Path, 'resolve', reject_escape)
    forbid_body(monkeypatch, outside)
    result = execute(root, binding, args, inventory, selection)
    assert result['state'] == 'partial'
    assert_limited(result)


def test_cli_exposes_computation_but_refuses_unverified_gate(make_repo):
    root, _, args = make_repo()
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_input_stage.py'
    env = dict(os.environ, WIKI_INSTALLED_CONTENT_ROOT=str(root),
               WIKI_COORDINATION_ALLOWED_CONTEXTS='.',
               WIKI_COORDINATION_TRUSTED_REF='refs/remotes/origin/main',
               WIKI_COORDINATION_CONTEXT_MODE='folder')
    command = [os.sys.executable, str(script), '--check', '--context-guard', '.',
               '--context-policy-revision', args['base'], '--context-base', args['base'],
               '--context-head', args['head'], '--context-branch', args['branch'],
               '--context-normative', 'wiki.config.yaml']
    planned = subprocess.run(command + ['--context-plan'], env=env, text=True, capture_output=True)
    selection = json.loads(planned.stdout)
    assert planned.returncode != 0
    assert selection['state'] == 'selection_only'
    assert selection['gate_state'] == 'blocked_external_qualification'
    checked = subprocess.run(command + ['--context-inventory-sha256', selection['inventory_sha256'],
                             '--context-selection-sha256', selection['selection']['selection_sha256']],
                             env=env, text=True, capture_output=True)
    result = json.loads(checked.stdout)
    assert checked.returncode != 0 and result['state'] == 'completed'
    assert result['result']['complete'] is True
    assert_limited(result)


def test_cli_without_binding_refuses_before_target_body(make_repo, monkeypatch, capsys):
    root, _, args = make_repo()
    target = root / 'memories/input-channels/team-docs.md'
    forbid_body(monkeypatch, target)
    monkeypatch.setattr(cli, 'ROOT', root)
    for name in ('WIKI_COORDINATION_ALLOWED_CONTEXTS', 'WIKI_COORDINATION_TRUSTED_REF',
                 'WIKI_COORDINATION_CONTEXT_MODE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(os.sys, 'argv', ['wiki_input_stage.py', '--check', '--context-guard', '.',
        '--context-policy-revision', args['base'], '--context-base', args['base'],
        '--context-head', args['head'], '--context-branch', args['branch'],
        '--context-normative', 'wiki.config.yaml', '--context-plan'])
    assert cli.main() != 0
    result = json.loads(capsys.readouterr().out)
    assert result['state'] == 'refused' and result['gate_state'] == 'blocked_external_qualification'


def test_partial_postread_failure_counts_attempt_as_possibly_read(make_repo, monkeypatch):
    root, binding, args = make_repo()
    inventory, selection = plan(root, binding, args)
    from wiki_core import audit_r1_inventory
    original = audit_r1_inventory._worktree_bytes
    observed = []
    def fail_after_read(repo, row):
        data = original(repo, row)
        if row['path'] != 'wiki.config.yaml':
            observed.append(row['path'])
            raise PolicyError('synthetic post-read validation failure')
        return data
    monkeypatch.setattr(audit_r1_inventory, '_worktree_bytes', fail_after_read)
    result = execute(root, binding, args, inventory, selection)
    assert len(observed) == 1 and result['state'] == 'partial'
    assert result['source_bodies_validated'] == 0
    assert result['source_body_attempts_may_have_read_bytes'] == 1
    assert_limited(result)
