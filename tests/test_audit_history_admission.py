"""Synthetic base-history selection; not a complete audit or OS observation."""
from pathlib import Path
import subprocess

import pytest
import yaml

import scripts.wiki_audit as audit
from wiki_core import audit_history_selection as guarded
from wiki_core import audit_r1_inventory as r1
from wiki_core.context_packet import qualify_folder_context
from wiki_core.context_policy import PolicyError, load_policy
from wiki_core.coordination_context import CoordinationBinding


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          text=True, capture_output=True).stdout.strip()


def make_case(tmp_path, monkeypatch, *, denied, alias=False, oversized=False, extra_files=0, extra_size=0):
    root = tmp_path / 'synthetic'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Synthetic')
    git(root, 'config', 'user.email', 'synthetic@example.invalid')
    (root / 'AGENTS.md').write_text('# Synthetic guidance\n')
    (root / 'index.md').write_text('# Synthetic index\n')
    (root / 'memories/internal').mkdir(parents=True)
    (root / 'memories/actions').mkdir(parents=True)
    (root / 'memories/internal/denied.md').write_text('---\npage_type: action\npage_id: hidden\n---\nSynthetic.\n')
    (root / 'memories/actions/allowed.md').write_text(
        '---\npage_type: action\npage_id: allowed\n---\nSynthetic.\n' + ('x' * 2_000_000 if oversized else ''))
    for index in range(extra_files):
        (root / f'memories/actions/extra-{index:03}.md').write_text(
            f'---\npage_type: action\npage_id: extra-{index}\n---\n' + ('x' * extra_size))
    (root / 'restricted').mkdir()
    (root / 'restricted/denied.json').write_text(
        (root / 'memories/actions/allowed.md').read_text() if alias else '{"synthetic": true}\n')
    config = {'context_access': {'.': {'owner': 'Synthetic', 'policy': {
        'read': ['self'], 'write': ['self'], 'deny': {'read': ['self/restricted'] + (['self/memories/internal'] if denied else [])},
        'capabilities': [], 'publication': []}}}}
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'synthetic approved base')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', base)
    git(root, 'checkout', '-qb', 'wiki/synthetic')
    monkeypatch.setattr(audit, 'ROOT', root)
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main')
    args = {'context_id': '.', 'approved_revision': base, 'base': base, 'head': base,
            'branch': 'wiki/synthetic', 'normative_paths': ['wiki.config.yaml']}
    return root, binding, args


def test_legacy_actual_grep_searches_synthetic_denied_markdown(tmp_path, monkeypatch):
    root, _, args = make_case(tmp_path, monkeypatch, denied=True)
    policy = load_policy(root, args['base'], 'wiki.config.yaml')
    qualify_folder_context(root, policy, '.', '.', 'index.md', 100_000)
    assert not policy.permits('.', 'read', 'memories/internal/denied.md')
    original = subprocess.run
    greps = []
    def record(argv, *args, **kwargs):
        if isinstance(argv, (list, tuple)) and 'grep' in argv:
            greps.append(tuple(argv))
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', record)
    result = audit._action_candidate_texts_by_path_at_ref(args['base'])
    assert 'memories/internal/denied.md' in result
    assert any(':(literal)memories/internal/denied.md' in call for call in greps)


def test_denied_candidate_refuses_before_search_or_blob_read(tmp_path, monkeypatch):
    root, binding, args = make_case(tmp_path, monkeypatch, denied=True)
    snapshot = r1.inventory(root, binding, **args)
    monkeypatch.setattr(audit, '_grep_selected_history', lambda *a: pytest.fail('grep executed'))
    monkeypatch.setattr(audit, '_history_text', lambda *a: pytest.fail('history body opened'))
    for check in ('action_state_transitions', 'source_lifecycle_transitions'):
        with pytest.raises(PolicyError, match='selection unavailable'):
            guarded.plan_base_markdown(snapshot, check=check, memory_root='memories')
        with pytest.raises(PolicyError, match='selection unavailable'):
            guarded.search_base_markdown(root, binding, **args, check=check, memory_root='memories',
                inventory_sha256=snapshot['inventory_sha256'], plan_sha256='0' * 64, admit=lambda _: True)


