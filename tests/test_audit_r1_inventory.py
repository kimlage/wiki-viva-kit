"""Synthetic boundary tests for the R1 inventory, not a global audit."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from wiki_core import audit_r1_inventory as r1
from wiki_core.context_policy import PolicyError
from wiki_core.coordination_context import CoordinationBinding


def git(root: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    if sys.platform == 'win32':
        pytest.skip('R1 inventory is not qualified on Windows')
    root = tmp_path / 'synthetic'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Synthetic')
    git(root, 'config', 'user.email', 'synthetic@example.invalid')
    (root / 'AGENTS.md').write_text('# synthetic instructions\n')
    (root / 'index.md').write_text('# synthetic index\n')
    (root / '.gitignore').write_text('cache/\n')
    (root / 'restricted').mkdir()
    (root / 'restricted/denied.json').write_text('{"synthetic":"denied"}\n')
    (root / 'allowed.md').write_text('approved base\n')
    config = {'context_access': {'.': {'owner': 'Synthetic', 'policy': {
        'read': ['self'], 'write': ['self'], 'deny': {'read': ['self/restricted']},
        'capabilities': [], 'publication': []}}}}
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'synthetic base')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', base)
    git(root, 'checkout', '-qb', 'wiki/synthetic')
    (root / 'allowed.md').write_text('intermediate synthetic blob\n')
    git(root, 'add', 'allowed.md')
    git(root, 'commit', '-qm', 'synthetic intermediate message')
    middle = git(root, 'rev-parse', 'HEAD')
    (root / 'allowed.md').write_text('final synthetic blob\n')
    git(root, 'add', 'allowed.md')
    git(root, 'commit', '-qm', 'synthetic final message')
    head = git(root, 'rev-parse', 'HEAD')
    (root / 'allowed.md').write_text('staged synthetic WIP\n')
    git(root, 'add', 'allowed.md')
    (root / 'allowed.md').write_text('unstaged synthetic WIP\n')
    (root / 'new.txt').write_text('untracked synthetic WIP\n')
    (root / 'cache').mkdir()
    (root / 'cache/ignored.txt').write_text('ignored synthetic WIP\n')
    return root, base, middle, head


def test_windows_refuses_before_bootstrap(tmp_path, monkeypatch):
    monkeypatch.setattr(r1.sys, 'platform', 'win32')
    monkeypatch.setattr(r1, '_git', lambda *_: pytest.fail('Git bootstrap ran on Windows'))
    with pytest.raises(PolicyError, match='platform unavailable'):
        r1.inventory(tmp_path / 'missing', CoordinationBinding(('.',), 'refs/remotes/origin/main'),
                     context_id='.', approved_revision='a' * 40, base='a' * 40,
                     head='b' * 40, branch='wiki/synthetic', normative_paths=['wiki.config.yaml'])


@pytest.mark.parametrize('relative', ['info/grafts', 'objects/info/alternates'])
def test_graph_overrides_fail_before_history_traversal(repo, monkeypatch, relative):
    root, _, _, _ = repo
    path = root / '.git' / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('synthetic override\n')
    original = r1._git
    def git_call(path, *args):
        assert 'rev-list' not in args
        return original(path, *args)
    monkeypatch.setattr(r1, '_git', git_call)
    with pytest.raises(PolicyError, match='graph override'):
        run(repo)


def run(repo):
    root, base, _, head = repo
    return r1.inventory(root, CoordinationBinding(('.',), 'refs/remotes/origin/main'),
                        context_id='.', approved_revision=base, base=base, head=head,
                        branch='wiki/synthetic', normative_paths=['wiki.config.yaml'])


def test_history_index_wip_ignored_and_denies_are_inventoried_without_body_reads(repo, monkeypatch):
    root, base, middle, head = repo
    watched = [root / name for name in ('allowed.md', 'restricted/denied.json',
                                        'new.txt', 'cache/ignored.txt')]
    before = {str(path): path.read_bytes() for path in watched}
    calls = []
    original = r1._git

    def git_call(path, *args):
        calls.append(args)
        assert not any(item in ('grep', 'show', 'cat-file', 'status', 'diff') for item in args)
        return original(path, *args)

    monkeypatch.setattr(r1, '_git', git_call)
    result = run(repo)
    assert {item['commit'] for item in result['history']} == {middle, head}
    assert set(result['trees']) == {base, middle, head}
    assert result['trees'][middle]['allowed.md'] != result['trees'][head]['allowed.md']
    assert result['coverage']['commit_messages'] == 'bootstrap_read_not_scanned'
    assert result['untracked'] == ['new.txt']
    assert result['ignored'] == ['cache/ignored.txt']
    assert result['physical']['files']['allowed.md']['content_relation'] == 'unknown'
    assert 'cache' in result['physical']['directories']
    assert next(row['current_policy'] for row in result['authorization'] if row['path'] == 'restricted/denied.json') == 'denied'
    assert result['global_audit'] == 'not_performed'
    assert result['selection_admission'] == 'not_verified'
    assert result['historical_policy'] == 'not_qualified'
    assert calls
    assert {str(path): path.read_bytes() for path in watched} == before


def test_denied_ignore_rule_blocks_before_git_ignore_enumeration(repo, monkeypatch):
    root, _, _, _ = repo
    # Qualify an additional synthetic deny without reading consumer data.
    original = r1._allowed
    monkeypatch.setattr(r1, '_allowed', lambda policy, actor, path:
                        False if path == '.gitignore' else original(policy, actor, path))
    original_git = r1._git

    def git_call(path, *args):
        assert '--others' not in args
        return original_git(path, *args)

    monkeypatch.setattr(r1, '_git', git_call)
    with pytest.raises(PolicyError, match='ignore bootstrap'):
        run(repo)


def test_intermediate_policy_change_then_revert_is_refused(repo):
    root, base, _, _ = repo
    git(root, 'reset', '--hard', base)
    config = (root / 'wiki.config.yaml').read_text()
    (root / 'wiki.config.yaml').write_text(config + '\n# synthetic candidate change\n')
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'candidate policy change')
    (root / 'wiki.config.yaml').write_text(config)
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'candidate policy revert')
    altered = (root, base, '', git(root, 'rev-parse', 'HEAD'))
    with pytest.raises(PolicyError, match='normative history'):
        run(altered)


def test_intermediate_context_instruction_change_then_revert_is_refused(repo):
    root, base, _, _ = repo
    git(root, 'reset', '--hard', base)
    original = (root / 'AGENTS.md').read_text()
    (root / 'AGENTS.md').write_text(original + 'synthetic change\n')
    git(root, 'add', 'AGENTS.md')
    git(root, 'commit', '-qm', 'change synthetic instruction')
    (root / 'AGENTS.md').write_text(original)
    git(root, 'add', 'AGENTS.md')
    git(root, 'commit', '-qm', 'revert synthetic instruction')
    with pytest.raises(PolicyError, match='normative history'):
        run((root, base, '', git(root, 'rev-parse', 'HEAD')))


def inherited_instruction_branches(repo):
    root, ancestor, _, _ = repo
    git(root, 'reset', '--hard', ancestor)
    git(root, 'checkout', '-qb', 'wiki/inherited-side')
    (root / 'allowed.md').write_text('synthetic side change\n')
    git(root, 'add', 'allowed.md')
    git(root, 'commit', '-qm', 'side inherits earlier instruction')
    side = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-q', 'wiki/synthetic')
    (root / 'AGENTS.md').write_text('approved current synthetic instruction\n')
    git(root, 'add', 'AGENTS.md')
    git(root, 'commit', '-qm', 'approved current instruction')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', base)
    return root, ancestor, side, base


def test_inherited_approved_ancestor_instruction_is_preserved_in_merge(repo):
    """Keep the side and boundary parent without inferring historical grants."""
    root, ancestor, side, base = inherited_instruction_branches(repo)
    git(root, 'merge', '--no-ff', '-qm', 'synthetic inherited merge', 'wiki/inherited-side')
    head = git(root, 'rev-parse', 'HEAD')
    assert git(root, 'show', f'{base}:AGENTS.md') == git(root, 'show', f'{head}:AGENTS.md')
    assert git(root, 'show', f'{side}:AGENTS.md') == git(root, 'show', f'{ancestor}:AGENTS.md')
    assert git(root, 'show', f'{side}:AGENTS.md') != git(root, 'show', f'{base}:AGENTS.md')
    git(root, 'merge-base', '--is-ancestor', ancestor, base)
    result = run((root, base, '', head))
    assert side in result['trees'] and ancestor in result['trees']
    assert result['trees'][side]['AGENTS.md'] == result['trees'][ancestor]['AGENTS.md']
    assert result['trees'][head]['AGENTS.md'] == result['trees'][base]['AGENTS.md']
    assert result['historical_policy'] == 'not_qualified'
    with pytest.raises(PolicyError, match='selection unavailable'):
        r1.select(result, [{'kind': 'git_blob', 'revision': side, 'path': 'restricted/denied.json'}])


@pytest.mark.parametrize('merged_instruction', ['old', 'novel'])
def test_merge_cannot_choose_old_or_create_instruction_then_restore(repo, merged_instruction):
    root, _, side, base = inherited_instruction_branches(repo)
    approved = (root / 'AGENTS.md').read_text()
    git(root, 'merge', '--no-ff', '--no-commit', 'wiki/inherited-side')
    candidate = git(root, 'show', f'{side}:AGENTS.md') + '\n' if merged_instruction == 'old' else 'new synthetic instruction\n'
    (root / 'AGENTS.md').write_text(candidate)
    git(root, 'add', 'AGENTS.md')
    git(root, 'commit', '-qm', 'synthetic disallowed merge instruction')
    (root / 'AGENTS.md').write_text(approved)
    git(root, 'add', 'AGENTS.md')
    git(root, 'commit', '-qm', 'restore approved instruction')
    with pytest.raises(PolicyError, match='normative history'):
        run((root, base, '', git(root, 'rev-parse', 'HEAD')))


def test_instruction_mode_change_then_restore_is_refused(repo):
    root, base, _, _ = repo
    git(root, 'reset', '--hard', base)
    (root / 'AGENTS.md').chmod(0o755)
    git(root, 'add', 'AGENTS.md')
    git(root, 'commit', '-qm', 'synthetic mode change')
    (root / 'AGENTS.md').chmod(0o644)
    git(root, 'add', 'AGENTS.md')
    git(root, 'commit', '-qm', 'restore mode')
    with pytest.raises(PolicyError, match='normative history'):
        run((root, base, '', git(root, 'rev-parse', 'HEAD')))


@pytest.mark.parametrize('operation', ['add', 'delete'])
def test_instruction_add_or_delete_then_restore_is_refused(repo, operation):
    root, base, _, _ = repo
    git(root, 'reset', '--hard', base)
    path = root / ('AGENTS.override.md' if operation == 'add' else 'AGENTS.md')
    original = path.read_text() if path.exists() else None
    if operation == 'add':
        path.write_text('synthetic new instruction\n')
    else:
        path.unlink()
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'synthetic normative change')
    if original is None:
        path.unlink()
    else:
        path.write_text(original)
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'restore normative state')
    with pytest.raises(PolicyError, match='normative history'):
        run((root, base, '', git(root, 'rev-parse', 'HEAD')))


def test_unrelated_merge_root_is_refused_even_with_identical_tree(repo):
    root, base, _, _ = repo
    git(root, 'reset', '--hard', base)
    tree = git(root, 'rev-parse', f'{base}^{{tree}}')
    unrelated = git(root, 'commit-tree', tree, '-m', 'synthetic unrelated root')
    merged = git(root, 'commit-tree', tree, '-p', base, '-p', unrelated, '-m', 'synthetic unrelated merge')
    git(root, 'reset', '--hard', merged)
    with pytest.raises(PolicyError, match='normative history'):
        run((root, base, '', merged))


def test_merge_cannot_assemble_normative_snapshot_from_different_parents(repo):
    root, ancestor, _, _ = repo
    git(root, 'reset', '--hard', ancestor)
    (root / 'AGENTS.override.md').write_text('synthetic old override\n')
    git(root, 'add', 'AGENTS.override.md')
    git(root, 'commit', '-qm', 'synthetic ancestor')
    common = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-qb', 'wiki/approved-left')
    (root / 'AGENTS.md').write_text('synthetic current instruction\n')
    git(root, 'add', 'AGENTS.md')
    git(root, 'commit', '-qm', 'synthetic left instruction')
    left = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-qb', 'wiki/approved-right', common)
    (root / 'AGENTS.override.md').write_text('synthetic current override\n')
    git(root, 'add', 'AGENTS.override.md')
    git(root, 'commit', '-qm', 'synthetic right instruction')
    right = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-q', 'wiki/synthetic')
    git(root, 'reset', '--hard', left)
    git(root, 'merge', '--no-ff', '-qm', 'synthetic approved merge', right)
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', base)
    tree = git(root, 'rev-parse', f'{base}^{{tree}}')
    left_child = git(root, 'commit-tree', git(root, 'rev-parse', f'{left}^{{tree}}'),
                     '-p', left, '-m', 'synthetic inherited left')
    right_child = git(root, 'commit-tree', git(root, 'rev-parse', f'{right}^{{tree}}'),
                      '-p', right, '-m', 'synthetic inherited right')
    mixed = git(root, 'commit-tree', tree, '-p', left_child, '-p', right_child,
                '-m', 'synthetic combined instructions')
    head = git(root, 'commit-tree', tree, '-p', base, '-p', mixed, '-m', 'synthetic final merge')
    git(root, 'reset', '--hard', head)
    with pytest.raises(PolicyError, match='normative history'):
        run((root, base, '', head))


def test_three_parent_merge_cannot_select_old_instruction(repo):
    root, _, side, base = inherited_instruction_branches(repo)
    base_tree = git(root, 'rev-parse', f'{base}^{{tree}}')
    side_tree = git(root, 'rev-parse', f'{side}^{{tree}}')
    current = git(root, 'commit-tree', base_tree, '-p', base, '-m', 'synthetic current parent')
    old = git(root, 'commit-tree', side_tree, '-p', base, '-p', current, '-p', side,
              '-m', 'synthetic old three-parent merge')
    # The final merge itself preserves the approved parent. Rejection must be
    # caused by the earlier three-parent merge that selected the older entry.
    head = git(root, 'commit-tree', base_tree, '-p', base, '-p', old,
               '-m', 'preserve approved instruction')
    git(root, 'reset', '--hard', head)
    with pytest.raises(PolicyError, match='normative history'):
        run((root, base, '', head))


def test_staged_context_instruction_change_is_refused(repo, monkeypatch):
    root, _, _, _ = repo
    with (root / 'AGENTS.md').open('a') as stream:
        stream.write('synthetic staged instruction\n')
    git(root, 'add', 'AGENTS.md')
    monkeypatch.setattr(r1, '_physical', lambda *_: pytest.fail('worktree inventoried after normative index change'))
    with pytest.raises(PolicyError, match='normative index'):
        run(repo)


def test_new_untracked_context_instruction_is_refused(repo):
    root, _, _, _ = repo
    (root / 'newcontext').mkdir()
    (root / 'newcontext/AGENTS.md').write_text('synthetic untracked instruction\n')
    with pytest.raises(PolicyError, match='normative worktree'):
        run(repo)


def test_host_declared_normative_path_is_checked_in_history(repo):
    root, base, _, head = repo
    with pytest.raises(PolicyError, match='normative history'):
        r1.inventory(root, CoordinationBinding(('.',), 'refs/remotes/origin/main'),
                     context_id='.', approved_revision=base, base=base, head=head,
                     branch='wiki/synthetic', normative_paths=['wiki.config.yaml', 'allowed.md'])


def test_host_must_explicitly_include_config_in_normative_scope(repo):
    root, base, _, head = repo
    with pytest.raises(PolicyError, match='normative scope'):
        r1.inventory(root, CoordinationBinding(('.',), 'refs/remotes/origin/main'),
                     context_id='.', approved_revision=base, base=base, head=head,
                     branch='wiki/synthetic', normative_paths=['allowed.md'])


def test_hardlink_alias_refuses_inventory_without_deleting_wip(repo):
    root, _, _, _ = repo
    alias = root / 'alias.txt'
    try:
        os.link(root / 'restricted/denied.json', alias)
    except OSError:
        pytest.skip('hardlinks unavailable')
    with pytest.raises(PolicyError, match='unsupported'):
        run(repo)
    assert alias.exists()


def test_denied_oid_alias_is_visible_before_any_target_read(repo):
    root, base, _, _ = repo
    git(root, 'reset', '--hard', base)
    (root / 'allowed.md').write_bytes((root / 'restricted/denied.json').read_bytes())
    git(root, 'add', 'allowed.md')
    git(root, 'commit', '-qm', 'synthetic alias')
    result = run((root, base, '', git(root, 'rev-parse', 'HEAD')))
    denied_oid = result['trees'][base]['restricted/denied.json']['oid']
    assert denied_oid in result['denied_oid_aliases']
    assert result['other_target_bodies'] == 'not_intentionally_read'
    with pytest.raises(PolicyError, match='selection unavailable'):
        r1.select(result, [{'kind': 'git_blob', 'revision': result['head'], 'path': 'allowed.md'}])


def test_graph_reads_admitted_worktree_bodies_from_r1_selection(repo, monkeypatch):
    from wiki_core.config import WikiConfig
    from wiki_core.graph.page_graph import build_page_graph, select_page_graph_inputs

    root, _, _, _ = repo
    memory = root / 'memories'
    memory.mkdir()
    (memory / 'index.md').write_text('---\npage_id: root\npage_type: root_index\ntitle: Root\n---\n')
    (memory / 'note.md').write_text('---\npage_id: note\npage_type: note\ntitle: Note\n---\n')
    (memory / 'cache').mkdir()
    (memory / 'cache/ignored.md').write_text('---\npage_id: ignored\npage_type: note\ntitle: Ignored\n---\n')
    snapshot = run(repo)
    assert 'memories/cache/ignored.md' in snapshot['ignored']
    names = sorted(path for path in snapshot['physical']['files']
                   if path.startswith('memories/') and path.endswith('.md'))
    plan = select_page_graph_inputs(snapshot, WikiConfig())
    selection = plan['selection']
    assert sorted(item['path'] for item in selection['inputs']) == names
    assert selection['external_admission'] == 'not_verified'
    assert plan['worktree_content_aliases'] == 'external_not_verified'
    assert plan['global_audit'] == 'not_performed'
    # A fixture-only host admits the selection; neither this stub nor its
    # digest proves authority in a real deployment.
    fixture_host_approves = lambda _candidate: True
    assert fixture_host_approves(plan)
    contents = {item['path']: r1._worktree_bytes(root, item) for item in selection['inputs']}
    reads = r1.SelectedReads(root, snapshot['physical'], contents, missing=snapshot['missing_tracked'])
    monkeypatch.setattr(Path, 'read_text', lambda *a, **kw: pytest.fail('graph opened worktree body'))
    graph = build_page_graph(root, WikiConfig(), reads=reads)
    assert set(graph.nodes) == set(names)
    assert snapshot['global_audit'] == 'not_performed' and selection['gate_coverage'] == 'not_verified'


def test_graph_candidate_deny_refuses_r1_selection_before_worktree_body(repo, monkeypatch):
    from wiki_core.config import WikiConfig
    from wiki_core.graph.page_graph import select_page_graph_inputs

    root, _, _, _ = repo
    (root / 'restricted/denied.md').write_text('synthetic denied graph page\n')
    snapshot = run(repo)
    names = sorted(path for path in snapshot['physical']['files'] if path.endswith('.md'))
    assert 'restricted/denied.md' in names
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('body read before denial'))
    config = WikiConfig()
    config.paths['memory_root'] = '.'
    with pytest.raises(PolicyError, match='selection unavailable'):
        select_page_graph_inputs(snapshot, config)


def test_graph_known_git_alias_refuses_before_worktree_body(repo, monkeypatch):
    from wiki_core.config import WikiConfig
    from wiki_core.graph.page_graph import select_page_graph_inputs

    root, base, _, _ = repo
    git(root, 'reset', '--hard', base)
    (root / 'allowed.md').write_bytes((root / 'restricted/denied.json').read_bytes())
    git(root, 'add', 'allowed.md')
    git(root, 'commit', '-qm', 'synthetic graph alias')
    head = git(root, 'rev-parse', 'HEAD')
    snapshot = run((root, base, '', head))
    assert snapshot['trees'][head]['allowed.md']['oid'] in snapshot['denied_oid_aliases']
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('body read before alias refusal'))
    config = WikiConfig()
    config.paths['memory_root'] = '.'
    with pytest.raises(PolicyError, match='graph selection unavailable'):
        select_page_graph_inputs(snapshot, config)


def test_graph_index_only_alias_refuses_before_worktree_body(repo, monkeypatch):
    from wiki_core.config import WikiConfig
    from wiki_core.graph.page_graph import select_page_graph_inputs

    root, _, _, head = repo
    (root / 'allowed.md').write_bytes((root / 'restricted/denied.json').read_bytes())
    git(root, 'add', 'allowed.md')
    snapshot = run(repo)
    assert snapshot['trees'][head]['allowed.md']['oid'] not in snapshot['denied_oid_aliases']
    assert next(entry['oid'] for entry in snapshot['index'] if entry['path'] == 'allowed.md') in snapshot['denied_oid_aliases']
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('body read before index alias refusal'))
    config = WikiConfig()
    config.paths['memory_root'] = '.'
    with pytest.raises(PolicyError, match='graph selection unavailable'):
        select_page_graph_inputs(snapshot, config)


def test_graph_index_conflict_refuses_before_worktree_body(repo, monkeypatch):
    from wiki_core.config import WikiConfig
    from wiki_core.graph.page_graph import select_page_graph_inputs

    root, _, _, _ = repo
    oid = git(root, 'rev-parse', 'HEAD:allowed.md')
    git(root, 'update-index', '--force-remove', 'allowed.md')
    subprocess.run(['git', '-C', str(root), 'update-index', '--index-info'], check=True,
                   input=f'100644 {oid} 1\tallowed.md\n100644 {oid} 2\tallowed.md\n', text=True)
    snapshot = run(repo)
    assert {entry['stage'] for entry in snapshot['index'] if entry['path'] == 'allowed.md'} == {1, 2}
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('body read before conflict refusal'))
    config = WikiConfig()
    config.paths['memory_root'] = '.'
    with pytest.raises(PolicyError, match='graph selection unavailable'):
        select_page_graph_inputs(snapshot, config)


def test_graph_missing_tracked_candidate_refuses_before_worktree_body(repo, monkeypatch):
    from wiki_core.config import WikiConfig
    from wiki_core.graph.page_graph import select_page_graph_inputs

    root, _, _, _ = repo
    git(root, 'rm', '-f', 'allowed.md')
    snapshot = run(repo)
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('body read before missing refusal'))
    config = WikiConfig()
    config.paths['memory_root'] = '.'
    with pytest.raises(PolicyError, match='graph selection unavailable'):
        select_page_graph_inputs(snapshot, config)


def test_graph_over_limit_candidate_refuses_before_worktree_body(repo, monkeypatch):
    from wiki_core.config import WikiConfig
    from wiki_core.graph.page_graph import select_page_graph_inputs

    root, _, _, _ = repo
    memory = root / 'memories'
    memory.mkdir()
    (memory / 'oversized.md').write_bytes(b'x' * 2_000_001)
    snapshot = run(repo)
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('body read before size refusal'))
    with pytest.raises(PolicyError, match='graph selection unavailable'):
        select_page_graph_inputs(snapshot, WikiConfig())


def test_graph_total_limit_refuses_before_worktree_body(repo, monkeypatch):
    from wiki_core.config import WikiConfig
    from wiki_core.graph.page_graph import select_page_graph_inputs

    root, _, _, _ = repo
    memory = root / 'memories'
    memory.mkdir()
    for number in range(5):
        (memory / f'{number}.md').write_bytes(b'x' * 1_700_000)
    snapshot = run(repo)
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('body read before total size refusal'))
    with pytest.raises(PolicyError, match='graph selection unavailable'):
        select_page_graph_inputs(snapshot, WikiConfig())


def test_graph_plan_digest_changes_when_inventory_selection_changes(repo):
    from wiki_core.config import WikiConfig
    from wiki_core.graph.page_graph import select_page_graph_inputs

    root, _, _, _ = repo
    memory = root / 'memories'
    memory.mkdir()
    (memory / 'index.md').write_text('synthetic root\n')
    before = select_page_graph_inputs(run(repo), WikiConfig())
    (memory / 'note.md').write_text('synthetic note\n')
    after = select_page_graph_inputs(run(repo), WikiConfig())
    assert before['selection']['selection_sha256'] != after['selection']['selection_sha256']
    assert before['plan_sha256'] != after['plan_sha256']


def test_merge_parents_and_missing_tracked_worktree_are_explicit(repo):
    root, base, _, _ = repo
    git(root, 'reset', '--hard', base)
    git(root, 'checkout', '-qb', 'wiki/side')
    (root / 'side.md').write_text('synthetic side\n')
    git(root, 'add', 'side.md')
    git(root, 'commit', '-qm', 'synthetic side message')
    side = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-q', 'wiki/synthetic')
    (root / 'main.md').write_text('synthetic main\n')
    git(root, 'add', 'main.md')
    git(root, 'commit', '-qm', 'synthetic main message')
    git(root, 'merge', '--no-ff', '-qm', 'synthetic merge message', 'wiki/side')
    head = git(root, 'rev-parse', 'HEAD')
    (root / 'allowed.md').unlink()
    result = run((root, base, '', head))
    merge = next(item for item in result['history'] if item['commit'] == head)
    assert len(merge['parents']) == 2 and side in merge['parents']
    assert side in result['trees']
    assert 'allowed.md' in result['missing_tracked']


def test_six_commit_messages_and_five_intermediate_denied_blobs_are_not_scanned(repo):
    root, base, _, _ = repo
    git(root, 'reset', '--hard', base)
    commits = []
    for number in range(6):
        if number < 5:
            (root / 'restricted/denied.json').write_text(f'{{"synthetic_revision":{number}}}\n')
            (root / 'allowed.md').write_text(f'synthetic allowed revision {number}\n')
        else:
            (root / 'allowed.md').write_text('sixth synthetic change\n')
        git(root, 'add', 'restricted/denied.json', 'allowed.md')
        git(root, 'commit', '-qm', f'synthetic message {number}')
        commits.append(git(root, 'rev-parse', 'HEAD'))
    result = run((root, base, '', commits[-1]))
    assert {entry['commit'] for entry in result['history']} == set(commits)
    assert len({result['trees'][sha]['restricted/denied.json']['oid'] for sha in commits[:5]}) == 5
    assert result['coverage']['commit_messages'] == 'bootstrap_read_not_scanned'
    assert next(row['current_policy'] for row in result['authorization']
                if row['path'] == 'restricted/denied.json') == 'denied'
    assert result['global_audit'] == 'not_performed'
    requested = ([{'kind': 'git_blob', 'revision': sha, 'path': 'allowed.md'} for sha in commits[:5]]
                 + [{'kind': 'message', 'revision': sha} for sha in commits])
    selection = r1.select(result, requested)
    output = scan((root, base, '', commits[-1]), requested, result, selection, lambda _: True)
    assert output['state'] == 'completed'
    assert output['scanned_count'] == 11
    assert output['gate_coverage'] == 'not_verified'


def test_worktree_branch_must_match_the_selected_head(repo, monkeypatch):
    root, _, _, _ = repo
    git(root, 'checkout', '-qb', 'wiki/other')
    monkeypatch.setattr(r1, '_index', lambda *_: pytest.fail('index read for wrong worktree branch'))
    with pytest.raises(PolicyError, match='revision changed'):
        run(repo)


def test_ignore_classification_change_is_refused(repo, monkeypatch):
    root, _, _, _ = repo
    original = r1._git
    changed = False

    def git_call(path, *args):
        nonlocal changed
        value = original(path, *args)
        if '--others' in args and '--ignored' in args and not changed:
            changed = True
            with (root / '.git/info/exclude').open('a') as stream:
                stream.write('\nnew.txt\n')
        return value

    monkeypatch.setattr(r1, '_git', git_call)
    with pytest.raises(PolicyError, match='ignore classification changed'):
        run(repo)
    assert (root / 'new.txt').read_text() == 'untracked synthetic WIP\n'


def test_staged_policy_change_is_refused_before_worktree_inventory(repo, monkeypatch):
    root, _, _, _ = repo
    with (root / 'wiki.config.yaml').open('a') as stream:
        stream.write('\n# synthetic staged policy change\n')
    git(root, 'add', 'wiki.config.yaml')
    monkeypatch.setattr(r1, '_physical', lambda *_: pytest.fail('worktree inventoried after policy index change'))
    with pytest.raises(PolicyError, match='normative index'):
        run(repo)


def test_unstaged_policy_body_is_not_treated_as_approved(repo):
    root, _, _, _ = repo
    with (root / 'wiki.config.yaml').open('a') as stream:
        stream.write('\n# synthetic unstaged policy change\n')
    result = run(repo)
    assert result['worktree_normative_bodies'] == 'not_inspected'
    assert result['normative_scope_completeness'] == 'external_not_verified'
    assert result['selection_admission'] == 'not_verified'


def test_explicit_selection_binds_all_requested_classes_without_io(repo, monkeypatch):
    _, _, middle, _ = repo
    result = run(repo)
    requested = [{'kind': 'message', 'revision': middle},
                 {'kind': 'git_blob', 'revision': middle, 'path': 'allowed.md'},
                 {'kind': 'index_blob', 'path': 'allowed.md', 'stage': 0},
                 {'kind': 'worktree', 'path': 'allowed.md'},
                 {'kind': 'worktree', 'path': 'new.txt'},
                 {'kind': 'worktree', 'path': 'cache/ignored.txt'}]
    monkeypatch.setattr(r1, '_git', lambda *_args: pytest.fail('selection attempted Git read'))
    selected = r1.select(result, requested)
    assert len(selected['inputs']) == len(requested)
    assert selected['inventory_sha256'] == result['inventory_sha256']
    assert len(selected['selection_sha256']) == 64
    assert selected['external_admission'] == 'not_verified'
    assert selected['gate_coverage'] == 'not_verified'
    with pytest.raises(PolicyError):
        r1.select(result, [{'kind': 'git_blob', 'revision': middle, 'path': 'restricted/denied.json'}])
    result['head'] = '0' * 40
    with pytest.raises(PolicyError, match='inventory unavailable'):
        r1.select(result, requested)


def test_bootstrap_and_target_git_calls_are_distinguished(repo, monkeypatch):
    import wiki_core.context_policy as context_policy
    import wiki_core.process_safety as process_safety

    root, base, middle, head = repo
    bootstrap_oids = {git(root, 'rev-parse', f'{base}:{path}') for path in ('AGENTS.md', 'index.md')}
    denied_oids = {git(root, 'rev-parse', f'{rev}:restricted/denied.json') for rev in (base, middle, head)}
    target_oids = {git(root, 'rev-parse', f'{rev}:allowed.md') for rev in (base, middle, head)}
    calls = []
    policy_paths = []
    original_start = process_safety.start_process_group
    original_popen = subprocess.Popen
    original_git_file = context_policy.git_file
    original_open = os.open
    forbidden_worktree = {str(root / name) for name in
                          ('allowed.md', 'restricted/denied.json', 'new.txt', 'cache/ignored.txt')}

    def record(argv):
        if isinstance(argv, (list, tuple)) and Path(str(argv[0])).name.lower() in ('git', 'git.exe'):
            calls.append(tuple(str(value) for value in argv))

    def start(argv, *args, **kwargs):
        record(argv)
        return original_start(argv, *args, **kwargs)

    def popen(argv, *args, **kwargs):
        record(argv)
        return original_popen(argv, *args, **kwargs)

    def git_file(path, ref, name):
        policy_paths.append((ref, name))
        return original_git_file(path, ref, name)

    def open_(path, flags, *args, **kwargs):
        if isinstance(path, (str, bytes, os.PathLike)) and os.fsdecode(path) in forbidden_worktree:
            pytest.fail('Python opened a non-bootstrap target body')
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(process_safety, 'start_process_group', start)
    monkeypatch.setattr(subprocess, 'Popen', popen)
    monkeypatch.setattr(context_policy, 'git_file', git_file)
    monkeypatch.setattr(os, 'open', open_)
    result = run(repo)
    assert calls and policy_paths and all(ref == base and name == 'wiki.config.yaml' for ref, name in policy_paths)
    for cmd in calls:
        assert not any(value in cmd for value in ('grep', 'status', 'diff'))
        if 'show' in cmd:
            assert cmd[cmd.index('show') + 1].endswith(':wiki.config.yaml')
        if 'cat-file' in cmd:
            pos = cmd.index('cat-file')
            value = cmd[pos + 2]
            assert value not in denied_oids | target_oids
            assert value in bootstrap_oids or value.endswith(':wiki.config.yaml')
    assert result['bootstrap_reads']['ignore_rules'] == 'read_may_overlap_target_paths'
    assert result['global_audit'] == 'not_performed'


def scan(repo, requested, inv, selection, admit):
    root, base, _, head = repo
    return r1.scan_selected(root, CoordinationBinding(('.',), 'refs/remotes/origin/main'),
                            context_id='.', approved_revision=base, base=base, head=head,
                            branch='wiki/synthetic', requested=requested,
                            inventory_sha256=inv['inventory_sha256'],
                            selection_sha256=selection['selection_sha256'],
                            normative_paths=['wiki.config.yaml'], admit=admit)


def test_selected_message_history_index_and_wip_scan_after_host_admission(repo, monkeypatch):
    root, _, middle, _ = repo
    inv = run(repo)
    requested = [{'kind': 'message', 'revision': middle},
                 {'kind': 'git_blob', 'revision': middle, 'path': 'allowed.md'},
                 {'kind': 'index_blob', 'path': 'allowed.md', 'stage': 0},
                 {'kind': 'worktree', 'path': 'allowed.md'},
                 {'kind': 'worktree', 'path': 'new.txt'},
                 {'kind': 'worktree', 'path': 'cache/ignored.txt'}]
    selection = r1.select(inv, requested)
    target_oids = {row['oid'] for row in selection['inputs'] if 'oid' in row}
    admitted = []
    original_git = r1._git
    original_worktree = r1._worktree_bytes

    def admitted_git(path, *args):
        if 'cat-file' in args and args[-1] in target_oids | {middle}:
            assert admitted, 'target object accessed before host admission'
        return original_git(path, *args)

    def admitted_file(path, row):
        assert admitted, 'worktree body accessed before host admission'
        return original_worktree(path, row)

    def admit(value):
        assert value['selection_sha256'] == selection['selection_sha256']
        admitted.append(True)
        return True

    monkeypatch.setattr(r1, '_git', admitted_git)
    monkeypatch.setattr(r1, '_worktree_bytes', admitted_file)
    output = scan(repo, requested, inv, selection, admit)
    assert output['state'] == 'completed'
    assert output['scanned_count'] == len(requested)
    assert output['global_audit'] == 'not_performed'
    assert output['gate_coverage'] == 'not_verified'
    assert output['host_admission'] == 'not_verified'
    assert output['historical_policy'] == 'external_not_verified'
    assert (root / 'allowed.md').read_text() == 'unstaged synthetic WIP\n'


def test_host_denial_and_selection_drift_refuse_before_target_reads(repo, monkeypatch):
    root, _, middle, _ = repo
    inv = run(repo)
    requested = [{'kind': 'git_blob', 'revision': middle, 'path': 'allowed.md'}]
    selection = r1.select(inv, requested)
    target = selection['inputs'][0]['oid']
    original = r1._git

    def guarded(path, *args):
        if 'cat-file' in args and args[-1] == target:
            pytest.fail('unadmitted target object was opened')
        return original(path, *args)

    monkeypatch.setattr(r1, '_git', guarded)
    with pytest.raises(PolicyError, match='admission'):
        scan(repo, requested, inv, selection, lambda _: False)
    (root / 'new.txt').write_text('synthetic changed after selection\n')
    with pytest.raises(PolicyError, match='inventory changed'):
        scan(repo, requested, inv, selection, lambda _: True)


def test_interrupted_selected_scan_reports_partial_coverage(repo, monkeypatch):
    _, _, middle, _ = repo
    inv = run(repo)
    requested = [{'kind': 'git_blob', 'revision': middle, 'path': 'allowed.md'},
                 {'kind': 'worktree', 'path': 'new.txt'}]
    selection = r1.select(inv, requested)
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: (_ for _ in ()).throw(OSError('synthetic stop')))
    output = scan(repo, requested, inv, selection, lambda _: True)
    assert output['state'] == 'partial'
    assert output['scanned_count'] == 1
    assert output['required_count'] == 2
    assert output['global_audit'] == 'not_performed'


def test_revoked_admission_stops_before_next_body(repo, monkeypatch):
    _, _, middle, _ = repo
    inv = run(repo)
    requested = [{'kind': 'git_blob', 'revision': middle, 'path': 'allowed.md'},
                 {'kind': 'worktree', 'path': 'new.txt'}]
    selection = r1.select(inv, requested)
    calls = []
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('body opened after revocation'))
    def admit(_selection):
        calls.append(True)
        return len(calls) < 5
    output = scan(repo, requested, inv, selection, admit)
    assert output['state'] == 'partial'
    assert output['scanned_count'] == 1
    assert output['required_count'] == 2


def test_callback_mutation_before_final_readback_reports_partial(repo):
    root, _, middle, _ = repo
    inv = run(repo)
    requested = [{'kind': 'git_blob', 'revision': middle, 'path': 'allowed.md'},
                 {'kind': 'worktree', 'path': 'new.txt'}]
    selection = r1.select(inv, requested)
    calls = []
    def admit(_selection):
        calls.append(True)
        if len(calls) == 6:
            (root / 'new.txt').write_text('synthetic callback mutation\n')
        return True
    output = scan(repo, requested, inv, selection, admit)
    assert len(calls) == 6
    assert output['state'] == 'partial'
    assert output['scanned_count'] == 2
    assert output['global_audit'] == 'not_performed'
