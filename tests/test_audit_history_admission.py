"""Synthetic base-history selection; not a complete audit or OS observation."""
import os
from pathlib import Path
import subprocess
import sys
import json

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
    assert plan['bootstrap_requirements']['git_attributes'] == {
        'possible_sources': 'worktree_including_ignored_or_external',
        'timing': 'bootstrap_or_search_may_read', 'authority': 'external_not_verified'}
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
               ('intermediate_bodies', 'index_bodies'))
    assert out['coverage']['base_other_bodies'] == 'bootstrap_policy_context_or_attributes_may_be_read'
    assert out['coverage']['worktree_bodies'] == out['coverage']['ignored_bodies'] == 'bootstrap_ignore_or_git_attributes_may_be_read'
    assert out['coverage']['commit_messages'] == 'bootstrap_read_not_scanned'
    assert all(out['bootstrap_reads'][key] == value for key, value in snapshot['bootstrap_reads'].items())
    assert out['bootstrap_reads']['git_attributes'] == 'may_be_read_by_git_including_ignored_or_external'


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


def test_wrong_initial_symbolic_branch_refuses_before_inventory(tmp_path, monkeypatch):
    root, binding, args = make_case(tmp_path, monkeypatch, denied=False)
    snapshot = r1.inventory(root, binding, **args)
    plan = guarded.plan_base_markdown(snapshot, check='action_state_transitions', memory_root='memories')
    git(root, 'branch', 'wiki/other', args['head'])
    git(root, 'symbolic-ref', 'HEAD', 'refs/heads/wiki/other')
    monkeypatch.setattr(r1, 'inventory', lambda *a, **kw: pytest.fail('inventory read bootstrap'))
    monkeypatch.setattr(audit, '_grep_selected_history', lambda *a: pytest.fail('grep executed'))
    with pytest.raises(PolicyError, match='branch unavailable'):
        guarded.search_base_markdown(root, binding, **args, check='action_state_transitions',
            memory_root='memories', inventory_sha256=snapshot['inventory_sha256'],
            plan_sha256=plan['plan_sha256'], admit=lambda _: True)


@pytest.mark.parametrize('ref', ['refs/heads/wiki/synthetic', 'refs/remotes/origin/main'])
def test_stale_initial_refs_refuse_before_inventory(tmp_path, monkeypatch, ref):
    root, binding, args = make_case(tmp_path, monkeypatch, denied=False)
    snapshot = r1.inventory(root, binding, **args)
    plan = guarded.plan_base_markdown(snapshot, check='action_state_transitions', memory_root='memories')
    other = git(root, 'commit-tree', args['base'] + '^{tree}', '-p', args['base'], '-m', 'synthetic newer commit')
    git(root, 'update-ref', ref, other)
    monkeypatch.setattr(r1, 'inventory', lambda *a, **kw: pytest.fail('inventory read bootstrap'))
    monkeypatch.setattr(audit, '_grep_selected_history', lambda *a: pytest.fail('grep executed'))
    with pytest.raises(PolicyError, match='branch unavailable'):
        guarded.search_base_markdown(root, binding, **args, check='action_state_transitions',
            memory_root='memories', inventory_sha256=snapshot['inventory_sha256'],
            plan_sha256=plan['plan_sha256'], admit=lambda _: True)