@pytest.mark.parametrize('check', ['action_state_transitions', 'source_lifecycle_transitions'])
def test_admitted_exact_search_reports_partial_gate(tmp_path, monkeypatch, check):
    root, binding, args = make_case(tmp_path, monkeypatch, denied=False)
    snapshot = r1.inventory(root, binding, **args)
    plan = guarded.plan_base_markdown(snapshot, check=check, memory_root='memories')
    selected = {item['path'] for item in plan['selection']['inputs']}
    assert selected == {'memories/actions/allowed.md', 'memories/internal/denied.md'}
    original = audit._grep_selected_history
    calls = []
    def record(base, pattern, paths):
        calls.append((base, tuple(paths)))
        return original(base, pattern, paths)
    monkeypatch.setattr(audit, '_grep_selected_history', record)
    common = dict(**args, check=check, memory_root='memories',
                  inventory_sha256=snapshot['inventory_sha256'], plan_sha256=plan['plan_sha256'])
    with pytest.raises(PolicyError, match='admission unavailable'):
        guarded.search_base_markdown(root, binding, **common, admit=lambda _: False)
    assert not calls
    with pytest.raises(PolicyError, match='selection changed'):
        guarded.search_base_markdown(root, binding, **{**common, 'plan_sha256': '0' * 64}, admit=lambda _: True)
    assert not calls
    out = guarded.search_base_markdown(root, binding, **common, admit=lambda _: True)
    assert calls and set(calls[0][1]) == selected
    assert out['state'] == 'partial' and out['search'] == 'completed'
    assert out['gate_coverage'] == 'not_verified' and out['global_audit'] == 'not_performed'
    assert out['worktree_check'] == 'not_performed' and out['index_bodies'] == 'not_inspected'
    assert out['coverage']['base_markdown'] == 'searched_under_caller_root'
    assert all(out['coverage'][name] == 'not_intentionally_read' for name in
               ('base_other_bodies', 'intermediate_bodies', 'index_bodies',
                'worktree_bodies', 'ignored_bodies'))
    assert out['coverage']['commit_messages'] == 'bootstrap_read_not_scanned'


def test_search_failure_never_reports_complete(tmp_path, monkeypatch):
    root, binding, args = make_case(tmp_path, monkeypatch, denied=False)
    snapshot = r1.inventory(root, binding, **args)
    plan = guarded.plan_base_markdown(snapshot, check='action_state_transitions', memory_root='memories')
    def failed(*args):
        raise audit.AuditPathBoundaryError('synthetic error')
    monkeypatch.setattr(audit, '_grep_selected_history', failed)
    out = guarded.search_base_markdown(root, binding, **args, check='action_state_transitions',
        memory_root='memories', inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: True)
    assert out['state'] == 'partial' and out['search'] == 'not_completed'
    assert out['possible_body_reads'] is True and out['gate_coverage'] == 'not_verified'


def test_denied_blob_alias_refuses_before_search(tmp_path, monkeypatch):
    root, binding, args = make_case(tmp_path, monkeypatch, denied=False, alias=True)
    snapshot = r1.inventory(root, binding, **args)
    assert snapshot['denied_oid_aliases']
    monkeypatch.setattr(audit, '_grep_selected_history', lambda *a: pytest.fail('grep executed'))
    with pytest.raises(PolicyError, match='selection unavailable'):
        guarded.plan_base_markdown(snapshot, check='action_state_transitions', memory_root='memories')


def test_changed_reference_refuses_before_search(tmp_path, monkeypatch):
    root, binding, args = make_case(tmp_path, monkeypatch, denied=False)
    snapshot = r1.inventory(root, binding, **args)
    plan = guarded.plan_base_markdown(snapshot, check='action_state_transitions', memory_root='memories')
    new_head = git(root, 'commit-tree', args['base'] + '^{tree}', '-p', args['base'], '-m', 'synthetic concurrent commit')
    calls = []
    def admit(_):
        calls.append(True)
        if len(calls) == 1:
            git(root, 'update-ref', 'refs/heads/wiki/synthetic', new_head)
        return True
    monkeypatch.setattr(audit, '_grep_selected_history', lambda *a: pytest.fail('grep executed'))
    with pytest.raises(PolicyError, match='admission changed'):
        guarded.search_base_markdown(root, binding, **args, check='action_state_transitions',
            memory_root='memories', inventory_sha256=snapshot['inventory_sha256'],
            plan_sha256=plan['plan_sha256'], admit=admit)


