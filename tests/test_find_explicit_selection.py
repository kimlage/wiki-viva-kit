"""Explicit local searches must not open unselected or nested-repo content."""
from pathlib import Path

import pytest

from wiki_core.find import find


def put(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def test_selected_node_excludes_clone_symlink_and_other_context(tmp_path, monkeypatch):
    import wiki_core.find as module
    node = put(tmp_path, 'node/index.md', 'Useful synthetic source in the node.')
    outside = put(tmp_path, 'other/private.md', 'Useful other context.')
    clone = put(tmp_path, 'node/clone/readme.md', 'Useful independent repository.')
    (tmp_path / 'node/clone/.git').mkdir()
    (tmp_path / 'node/linked.md').symlink_to(outside)
    original_open = Path.open
    def guarded(path, *args, **kwargs):
        if path in (clone, outside, tmp_path / 'node/linked.md'):
            pytest.fail('unselected content was opened')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    monkeypatch.setattr(module, '_local_catalog', lambda *_: pytest.fail('global catalog opened'))
    monkeypatch.setattr(module, 'search_detailed', lambda *_a, **_k: pytest.fail('global index opened'))
    result = find(tmp_path, None, 'useful source', selections=['node'])
    assert result['status'] == 'ok'
    assert [hit['path'] for hit in result['hits']] == [node.relative_to(tmp_path).as_posix()]
    assert result['coverage']['context_scope'] == 'explicit_selection_partial'
    assert result['coverage']['index'] == 'not_used'
    assert result['hits'][0]['origin'] == 'working_tree'
    assert len(result['hits'][0]['content_sha256']) == 64


def test_every_selected_path_is_validated_before_any_body(tmp_path, monkeypatch):
    first = put(tmp_path, 'node/index.md', 'allowed')
    put(tmp_path, 'node/clone/readme.md', 'forbidden')
    (tmp_path / 'node/clone/.git').mkdir()
    original_open = Path.open
    def guarded(path, *args, **kwargs):
        if path == first:
            pytest.fail('body opened before validating all selected paths')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    with pytest.raises(ValueError):
        find(tmp_path, None, 'allowed', selections=['node/index.md', 'node/clone/readme.md'])
    with pytest.raises(ValueError):
        find(tmp_path, None, 'allowed', selections=['node/index.md', '../outside.md'])


def test_rejects_explicit_symlink_and_oversized_file_before_open(tmp_path, monkeypatch):
    put(tmp_path, 'node/index.md', 'small')
    link = tmp_path / 'node/link.md'
    link.symlink_to(tmp_path / 'node/index.md')
    big = put(tmp_path, 'node/big.txt', 'x' * 1_000_001)
    original_open = Path.open
    def guarded(path, *args, **kwargs):
        if path in (link, big):
            pytest.fail('invalid selected body was opened')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    for name in ('node/link.md', 'node/big.txt'):
        with pytest.raises(ValueError):
            find(tmp_path, None, 'small', selections=[name])


def test_explicit_text_file_and_no_index_result(tmp_path):
    put(tmp_path, 'node/source.txt', 'First synthetic line.\nA needle here.\n')
    result = find(tmp_path, None, 'needle', selections=['node/source.txt'])
    assert result['hits'][0]['path'] == 'node/source.txt'
    empty = find(tmp_path, None, 'not-present', selections=['node/source.txt'])
    assert empty['status'] == 'no_matches' and empty['coverage']['context_scope'] == 'explicit_selection_partial'
    with pytest.raises(ValueError):
        find(tmp_path, None, 'needle', context='other', selections=['node/source.txt'])


def test_cli_uses_explicit_path_and_refuses_incompatible_filters(tmp_path, monkeypatch, capsys):
    import importlib.util
    import json
    path = Path(__file__).resolve().parents[1] / 'scripts/wiki_find.py'
    spec = importlib.util.spec_from_file_location('explicit_wiki_find_cli', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    put(tmp_path, 'node/index.md', 'A synthetic needle.')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'load_config', lambda _root: None)
    assert module.main(['needle', '--path', 'node']) == 0
    assert json.loads(capsys.readouterr().out)['hits'][0]['path'] == 'node/index.md'
    with pytest.raises(SystemExit):
        module.main(['needle', '--path', 'node', '--context', 'another'])
    assert module.main(['needle', '--path', '../outside']) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'selection_unavailable'


def test_traversal_limit_stops_before_opening_selected_body(tmp_path, monkeypatch):
    from wiki_core.traversal import wiki_files
    put(tmp_path, 'node/a.md', 'a')
    put(tmp_path, 'node/b.md', 'b')
    with pytest.raises(ValueError, match='entry limit'):
        wiki_files(tmp_path / 'node', wiki_root=tmp_path, max_entries=1)


def test_selected_search_refuses_secret_without_returning_it(tmp_path):
    # Synthetic public detector fixture, never an actual credential.
    secret = 'AKIA' + 'IOSFODNN7EXAMPLE'
    put(tmp_path, 'node/index.md', 'needle ' + secret)
    with pytest.raises(ValueError, match='content unavailable') as error:
        find(tmp_path, None, 'needle', selections=['node'])
    assert secret not in str(error.value)


def test_hit_limit_does_not_open_remaining_files_and_reports_gap(tmp_path, monkeypatch):
    put(tmp_path, 'node/a.md', 'synthetic needle')
    later = put(tmp_path, 'node/b.md', 'synthetic needle')
    original_open = Path.open
    def guarded(path, *args, **kwargs):
        if path == later:
            pytest.fail('unneeded body was opened after result limit')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    result = find(tmp_path, None, 'needle', selections=['node'], limit=1)
    assert result['coverage']['files_selected'] == 2
    assert result['coverage']['files_read'] == 1
    assert result['coverage']['files_not_read'] == 1


def test_query_and_paths_with_secrets_fail_before_open_and_without_echo(tmp_path, monkeypatch):
    secret = 'AKIA' + 'IOSFODNN7EXAMPLE'
    target = put(tmp_path, 'node/' + secret + '.md', 'needle')
    original_open = Path.open
    def guarded(path, *args, **kwargs):
        if path == target:
            pytest.fail('secret-bearing selector was opened')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    for query, selected in [('needle', ['node']), (secret, ['node']), ('needle', ['node/' + secret + '.md'])]:
        with pytest.raises(ValueError) as error:
            find(tmp_path, None, query, selections=selected)
        assert secret not in str(error.value)


def test_io_error_does_not_disclose_path(tmp_path, monkeypatch):
    target = put(tmp_path, 'node/private-selector.md', 'needle')
    original_open = Path.open
    def denied(path, *args, **kwargs):
        if path == target:
            raise PermissionError('private-selector.md')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', denied)
    with pytest.raises(ValueError) as error:
        find(tmp_path, None, 'needle', selections=['node/private-selector.md'])
    assert 'private-selector' not in str(error.value)
