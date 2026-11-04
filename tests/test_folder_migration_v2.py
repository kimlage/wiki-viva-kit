"""Synthetic-only v1→v2 preview; never use personal data as fixture."""
from __future__ import annotations

import json
import datetime as dt
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from wiki_core.folder_migration_v2 import FolderMigrationError, FolderMigrationUncertain, prepare_folder_controls, write_folder_controls
from wiki_core import folder_migration_v2 as migration
from wiki_core.folder_policy_v2 import _at_revision, CONTROLS_PATH, folder_id
from wiki_core.context_policy import load_policy


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/wiki_folder_migration_v2.py'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def put(root, path, value):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(value, encoding='utf-8')


def manifest(identity, parent, root, policy, *, imports=(), exports=(), instructions=(), skills=()):
    return {'schema_version': 'wiki.context/v1', 'id': identity, 'parent': parent, 'root': root,
            'purpose': 'synthetic', 'owner': 'synthetic', 'instructions': list(instructions),
            'skills': list(skills), 'templates': [], 'policy': policy,
            'imports': list(imports), 'exports': list(exports)}


@pytest.fixture
def project(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Fixture')
    git(tmp_path, 'config', 'user.email', 'fixture@example.test')
    grant = {'from_context': 'b', 'to_context': 'a', 'selector': 'b/source.md',
             'use': 'synthetic-interpret', 'classification': 'internal', 'expires': '2099-12-31'}
    root = manifest('root', None, '.', {'read': ['self'], 'write': ['self'], 'capabilities': [],
                     'deny': {}, 'publication': []}, instructions=['AGENTS.md'])
    a = manifest('a', 'root', 'a', {'read': ['self', 'b/source.md'], 'write': ['self']}, imports=[grant], skills=['a/skill.md'])
    b = manifest('b', 'root', 'b', {'read': ['self'], 'write': ['self']}, exports=[grant])
    for path, data in [('context.yaml', root), ('a/context.yaml', a), ('b/context.yaml', b)]:
        put(tmp_path, path, yaml.safe_dump(data))
    put(tmp_path, 'AGENTS.md', '# Root\n\n## Wiki v2: indexes\n\n- [Root](README.md)\n')
    for path in ('README.md', 'a/index.md', 'b/index.md', 'a/skill.md', 'b/source.md'):
        put(tmp_path, path, 'Synthetic content.\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'approved v1')
    approved = git(tmp_path, 'rev-parse', 'HEAD')
    git(tmp_path, 'update-ref', 'refs/remotes/origin/main', approved)
    put(tmp_path, 'a/AGENTS.md', '# A\n\n## Wiki v2: mandatory references\n\n- [Skill](skill.md)\n')
    put(tmp_path, 'b/AGENTS.md', '# B\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'candidate folder instructions')
    return tmp_path, approved, git(tmp_path, 'rev-parse', 'HEAD')


def command(project, *extra):
    root, approved, candidate = project
    return subprocess.run([sys.executable, str(SCRIPT), '--repo', str(root), '--approved-revision', approved,
                           '--candidate-revision', candidate, *extra], capture_output=True, text=True, timeout=30)


def test_preview_preserves_mechanical_rules_without_writing_or_disclosure(project):
    root, approved, candidate = project
    report, proposal = prepare_folder_controls(root, approved, candidate)
    assert report['status'] == 'ready_for_review' and report['written'] is False
    data = yaml.safe_load(proposal)
    assert set(data) == {'schema_version', 'controls'}
    assert set(data['controls']) == {'.', 'a', 'b'}
    assert set(data['controls']['a']) == {'policy', 'imports', 'exports'}
    assert data['controls']['a']['imports'][0] == data['controls']['b']['exports'][0]
    assert data['controls']['a']['imports'][0]['from_context'] == 'b'
    assert data['controls']['a']['imports'][0]['to_context'] == 'a'
    assert data['controls']['a']['imports'][0]['expires'] == '2099-12-31'
    assert not (root / 'wiki-context-controls.yaml').exists()
    output = command(project)
    assert output.returncode == 0 and json.loads(output.stdout)['status'] == 'ready_for_review'
    assert 'synthetic-interpret' not in output.stdout + output.stderr
    assert str(root) not in output.stdout + output.stderr
    assert not (root / 'wiki-context-controls.yaml').exists()


def test_explicit_write_is_exclusive_clean_and_never_activates(project):
    root, approved, candidate = project
    result = command(project, '--write-proposal')
    assert result.returncode == 0 and json.loads(result.stdout)['written']
    target = root / 'wiki-context-controls.yaml'
    original = target.read_bytes()
    assert git(root, 'rev-parse', 'refs/remotes/origin/main') == approved
    assert git(root, 'rev-parse', 'HEAD') == candidate
    result = command(project, '--write-proposal')
    assert result.returncode == 1 and target.read_bytes() == original
    assert json.loads(result.stderr)['reason'] == 'candidate_worktree_not_clean'


def test_unindexed_instruction_boundary_blocks_even_explicit_write(project):
    root, approved, _ = project
    put(root, 'apps/tool/AGENTS.md', '# Auxiliary instruction\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'auxiliary boundary')
    candidate = git(root, 'rev-parse', 'HEAD')
    report, proposal = prepare_folder_controls(root, approved, candidate)
    assert report['status'] == 'blocked' and proposal is None
    assert 'unindexed_instruction_boundaries' in report['blockers']
    result = command((root, approved, candidate), '--write-proposal')
    assert result.returncode == 2 and not json.loads(result.stdout)['written']
    assert not (root / 'wiki-context-controls.yaml').exists()


def _nonintersecting_boundary(project):
    root, _, _ = project
    path = root / 'context.yaml'
    data = yaml.safe_load(path.read_text())
    data['policy']['read'] = ['AGENTS.md', 'README.md', 'a', 'b']
    data['policy']['write'] = ['a', 'b']
    path.write_text(yaml.safe_dump(data))
    git(root, 'add', 'context.yaml')
    git(root, 'commit', '-qm', 'approve limited root scopes')
    approved = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', approved)
    put(root, 'apps/tool/AGENTS.md', '# Auxiliary; no marker read required\n')
    git(root, 'add', 'apps/tool/AGENTS.md')
    git(root, 'commit', '-qm', 'auxiliary boundary outside scopes')
    return root, approved, git(root, 'rev-parse', 'HEAD')


def test_nonintersecting_boundary_is_reviewable_without_reading_auxiliary_body(project, monkeypatch):
    root, approved, candidate = _nonintersecting_boundary(project)
    from wiki_core.repository_reader import RepositoryReader
    original = RepositoryReader.read
    def guarded(self, path, *args, **kwargs):
        if path == 'apps/tool/AGENTS.md': pytest.fail('unrelated auxiliary body read')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    report, raw = prepare_folder_controls(root, approved, candidate)
    assert report['status'] == 'ready_for_review' and raw is not None
    assert report['ownership_change'] == 'ownership_changed_no_effective_grants'
    proof = report['boundary_scope_proof']
    assert proof['boundary_count'] == 1
    assert all(value == 0 for key, value in proof.items() if key != 'boundary_count')
    assert any('callers' in item for item in report['limitations'])
    write_folder_controls(root, approved, candidate)
    assert (root / CONTROLS_PATH).exists()


def test_nonintersecting_boundary_still_blocks_if_any_effect_exists(project):
    root, approved, _ = _nonintersecting_boundary(project)
    # Approve a policy with an unconstrained effect, then produce a descendant
    # candidate; the boundary cannot be certified harmless for all targets.
    git(root, 'reset', '--hard', approved)
    path = root / 'context.yaml'
    data = yaml.safe_load(path.read_text())
    data['policy']['capabilities'] = ['synthetic.effect']
    path.write_text(yaml.safe_dump(data))
    git(root, 'add', 'context.yaml')
    git(root, 'commit', '-qm', 'approve effect')
    approved = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', approved)
    put(root, 'apps/tool/AGENTS.md', '# Auxiliary\n')
    git(root, 'add', 'apps/tool/AGENTS.md')
    git(root, 'commit', '-qm', 'auxiliary')
    report, raw = prepare_folder_controls(root, approved, git(root, 'rev-parse', 'HEAD'))
    assert report['status'] == 'blocked' and raw is None
    assert report['boundary_scope_proof']['contexts_with_effective_capabilities'] > 0


@pytest.mark.parametrize('deny, expected_status', [('apps', 'ready_for_review'),
                                                   ('apps/tool/private', 'blocked')])
def test_total_deny_proves_boundary_but_partial_deny_does_not(project, deny, expected_status):
    root, _, _ = project
    path = root / 'context.yaml'
    data = yaml.safe_load(path.read_text())
    data['policy']['deny'] = {'read': [deny], 'write': [deny]}
    path.write_text(yaml.safe_dump(data))
    git(root, 'add', 'context.yaml')
    git(root, 'commit', '-qm', 'approve deny')
    approved = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', approved)
    put(root, 'apps/tool/AGENTS.md', '# Auxiliary instruction\n')
    git(root, 'add', 'apps/tool/AGENTS.md')
    git(root, 'commit', '-qm', 'auxiliary boundary')
    report, raw = prepare_folder_controls(root, approved, git(root, 'rev-parse', 'HEAD'))
    assert report['status'] == expected_status
    proof = report['boundary_scope_proof']
    assert proof['read_scope_intersections'] > 0 and proof['write_scope_intersections'] > 0
    if expected_status == 'ready_for_review':
        assert raw is not None and proof['read_uncovered_intersections'] == 0
        assert proof['write_uncovered_intersections'] == 0
        assert proof['read_fully_denied_intersections'] > 0
    else:
        assert raw is None and proof['read_uncovered_intersections'] > 0
        assert proof['write_uncovered_intersections'] > 0


def test_missing_mandatory_skill_or_root_index_is_not_equivalence(project):
    root, approved, _ = project
    put(root, 'a/AGENTS.md', '# A without mandatory skill\n')
    put(root, 'AGENTS.md', '# Root without declared index\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'incomplete')
    report, proposal = prepare_folder_controls(root, approved, git(root, 'rev-parse', 'HEAD'))
    assert proposal is None and report['status'] == 'blocked'
    assert {'mandatory_reference_parity_unproven', 'root_index_not_declared'} <= set(report['blockers'])
    assert report['contexts_with_mandatory_mismatch'] == 1


def test_unapproved_v1_ref_and_dirty_worktree_are_rejected(project):
    root, approved, candidate = project
    with pytest.raises(FolderMigrationError, match='fixed_revision_required'):
        prepare_folder_controls(root, 'HEAD', candidate)
    with pytest.raises(FolderMigrationError, match='approved_policy_or_candidate_unavailable'):
        prepare_folder_controls(root, candidate, candidate)
    report, proposal = prepare_folder_controls(root, approved, candidate)
    put(root, 'wip.txt', 'keep this file')
    with pytest.raises(FolderMigrationError, match='candidate_worktree_not_clean'):
        write_folder_controls(root, approved, candidate)
    assert (root / 'wip.txt').read_text() == 'keep this file'
    assert not (root / 'wiki-context-controls.yaml').exists()


def test_one_sided_connection_remains_one_sided_and_pending(project):
    root, _, _ = project
    path = root / 'b/context.yaml'
    data = yaml.safe_load(path.read_text())
    data['exports'] = []
    path.write_text(yaml.safe_dump(data))
    git(root, 'add', 'b/context.yaml')
    git(root, 'commit', '-qm', 'approve one-sided connection')
    approved = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', approved)
    report, raw = prepare_folder_controls(root, approved, approved)
    assert report['status'] == 'ready_for_review'
    proposal = yaml.safe_load(raw)
    assert len(proposal['controls']['a']['imports']) == 1
    assert proposal['controls']['b']['exports'] == []
    put(root, CONTROLS_PATH, raw.decode('utf-8'))
    git(root, 'add', CONTROLS_PATH)
    git(root, 'commit', '-qm', 'inspect proposed controls')
    v1 = load_policy(root, approved)
    v2 = _at_revision(root, git(root, 'rev-parse', 'HEAD'), CONTROLS_PATH)
    args = ('b/source.md', 'synthetic-interpret', 'internal')
    assert v1.connection('b', 'a', *args, today=dt.date(2026, 1, 1)) == 'pending'
    assert v2.connection(folder_id('b'), folder_id('a'), *args, today=dt.date(2026, 1, 1)) == 'pending'


def test_structured_workflow_is_not_silently_discarded(project):
    root, _, _ = project
    path = root / 'context.yaml'
    data = yaml.safe_load(path.read_text())
    data['workflow'] = {'requires_separate_review': True}
    path.write_text(yaml.safe_dump(data))
    git(root, 'add', 'context.yaml')
    git(root, 'commit', '-qm', 'approve workflow')
    approved = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', approved)
    report, raw = prepare_folder_controls(root, approved, approved)
    assert report['status'] == 'blocked' and raw is None
    assert 'structured_fields_need_review' in report['blockers']


@pytest.mark.parametrize('moving_ref', ['origin', 'head'])
def test_preview_rechecks_refs_after_comparison(project, monkeypatch, moving_ref):
    root, approved, candidate = project
    parse = migration.parse_folder_declarations
    moved = False
    def moving(*args, **kwargs):
        nonlocal moved
        if not moved:
            moved = True
            if moving_ref == 'origin':
                git(root, 'update-ref', 'refs/remotes/origin/main', candidate)
            else:
                git(root, 'update-ref', 'HEAD', approved)
        return parse(*args, **kwargs)
    monkeypatch.setattr(migration, 'parse_folder_declarations', moving)
    with pytest.raises(FolderMigrationError, match='migration_binding_moved'):
        prepare_folder_controls(root, approved, candidate)
    assert not (root / 'wiki-context-controls.yaml').exists()


def test_ref_moving_after_write_is_uncertain_and_file_is_not_deleted(project, monkeypatch):
    root, approved, candidate = project
    check = migration._ensure_binding_current
    calls = 0
    def moving(root_arg, approved_arg, candidate_arg):
        nonlocal calls
        calls += 1
        if calls == 3:  # two checks during preview; final check after file creation
            git(root, 'update-ref', 'refs/remotes/origin/main', candidate)
        return check(root_arg, approved_arg, candidate_arg)
    monkeypatch.setattr(migration, '_ensure_binding_current', moving)
    with pytest.raises(FolderMigrationUncertain, match='proposal_written_binding_uncertain'):
        write_folder_controls(root, approved, candidate)
    assert (root / 'wiki-context-controls.yaml').is_file()


def test_replacement_after_final_ref_check_is_uncertain_and_never_deleted(project, monkeypatch):
    root, approved, candidate = project
    check = migration._ensure_binding_current
    replacement = root.parent / (root.name + '-replacement')
    replacement.write_text('other actor content')
    calls = 0
    def swap(root_arg, approved_arg, candidate_arg):
        nonlocal calls
        calls += 1
        check(root_arg, approved_arg, candidate_arg)
        if calls == 3:
            os.replace(replacement, root / CONTROLS_PATH)
    monkeypatch.setattr(migration, '_ensure_binding_current', swap)
    with pytest.raises(FolderMigrationUncertain, match='proposal_written_binding_uncertain'):
        write_folder_controls(root, approved, candidate)
    assert (root / CONTROLS_PATH).read_text() == 'other actor content'


def test_write_rejects_executable_git_config_before_status(project, tmp_path):
    root, approved, candidate = project
    marker = tmp_path.parent / (tmp_path.name + '-fsmonitor-ran')
    stub = tmp_path.parent / (tmp_path.name + '-fsmonitor-stub')
    stub.write_text('#!/bin/sh\nprintf attempted > "' + str(marker) + '"\nexit 1\n')
    stub.chmod(0o700)
    git(root, 'config', 'core.fsmonitor', str(stub))
    with pytest.raises(FolderMigrationError, match='candidate_git_config_requires_review'):
        write_folder_controls(root, approved, candidate)
    assert not marker.exists()
    assert not (root / 'wiki-context-controls.yaml').exists()


def test_intermediate_sync_commit_then_explicit_c3_stays_one_unpromoted_branch(project, tmp_path):
    root, approved, _ = project
    git(root, 'checkout', '-qb', 'wiki/synthetic-adoption')
    kit = tmp_path.parent / (tmp_path.name + '-kit')
    kit.mkdir()
    git(kit, 'init', '-q')
    git(kit, 'config', 'user.name', 'Fixture')
    git(kit, 'config', 'user.email', 'fixture@example.test')
    put(kit, 'portable/tool.txt', 'Synthetic shared tool.\n')
    put(kit, 'generate.py', "from pathlib import Path\nPath('derived.txt').write_text('generated\\n')\n")
    manifest = {'schema_version': 'wiki_viva_sync_manifest.v1',
                'portable': {'allow': ['portable/**', 'generate.py'], 'block': []},
                'c2_commands': [[sys.executable, 'generate.py']]}
    put(kit, 'sync.yaml', yaml.safe_dump(manifest))
    git(kit, 'add', '.')
    git(kit, 'commit', '-qm', 'synthetic kit')
    kit_sha = git(kit, 'rev-parse', 'HEAD')
    sync = SCRIPT.parent / 'wiki_sync_from_kit.py'
    command_line = [sys.executable, str(sync), '--kit', str(kit), '--consumer', str(root),
                    '--manifest', str(kit / 'sync.yaml')]
    dry = subprocess.run([*command_line, '--dry-run'], capture_output=True, text=True, timeout=30)
    assert dry.returncode == 0 and not (root / 'kit.lock').exists()
    apply = subprocess.run(command_line, capture_output=True, text=True, timeout=30)
    assert apply.returncode == 0
    assert yaml.safe_load((root / 'kit.lock').read_text())['source_sha'] == kit_sha
    assert (root / 'portable/tool.txt').read_text() == 'Synthetic shared tool.\n'
    assert (root / 'derived.txt').read_text() == 'generated\n'
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'intermediate c1 c2 and lock')
    candidate = git(root, 'rev-parse', 'HEAD')
    result = command((root, approved, candidate), '--write-proposal')
    assert result.returncode == 0 and json.loads(result.stdout)['written']
    git(root, 'add', 'wiki-context-controls.yaml')
    git(root, 'commit', '-qm', 'explicit c3 controls proposal')
    assert git(root, 'branch', '--show-current') == 'wiki/synthetic-adoption'
    assert git(root, 'rev-parse', 'refs/remotes/origin/main') == approved
    assert git(root, 'merge-base', '--is-ancestor', candidate, 'HEAD') == ''
