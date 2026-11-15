import subprocess
import sys

import pytest

from wiki_core.action_queue import DERIVED_POINTER, read_queue
from wiki_core.action_transition import transition_action_page
from scripts import wiki_action_queue


def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def setup_repo(root):
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'config', 'user.email', 'test@example.org')
    git(root, 'config', 'user.name', 'Test')
    (root / '.gitignore').write_text('data/derived/\n', encoding='utf-8')
    action_dir = root / 'memories' / 'actions'
    action_dir.mkdir(parents=True)
    for key in ('a', 'b'):
        (action_dir / f'{key}.md').write_text(
            f'---\npage_type: action\npage_id: {key}\ntitle: {key}\n'
            'action_state: open\nnext_action: work\n---\n\n# Action\n', encoding='utf-8')
    (action_dir / 'pending.md').write_text('---\npage_type: index\n---\n\n' + DERIVED_POINTER + '\n', encoding='utf-8')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'base')


def test_parallel_action_edits_merge_without_queue_conflict(tmp_path):
    setup_repo(tmp_path)
    base = git(tmp_path, 'rev-parse', 'HEAD')
    git(tmp_path, 'switch', '-qc', 'one')
    transition_action_page(tmp_path, 'memories/actions/a.md', 'in_progress', reason='First')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'one')
    git(tmp_path, 'switch', '-qc', 'two', base)
    transition_action_page(tmp_path, 'memories/actions/b.md', 'in_progress', reason='Second')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'two')
    git(tmp_path, 'merge', '--no-edit', 'one')
    rows, errors = read_queue(tmp_path, base=base)
    assert errors == []
    assert [(x['page_id'], x['state']) for x in rows] == [('a', 'in_progress'), ('b', 'in_progress')]
    assert git(tmp_path, 'diff', '--name-only', base, 'HEAD').splitlines() == [
        'memories/actions/a.md', 'memories/actions/b.md']


def test_check_rejects_lifecycle_edit_without_receipt_and_invalid_state(tmp_path):
    setup_repo(tmp_path)
    base = git(tmp_path, 'rev-parse', 'HEAD')
    action = tmp_path / 'memories/actions/a.md'
    action.write_text(action.read_text().replace('next_action: work', 'next_action: altered'))
    _, errors = read_queue(tmp_path, base=base)
    assert any('missing_action_transition_receipt' in error for error in errors)
    action.write_text(action.read_text().replace('action_state: open', 'action_state: invalid'))
    _, errors = read_queue(tmp_path, base=base)
    assert any('invalid action_state' in error for error in errors)


def test_check_rejects_duplicate_deleted_actions_and_missing_base(tmp_path):
    setup_repo(tmp_path)
    base = git(tmp_path, 'rev-parse', 'HEAD')
    action = tmp_path / 'memories/actions/a.md'
    (action.parent / 'duplicate.md').write_text(action.read_text())
    assert any('duplicate page_id' in error for error in read_queue(tmp_path, base=base)[1])
    (action.parent / 'duplicate.md').unlink()
    action.unlink()
    assert any('action missing' in error for error in read_queue(tmp_path, base=base)[1])
    assert read_queue(tmp_path, base='nonexistent')[1][-1] == 'base action inventory unavailable'


def test_check_uses_common_base_when_main_advances(tmp_path, monkeypatch):
    setup_repo(tmp_path)
    git(tmp_path, 'switch', '-qc', 'candidate')
    transition_action_page(tmp_path, 'memories/actions/a.md', 'in_progress', reason='First')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'candidate')
    git(tmp_path, 'switch', '-q', 'main')
    path = tmp_path / 'memories/actions/new.md'
    path.write_text('---\npage_type: action\npage_id: new\naction_state: open\nnext_action: work\n---\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'independent action')
    git(tmp_path, 'switch', '-q', 'candidate')
    monkeypatch.setattr(wiki_action_queue, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['wiki_action_queue.py', '--check', '--base', 'main'])
    assert wiki_action_queue.main() == 0


@pytest.mark.parametrize('stale', [
    '| Ação | Estado |\n| --- | --- |\n| a | open |\n\n'
    '| Ação | Estado |\n| --- | --- |\n| a | done |',
    '- a: done',
    '| Identificador | Situação |\n| --- | --- |\n| a | done |',
    'A ação a está concluída.',
    '## Fila reconciliada\n\n| a | open |\n\n## Outra fila\n\n| a | done |',
])
def test_check_rejects_any_stale_content_beyond_pointer(tmp_path, monkeypatch, capsys, stale):
    setup_repo(tmp_path)
    queue = tmp_path / 'memories/actions/pending.md'
    queue.write_text('---\npage_type: index\n---\n\n' + DERIVED_POINTER + '\n\n' + stale + '\n')
    monkeypatch.setattr(wiki_action_queue, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['wiki_action_queue.py', '--check', '--base', 'main'])
    assert wiki_action_queue.main() == 1
    assert 'only the exact derived pointer' in capsys.readouterr().err


@pytest.mark.parametrize('metadata', ['collection:\n  members: [a]', 'actions: [a]', 'extra: stale'])
def test_pointer_rejects_materialized_or_unknown_metadata(tmp_path, metadata):
    setup_repo(tmp_path)
    queue = tmp_path / 'memories/actions/pending.md'
    queue.write_text('---\npage_type: index\n' + metadata + '\n---\n\n' + DERIVED_POINTER + '\n')
    assert any('unsupported or materialized metadata' in x for x in read_queue(tmp_path, base='main')[1])


def test_legacy_materialization_must_be_migrated_even_when_current(tmp_path):
    setup_repo(tmp_path)
    queue = tmp_path / 'memories/actions/pending.md'
    queue.write_text('---\npage_type: index\n---\n\n# Queue\n\n'
                     '## Fila reconciliada\n\n| a | open |\n| b | open |\n')
    assert any('only the exact derived pointer' in x for x in read_queue(tmp_path, base='main')[1])


def test_pointer_refuses_symlink_even_if_target_has_pointer(tmp_path):
    setup_repo(tmp_path)
    queue = tmp_path / 'memories/actions/pending.md'
    target = tmp_path / 'target.md'
    target.write_text(queue.read_text())
    queue.unlink()
    queue.symlink_to(target)
    assert 'pending queue path contains a symlink' in read_queue(tmp_path, base='main')[1]