def test_context_bootstrap_reads_are_reported_separately(tmp_path, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    root, binding, args = make_case(tmp_path, monkeypatch, denied=False)
    snapshot = r1.inventory(root, binding, **args)
    plan = guarded.plan_base_markdown(snapshot, check='action_state_transitions', memory_root='memories')
    original = RepositoryReader._document
    opened = []
    def observe(reader, path, *a, **kw):
        opened.append(path)
        return original(reader, path, *a, **kw)
    monkeypatch.setattr(RepositoryReader, '_document', observe)
    out = guarded.search_base_markdown(root, binding, **args, check='action_state_transitions',
        memory_root='memories', inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=lambda _: True)
    assert {'AGENTS.md', 'index.md'} <= set(opened)
    assert out['bootstrap_reads']['context'] == 'read_may_overlap_target_paths'
    assert out['coverage']['base_other_bodies'] == 'bootstrap_policy_context_or_attributes_may_be_read'
    assert out['state'] == 'partial' and out['gate_coverage'] == 'not_verified'


@pytest.mark.skipif(os.name == 'nt' or not hasattr(os, 'mkfifo'), reason='requires a POSIX FIFO')
def test_legacy_git_grep_may_open_ignored_attributes(tmp_path, monkeypatch):
    """A FIFO proves a real Git read; this is not an OS-wide trace of the helper."""
    root, _, args = make_case(tmp_path, monkeypatch, denied=False)
    (root / '.git/info/exclude').write_text('/.gitattributes\n')
    os.mkfifo(root / '.gitattributes')
    assert git(root, 'check-ignore', '.gitattributes') == '.gitattributes'
    original = subprocess.run
    timed_out = []
    def bound(argv, *a, **kw):
        if isinstance(argv, (list, tuple)) and 'grep' in argv:
            kw['timeout'] = 1
            try:
                return original(argv, *a, **kw)
            except subprocess.TimeoutExpired:
                timed_out.append(True)
                raise
        return original(argv, *a, **kw)
    monkeypatch.setattr(subprocess, 'run', bound)
    with pytest.raises(audit.AuditPathBoundaryError, match='search unavailable'):
        audit._grep_selected_history(args['base'], r'page_type[[:space:]]*:',
                                     ['memories/actions/allowed.md'])
    assert timed_out == [True]


@pytest.mark.skipif(os.name == 'nt' or not hasattr(os, 'mkfifo'), reason='requires a POSIX FIFO')
def test_guarded_fifo_attributes_refuses_before_grep(tmp_path, monkeypatch):
    root, binding, args = make_case(tmp_path, monkeypatch, denied=False)
    (root / '.git/info/exclude').write_text('/.gitattributes\n')
    snapshot = r1.inventory(root, binding, **args)
    plan = guarded.plan_base_markdown(snapshot, check='action_state_transitions', memory_root='memories')
    os.mkfifo(root / '.gitattributes')
    monkeypatch.setattr(audit, '_grep_selected_history', lambda *a: pytest.fail('grep executed'))
    with pytest.raises(PolicyError, match='worktree entry unsupported'):
        guarded.search_base_markdown(root, binding, **args, check='action_state_transitions',
            memory_root='memories', inventory_sha256=snapshot['inventory_sha256'],
            plan_sha256=plan['plan_sha256'], admit=lambda _: True)


def test_ignored_regular_attributes_are_disclosed_as_bootstrap(tmp_path, monkeypatch):
    root, binding, args = make_case(tmp_path, monkeypatch, denied=False)
    (root / '.git/info/exclude').write_text('/.gitattributes\n')
    (root / '.gitattributes').write_text('*.md text\n')
    snapshot = r1.inventory(root, binding, **args)
    assert '.gitattributes' in snapshot['ignored']
    plan = guarded.plan_base_markdown(snapshot, check='action_state_transitions', memory_root='memories')
    expected = {'possible_sources': 'worktree_including_ignored_or_external',
                'timing': 'bootstrap_or_search_may_read', 'authority': 'external_not_verified'}
    assert plan['bootstrap_requirements']['git_attributes'] == expected
    received = []
    original = audit._grep_selected_history
    def admit(candidate):
        received.append(candidate['bootstrap_requirements']['git_attributes'])
        return True
    def search(*args):
        assert received and all(value == expected for value in received)
        return original(*args)
    monkeypatch.setattr(audit, '_grep_selected_history', search)
    out = guarded.search_base_markdown(root, binding, **args, check='action_state_transitions',
        memory_root='memories', inventory_sha256=snapshot['inventory_sha256'],
        plan_sha256=plan['plan_sha256'], admit=admit)
    assert out['search'] == 'completed' and out['state'] == 'partial'
    assert received and all(value == expected for value in received)
    assert out['bootstrap_reads']['git_attributes'] == 'may_be_read_by_git_including_ignored_or_external'


def invoke_audit_cli(monkeypatch, args, check, *, plan=False, inventory=None, selection=None):
    argv = ['wiki_audit.py', '--check', '--only', check, '--context-guard', '.',
            '--context-policy-revision', args['approved_revision'], '--context-base', args['base'],
            '--context-head', args['head'], '--context-branch', args['branch'],
            '--context-normative', 'wiki.config.yaml']
    if plan:
        argv.append('--context-plan')
    else:
        argv.extend(['--context-inventory-sha256', inventory, '--context-selection-sha256', selection])
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setenv('WIKI_COORDINATION_ALLOWED_CONTEXTS', '.')
    monkeypatch.setenv('WIKI_COORDINATION_TRUSTED_REF', 'refs/remotes/origin/main')
    monkeypatch.delenv('WIKI_COORDINATION_CONTEXT_MODE', raising=False)
    monkeypatch.delenv('WIKI_COORDINATION_MANIFEST', raising=False)
    monkeypatch.delenv('WIKI_COORDINATION_REPOSITORY_GRANTS', raising=False)
    return audit.main()


@pytest.mark.parametrize('check', ['action_state_transitions', 'source_lifecycle_transitions'])
def test_cli_denied_base_candidate_refuses_before_grep(tmp_path, monkeypatch, capsys, check):
    _, _, args = make_case(tmp_path, monkeypatch, denied=True)
    monkeypatch.setattr(audit, '_grep_selected_history', lambda *a: pytest.fail('grep executed'))
    monkeypatch.setattr(audit, '_history_text', lambda *a: pytest.fail('history body opened'))
    assert invoke_audit_cli(monkeypatch, args, check, plan=True) == 1
    output = json.loads(capsys.readouterr().out)
    assert output['state'] == 'refused'
    assert output['gate_state'] == 'blocked_incomplete_coverage'
    assert output['global_audit'] == 'not_performed'
    assert invoke_audit_cli(monkeypatch, args, check, inventory='0' * 64, selection='0' * 64) == 1
    assert json.loads(capsys.readouterr().out)['state'] == 'refused'


@pytest.mark.parametrize('check', ['action_state_transitions', 'source_lifecycle_transitions'])
def test_cli_admitted_history_search_never_passes_transition_gate(tmp_path, monkeypatch, capsys, check):
    _, _, args = make_case(tmp_path, monkeypatch, denied=False)
    assert invoke_audit_cli(monkeypatch, args, check, plan=True) == 1
    proposed = json.loads(capsys.readouterr().out)
    assert proposed['state'] == 'selection_only'
    assert proposed['gate_state'] == 'blocked_incomplete_coverage'
    assert proposed['plan']['target_bodies'] == 'not_read_by_selector_bootstrap_may_overlap'
    original = audit._grep_selected_history
    calls = []
    def observe(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(audit, '_grep_selected_history', observe)
    assert invoke_audit_cli(monkeypatch, args, check,
        inventory=proposed['inventory_sha256'], selection='0' * 64) == 1
    assert json.loads(capsys.readouterr().out)['state'] == 'refused' and not calls
    assert invoke_audit_cli(monkeypatch, args, check,
        inventory=proposed['inventory_sha256'], selection=proposed['plan']['plan_sha256']) == 1
    output = json.loads(capsys.readouterr().out)
    assert calls and output['search'] == 'completed' and output['state'] == 'partial'
    assert output['gate_state'] == 'blocked_incomplete_coverage'
    assert output['global_audit'] == 'not_performed' and 'matching_paths' not in output


def test_mixed_guarded_cli_refuses_before_inventory(tmp_path, monkeypatch, capsys):
    _, _, args = make_case(tmp_path, monkeypatch, denied=False)
    monkeypatch.setattr(r1, 'inventory', lambda *a, **kw: pytest.fail('inventory executed'))
    assert invoke_audit_cli(monkeypatch, args, 'action_state_transitions,secrets', plan=True) == 1
    assert 'coverage unavailable' in capsys.readouterr().out


def test_history_plan_rejects_explicit_empty_digest_before_inventory(tmp_path, monkeypatch, capsys):
    _, _, args = make_case(tmp_path, monkeypatch, denied=False)
    monkeypatch.setattr(r1, 'inventory', lambda *a, **kw: pytest.fail('inventory executed'))
    argv = ['wiki_audit.py', '--check', '--only', 'action_state_transitions', '--context-guard', '.',
            '--context-policy-revision', args['approved_revision'], '--context-base', args['base'],
            '--context-head', args['head'], '--context-branch', args['branch'], '--context-normative',
            'wiki.config.yaml', '--context-plan', '--context-inventory-sha256', '']
    monkeypatch.setattr(sys, 'argv', argv)
    assert audit.main() == 1
    assert 'coverage unavailable' in capsys.readouterr().out


@pytest.mark.parametrize('option', ['--query-context', '--query-policy-revision', '--query-head',
                                    '--freshness-base'])
@pytest.mark.parametrize('mode', ['plan', 'execute', 'secrets'])
def test_empty_incompatible_option_refuses_before_guarded_bootstrap(monkeypatch, capsys, option, mode):
    def unexpected(*_args, **_kwargs):
        pytest.fail('incompatible mode reached a guarded or global reader')
    monkeypatch.setattr(audit, 'audit_context_bound_history', unexpected)
    monkeypatch.setattr(audit, 'audit_context_bound_secrets', unexpected)
    monkeypatch.setattr(audit, 'load_config', unexpected)
    argv = ['wiki_audit.py', '--check', '--context-guard', '.', '--context-policy-revision', '0' * 40]
    if mode == 'secrets':
        argv += ['--only', 'secrets', '--context-selection-sha256', '0' * 64]
    else:
        argv += ['--only', 'action_state_transitions', '--context-base', '0' * 40,
                 '--context-head', '1' * 40, '--context-branch', 'wiki/synthetic',
                 '--context-normative', 'wiki.config.yaml']
        if mode == 'plan':
            argv += ['--context-plan']
        else:
            argv += ['--context-inventory-sha256', '0' * 64, '--context-selection-sha256', '1' * 64]
    monkeypatch.setattr(sys, 'argv', argv + [option, ''])
    assert audit.main() == 1
    assert 'coverage unavailable' in capsys.readouterr().out


@pytest.mark.parametrize('path', ['', '   '])
def test_empty_normative_path_refuses_before_precheck(monkeypatch, capsys, path):
    monkeypatch.setattr(audit, 'audit_context_bound_history',
                        lambda **kwargs: pytest.fail('history precheck executed'))
    monkeypatch.setattr(sys, 'argv', ['wiki_audit.py', '--check', '--only', 'action_state_transitions',
        '--context-guard', '.', '--context-policy-revision', '0' * 40, '--context-base', '0' * 40,
        '--context-head', '1' * 40, '--context-branch', 'wiki/synthetic', '--context-normative', path,
        '--context-plan'])
    assert audit.main() == 1
    assert 'coverage unavailable' in capsys.readouterr().out


def test_direct_cli_empty_query_option_refuses_before_precheck():
    child = r'''
import runpy, subprocess, sys
import wiki_core.config as config
def blocked(*args, **kwargs):
    raise RuntimeError('SYNTHETIC_UNGUARDED_BOOTSTRAP')
config.load_config = blocked
subprocess.Popen = blocked
script = sys.argv[1]
sys.argv = [script, '--check', '--only', 'action_state_transitions', '--context-guard', '.',
            '--context-policy-revision', '0' * 40, '--context-base', '0' * 40,
            '--context-head', '1' * 40, '--context-branch', 'wiki/synthetic',
            '--context-normative', 'wiki.config.yaml', '--context-plan', '--query-context', '']
runpy.run_path(script, run_name='__main__')
'''
    result = subprocess.run([sys.executable, '-c', child, str(Path(audit.__file__).resolve())],
                            cwd=Path(audit.__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert 'coverage unavailable' in result.stdout.lower()
    assert 'SYNTHETIC_UNGUARDED_BOOTSTRAP' not in result.stderr


@pytest.mark.parametrize('option', ['--context-base', '--context-head', '--context-branch',
                                    '--context-inventory-sha256'])
@pytest.mark.parametrize('mode', ['secrets', 'list', 'guarded-secrets'])
def test_empty_history_option_refuses_before_global_bootstrap(tmp_path, option, mode):
    # A fresh CLI process catches fallthrough during import/dispatch too. The
    # spies cover these specific calls, not every possible OS-level read.
    child = r'''
import runpy, subprocess, sys
from pathlib import Path
root, script, option, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
import scripts._common as common
common.ROOT = root
import wiki_core.config as config
def blocked(*args, **kwargs):
    raise RuntimeError('SYNTHETIC_UNGUARDED_BOOTSTRAP')
config.load_config = blocked
subprocess.Popen = blocked
sys.argv = [script, option, '']
if mode == 'list':
    sys.argv += ['--list-checks']
else:
    sys.argv += ['--check', '--only', 'secrets']
    if mode == 'guarded-secrets':
        sys.argv += ['--context-guard', '.', '--context-policy-revision', '0' * 40,
                     '--context-selection-sha256', '0' * 64]
runpy.run_path(script, run_name='__main__')
'''
    result = subprocess.run([sys.executable, '-c', child, str(tmp_path),
                             str(Path(audit.__file__).resolve()), option, mode],
                            cwd=Path(audit.__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert 'coverage unavailable' in result.stdout.lower()
    assert 'not completed' in result.stdout.lower()
    assert 'SYNTHETIC_UNGUARDED_BOOTSTRAP' not in result.stderr
    assert '0 error(s)' not in result.stdout


def test_direct_cli_refuses_denied_search_with_synthetic_binding(tmp_path, monkeypatch):
    root, _, args = make_case(tmp_path, monkeypatch, denied=True)
    env = {'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1',
           'WIKI_INSTALLED_CONTENT_ROOT': str(root), 'WIKI_COORDINATION_ALLOWED_CONTEXTS': '.',
           'WIKI_COORDINATION_TRUSTED_REF': 'refs/remotes/origin/main'}
    argv = [sys.executable, str(Path(audit.__file__).resolve()), '--check', '--only',
            'action_state_transitions', '--context-guard', '.', '--context-policy-revision',
            args['approved_revision'], '--context-base', args['base'], '--context-head', args['head'],
            '--context-branch', args['branch'], '--context-normative', 'wiki.config.yaml', '--context-plan']
    result = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output['state'] == 'refused' and output['gate_state'] == 'blocked_incomplete_coverage'


def test_direct_cli_admitted_search_remains_partial(tmp_path, monkeypatch):
    root, _, args = make_case(tmp_path, monkeypatch, denied=False)
    env = {'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1',
           'WIKI_INSTALLED_CONTENT_ROOT': str(root), 'WIKI_COORDINATION_ALLOWED_CONTEXTS': '.',
           'WIKI_COORDINATION_TRUSTED_REF': 'refs/remotes/origin/main'}
    argv = [sys.executable, str(Path(audit.__file__).resolve()), '--check', '--only',
            'source_lifecycle_transitions', '--context-guard', '.', '--context-policy-revision',
            args['approved_revision'], '--context-base', args['base'], '--context-head', args['head'],
            '--context-branch', args['branch'], '--context-normative', 'wiki.config.yaml']
    proposed = subprocess.run(argv + ['--context-plan'], cwd=root, env=env,
                              capture_output=True, text=True, timeout=30)
    assert proposed.returncode == 1
    plan = json.loads(proposed.stdout)
    assert plan['state'] == 'selection_only'
    result = subprocess.run(argv + ['--context-inventory-sha256', plan['inventory_sha256'],
                            '--context-selection-sha256', plan['plan']['plan_sha256']],
                            cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output['state'] == 'partial' and output['search'] == 'completed'
    assert output['gate_state'] == 'blocked_incomplete_coverage'
    assert output['global_audit'] == 'not_performed' and 'matching_paths' not in output


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