def test_admission_withdrawn_after_search_reports_partial_without_matches(tmp_path, monkeypatch):
    root, binding, args = make_case(tmp_path, monkeypatch, denied=False)
    snapshot = r1.inventory(root, binding, **args)
    plan = guarded.plan_base_markdown(snapshot, check='action_state_transitions', memory_root='memories')
    original = audit._grep_selected_history
    searches = []
    def search(*args):
        searches.append(True)
        return original(*args)
    monkeypatch.setattr(audit, '_grep_selected_history', search)
    def admit(_):
        return not searches
    out = guarded.search_base_markdown(root, binding, **args, check='action_state_transitions',
        memory_root='memories', inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=admit)
    assert out['state'] == 'partial' and out['search'] == 'not_completed'
    assert out['possible_body_reads'] is True and 'matching_paths' not in out
    assert out['grep_batches_attempted'] == out['grep_batches_completed'] == 1


def test_same_sha_other_symbolic_branch_refuses_before_grep(tmp_path, monkeypatch):
    root, binding, args = make_case(tmp_path, monkeypatch, denied=False)
    snapshot = r1.inventory(root, binding, **args)
    plan = guarded.plan_base_markdown(snapshot, check='action_state_transitions', memory_root='memories')
    git(root, 'branch', 'wiki/other', args['head'])
    admissions = []
    def admit(_):
        admissions.append(True)
        if len(admissions) == 2:
            git(root, 'symbolic-ref', 'HEAD', 'refs/heads/wiki/other')
        return True
    monkeypatch.setattr(audit, '_grep_selected_history', lambda *a: pytest.fail('grep executed'))
    with pytest.raises(PolicyError, match='admission changed'):
        guarded.search_base_markdown(root, binding, **args, check='action_state_transitions',
            memory_root='memories', inventory_sha256=snapshot['inventory_sha256'],
            plan_sha256=plan['plan_sha256'], admit=admit)


@pytest.mark.parametrize('kind', ['item', 'total'])
def test_declared_size_limits_refuse_before_grep(tmp_path, monkeypatch, kind):
    options = {'oversized': True} if kind == 'item' else {'extra_files': 5, 'extra_size': 1_700_000}
    root, binding, args = make_case(tmp_path, monkeypatch, denied=False, **options)
    snapshot = r1.inventory(root, binding, **args)
    plan = guarded.plan_base_markdown(snapshot, check='action_state_transitions', memory_root='memories')
    monkeypatch.setattr(audit, '_grep_selected_history', lambda *a: pytest.fail('grep executed'))
    out = guarded.search_base_markdown(root, binding, **args, check='action_state_transitions',
        memory_root='memories', inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: True)
    assert out['state'] == 'partial' and out['search'] == 'not_completed'
    assert out['size_checks_attempted'] == out['size_checks_completed'] > 0
    assert out['grep_batches_attempted'] == out['grep_batches_completed'] == 0


def test_second_batch_failure_reports_attempted_and_completed(tmp_path, monkeypatch):
    root, binding, args = make_case(tmp_path, monkeypatch, denied=False, extra_files=33)
    snapshot = r1.inventory(root, binding, **args)
    plan = guarded.plan_base_markdown(snapshot, check='action_state_transitions', memory_root='memories')
    original = audit._grep_selected_history
    calls = []
    def search(*args):
        calls.append(True)
        if len(calls) == 2:
            raise audit.AuditPathBoundaryError('synthetic second batch failure')
        return original(*args)
    monkeypatch.setattr(audit, '_grep_selected_history', search)
    out = guarded.search_base_markdown(root, binding, **args, check='action_state_transitions',
        memory_root='memories', inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: True)
    assert out['state'] == 'partial' and out['search'] == 'not_completed'
    assert out['grep_batches_attempted'] == 2 and out['grep_batches_completed'] == 1
    assert out['possible_body_reads'] is True and 'matching_paths' not in out
