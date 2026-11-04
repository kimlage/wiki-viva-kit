from pathlib import Path
import subprocess
import sqlite3
import json
import sys
import pytest

from scripts.wiki_build_index import collect_page_chunks
from wiki_core.config import WikiConfig
from wiki_core.find import find
from wiki_core.graph import build_page_graph
from wiki_core.index import build_index, index_pages
from wiki_core.paths import WikiPaths
from wiki_core.repository_reader import RepositoryReader
from wiki_core.traversal import wiki_markdown_files
from wiki_core.okf import _all_markdown
from wiki_core.source_manifest import sha256_directory_listing
from wiki_core.web.source_operations import _inventory_raw_path
from wiki_core.insight.job import _gather_chunks
from scripts.wiki_llm_context_pass import _chunks_for_query
from wiki_core import consolidate


def page(path, identity, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'---\npage_id: {identity}\ncontext: system\n---\n{body}\n', encoding='utf-8')


def test_node_stays_visible_and_child_git_file_and_dir_are_pruned(tmp_path):
    (tmp_path / '.git').mkdir()  # the selected root remains traversable
    node = tmp_path / 'memories' / 'node'
    page(node / 'index.md', 'node', 'nodeword')
    page(node / 'one' / 'nested.md', 'one', 'outsideword')
    (node / 'one' / '.git').mkdir()
    page(node / 'two' / 'nested.md', 'two', 'worktreeword')
    (node / 'two' / '.git').write_text('gitdir: ../separate')
    page(tmp_path / 'outside.md', 'outside', 'symlinkword')
    (node / 'link.md').symlink_to(tmp_path / 'outside.md')
    (node / 'linkdir').symlink_to(node / 'one', target_is_directory=True)
    assert wiki_markdown_files(tmp_path) == [node / 'index.md', tmp_path / 'outside.md']
    assert wiki_markdown_files(node / 'one') == [node / 'one' / 'nested.md']
    assert wiki_markdown_files(node / 'one', wiki_root=tmp_path) == []
    assert _all_markdown(node / 'one', tmp_path) == []
    assert wiki_markdown_files(tmp_path / '..' / tmp_path.name, wiki_root=tmp_path) == []


@pytest.mark.parametrize('marker', ['file', 'directory'])
def test_find_refuses_derived_index_and_manifests_inside_nested_repo(tmp_path, monkeypatch, marker):
    cfg = WikiConfig()
    paths = WikiPaths(tmp_path, cfg)
    node = paths.memory_root / 'node' / 'index.md'
    page(node, 'node', 'nodeword')
    paths.source_manifests.mkdir(parents=True)
    manifest = paths.source_manifests / 'unselected.json'
    manifest.write_text('{"schema_version":"wiki_source_manifest.v1","source_id":"unselected"}')
    db = paths.indexes / 'wiki.sqlite'
    index_pages(db, collect_page_chunks(tmp_path, paths, cfg))
    marker_path = paths.derived_root / '.git'
    if marker == 'file':
        marker_path.write_text('gitdir: ../separate')
    else:
        marker_path.mkdir()
    assert wiki_markdown_files(paths.memory_root, wiki_root=tmp_path) == [node]
    original_read = Path.read_text
    original_open = Path.open
    def guarded_read(path, *args, **kwargs):
        if path == manifest:
            pytest.fail('nested repository manifest opened')
        return original_read(path, *args, **kwargs)
    def guarded_open(path, *args, **kwargs):
        if path == db:
            pytest.fail('nested repository SQLite opened')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded_read)
    monkeypatch.setattr(Path, 'open', guarded_open)
    monkeypatch.setattr(sqlite3, 'connect', lambda *args, **kwargs: pytest.fail('nested SQLite connected'))
    for source in (None, 'source-example'):
        result = find(tmp_path, cfg, 'nodeword', source_id=source)
        assert result['status'] == 'index_error'
        assert result['error'] == 'index_path_crosses_repository_boundary'
        assert not result['hits']
        assert any(issue['reason'] == 'metadata_path_crosses_repository_boundary'
                   for issue in result['scope']['catalog_issues'])


@pytest.mark.parametrize('boundary', ['git-file', 'git-directory', 'symlink'])
def test_legacy_wiki_query_consumers_refuse_index_across_boundary(tmp_path, monkeypatch, capsys, boundary):
    from wiki_core.index.page_collection import current_page_signature
    from wiki_core.index.sqlite import search

    cfg = WikiConfig()
    paths = WikiPaths(tmp_path, cfg)
    node = paths.memory_root / 'node' / 'index.md'
    page(node, 'node', 'nodeword')
    db = paths.indexes / 'wiki.sqlite'
    index_pages(db, collect_page_chunks(tmp_path, paths, cfg))
    signature = current_page_signature(paths)
    if boundary == 'symlink':
        outside = tmp_path / 'separate-indexes'
        paths.indexes.rename(outside)
        paths.indexes.symlink_to(outside, target_is_directory=True)
    elif boundary == 'git-file':
        (paths.derived_root / '.git').write_text('gitdir: ../separate')
    else:
        (paths.derived_root / '.git').mkdir()
    assert wiki_markdown_files(paths.memory_root, wiki_root=tmp_path) == [node]
    with monkeypatch.context() as m:
        m.setattr(sqlite3, 'connect', lambda *args, **kwargs: pytest.fail('nested SQLite connected'))
        with pytest.raises(ValueError, match='index_path_crosses_repository_boundary'):
            _chunks_for_query(paths, 'nodeword')
        with pytest.raises(ValueError, match='index_path_crosses_repository_boundary'):
            _gather_chunks(paths, 'nodeword', 10)
        from scripts import wiki_llm_context_pass
        m.setattr(wiki_llm_context_pass, 'load_config', lambda _: cfg)
        m.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--root', str(tmp_path),
                                '--query', 'nodeword', '--context', 'system'])
        assert wiki_llm_context_pass.main() == 2
        assert json.loads(capsys.readouterr().out)['error_code'] == 'query_index_unavailable'
        from wiki_core.insight import job
        m.setattr(job, '_gather_events', lambda *args: pytest.fail('nested derived events opened'))
        with pytest.raises(ValueError, match='index_path_crosses_repository_boundary'):
            job.run('nodeword', 'system', tmp_path, cfg, write=False)
        packet = consolidate.build_packet({'claims': ['nodeword']}, tmp_path, cfg, paths)
        assert packet['claims'][0]['related'] == []
        assert any('index_path_crosses_repository_boundary' in warning for warning in packet['warnings'])
    # Generic callers with no wiki root retain their prior contract.
    assert search(db, 'nodeword', page_signature=signature)


def test_rebuild_removes_previously_indexed_clone_but_explicit_git_read_works(tmp_path):
    cfg = WikiConfig()
    paths = WikiPaths(tmp_path, cfg)
    node = paths.memory_root / 'node'
    page(node / 'index.md', 'node', 'nodeword')
    repo = node / 'repo'
    page(repo / 'code.md', 'repo-doc', 'repoword')
    db = paths.indexes / 'wiki.sqlite'
    index_pages(db, collect_page_chunks(tmp_path, paths, cfg))
    assert find(tmp_path, cfg, 'repoword')['status'] == 'ok'
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    stale = find(tmp_path, cfg, 'repoword')
    assert stale['status'] == 'index_error'
    assert stale['error'] == 'wiki_page_index_stale_or_unverified_rebuild_required'
    with pytest.raises(ValueError, match='wiki_page_index_stale_or_unverified'):
        _gather_chunks(paths, 'repoword', 10)
    with pytest.raises(ValueError, match='wiki_page_index_stale_or_unverified'):
        _chunks_for_query(paths, 'repoword')
    subprocess.run(['git', '-C', str(repo), 'add', 'code.md'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c',
                    'user.email=fixture@example.test', 'commit', '-qm', 'fixture'], check=True)
    index_pages(db, collect_page_chunks(tmp_path, paths, cfg))
    assert find(tmp_path, cfg, 'repoword')['status'] == 'no_matches'
    found = find(tmp_path, cfg, 'nodeword')
    assert found['hits'][0]['provenance']['path'] == 'memories/node/index.md'
    assert set(build_page_graph(tmp_path, cfg).nodes) == {'memories/node/index.md'}
    read = RepositoryReader(repo, 'HEAD').read('code.md')
    assert 'repoword' in read['text']
    assert read['origin']['path'] == 'code.md'
    assert read['origin']['revision'] == subprocess.check_output(
        ['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()


def test_collision_with_valid_page_cannot_keep_clone_text_in_old_index(tmp_path):
    cfg = WikiConfig()
    paths = WikiPaths(tmp_path, cfg)
    node = paths.memory_root / 'node'
    repo = node / 'repo'
    page(repo / 'code.md', 'shared', 'repoword')
    db = paths.indexes / 'wiki.sqlite'
    index_pages(db, collect_page_chunks(tmp_path, paths, cfg))
    (repo / '.git').mkdir()
    page(node / 'index.md', 'shared', 'nodeword')
    assert find(tmp_path, cfg, 'repoword')['status'] == 'index_error'
    index_pages(db, collect_page_chunks(tmp_path, paths, cfg))
    assert find(tmp_path, cfg, 'repoword')['status'] == 'no_matches'
    assert find(tmp_path, cfg, 'nodeword')['status'] == 'ok'


def test_legacy_and_orphan_page_rows_require_rebuild(tmp_path):
    cfg = WikiConfig()
    paths = WikiPaths(tmp_path, cfg)
    page(paths.memory_root / 'index.md', 'node', 'nodeword')
    db = paths.indexes / 'wiki.sqlite'
    index_pages(db, collect_page_chunks(tmp_path, paths, cfg))
    with sqlite3.connect(db) as conn:
        conn.execute('DROP TABLE wiki_page_index_state')
        conn.execute("DELETE FROM chunks WHERE source_id='page:node'")
    assert find(tmp_path, cfg, 'nodeword')['status'] == 'index_error'
    index_pages(db, collect_page_chunks(tmp_path, paths, cfg))
    result = find(tmp_path, cfg, 'nodeword')
    assert result['status'] == 'ok'
    assert len(result['hits']) == 1


@pytest.mark.parametrize('corruption', ['delete_all', 'delete_one', 'missing_fts',
                                       'missing_chunks', 'mutate_text', 'mutate_metadata', 'duplicate_fts'])
def test_page_rows_and_fts_must_match_the_current_wiki(tmp_path, corruption):
    cfg = WikiConfig()
    paths = WikiPaths(tmp_path, cfg)
    page(paths.memory_root / 'one.md', 'one', 'tokenone')
    page(paths.memory_root / 'two.md', 'two', 'tokentwo')
    db = paths.indexes / 'wiki.sqlite'
    index_pages(db, collect_page_chunks(tmp_path, paths, cfg))
    with sqlite3.connect(db) as conn:
        if corruption == 'delete_all':
            conn.execute("DELETE FROM chunks WHERE source_id LIKE 'page:%'")
            conn.execute("DELETE FROM chunk_fts WHERE source_id LIKE 'page:%'")
        elif corruption == 'delete_one':
            conn.execute("DELETE FROM chunks WHERE source_id='page:one'")
            conn.execute("DELETE FROM chunk_fts WHERE source_id='page:one'")
        elif corruption == 'missing_fts':
            conn.execute("DELETE FROM chunk_fts WHERE source_id='page:one'")
        elif corruption == 'missing_chunks':
            conn.execute("DELETE FROM chunks WHERE source_id='page:one'")
        elif corruption == 'mutate_text':
            conn.execute("UPDATE chunks SET text='altered' WHERE source_id='page:one'")
            conn.execute("UPDATE chunk_fts SET text='altered' WHERE source_id='page:one'")
        elif corruption == 'mutate_metadata':
            conn.execute("UPDATE chunks SET hash_sha256='altered' WHERE source_id='page:one'")
        else:
            conn.execute("INSERT INTO chunk_fts SELECT chunk_id, source_id, text FROM chunk_fts WHERE source_id='page:one'")
    assert find(tmp_path, cfg, 'tokenone')['status'] == 'index_error'
    with pytest.raises(ValueError, match='wiki_page_index_stale_or_unverified'):
        _chunks_for_query(paths, 'tokenone')
    index_pages(db, collect_page_chunks(tmp_path, paths, cfg))
    assert find(tmp_path, cfg, 'tokenone')['status'] == 'ok'


def test_source_only_index_and_new_wiki_pages_require_explicit_scope_or_rebuild(tmp_path):
    cfg = WikiConfig()
    paths = WikiPaths(tmp_path, cfg)
    paths.chunks.mkdir(parents=True)
    (paths.chunks / 'source.json').write_text(json.dumps({
        'source_id': 'source-example', 'chunks': [dict(chunk_id='source-chunk', ordinal=0,
        hash_sha256='a' * 64, token_estimate=1, text='sourceword')]}))
    db = paths.indexes / 'wiki.sqlite'
    build_index(paths.chunks, db)
    page(paths.memory_root / 'index.md', 'node', 'nodeword')
    assert find(tmp_path, cfg, 'nodeword')['status'] == 'index_error'
    source = find(tmp_path, cfg, 'sourceword', source_id='source-example')
    assert source['status'] == 'ok'
    assert source['coverage']['page_index'] == 'not_checked_source_only'
    with pytest.raises(ValueError, match='wiki_page_index_stale_or_unverified'):
        _gather_chunks(paths, 'sourceword', 10)
    index_pages(db, [])  # stale empty page index must not mask a newly created page
    assert find(tmp_path, cfg, 'nodeword')['status'] == 'index_error'
    index_pages(db, collect_page_chunks(tmp_path, paths, cfg))
    assert find(tmp_path, cfg, 'nodeword')['status'] == 'ok'


def test_consolidation_reuses_one_signature_and_discards_results_if_wiki_changes(tmp_path, monkeypatch):
    cfg = WikiConfig()
    paths = WikiPaths(tmp_path, cfg)
    page_path = paths.memory_root / 'index.md'
    page(page_path, 'node', 'nodeword')
    index_pages(paths.indexes / 'wiki.sqlite', collect_page_chunks(tmp_path, paths, cfg))
    original = consolidate.current_page_signature
    calls = []
    def measure(paths_arg):
        calls.append(1)
        return original(paths_arg)
    monkeypatch.setattr(consolidate, 'current_page_signature', measure)
    packet = consolidate.build_packet({'claims': ['nodeword', 'nodeword']}, tmp_path, cfg, paths)
    assert len(calls) == 2
    assert all(row['related'] for row in packet['claims'])
    calls.clear()
    def changed(paths_arg):
        calls.append(1)
        if len(calls) == 2:
            page(page_path, 'node', 'changed')
        return original(paths_arg)
    monkeypatch.setattr(consolidate, 'current_page_signature', changed)
    packet = consolidate.build_packet({'claims': ['nodeword', 'nodeword']}, tmp_path, cfg, paths)
    assert len(calls) == 2
    assert not any(row['related'] for row in packet['claims'])
    assert any('changed during packet' in warning for warning in packet['warnings'])


def test_consolidation_missing_index_does_not_compute_signature(tmp_path, monkeypatch):
    cfg = WikiConfig()
    paths = WikiPaths(tmp_path, cfg)
    page(paths.memory_root / 'index.md', 'node', 'nodeword')
    monkeypatch.setattr(consolidate, 'current_page_signature',
                        lambda *_: pytest.fail('missing index must not scan wiki pages for signature'))
    packet = consolidate.build_packet({'claims':['nodeword']}, tmp_path, cfg, paths)
    assert packet['claims'][0]['related'] == []
    paths.derived_root.mkdir(parents=True)
    (paths.derived_root / '.git').mkdir()
    packet = consolidate.build_packet({'claims':['nodeword']}, tmp_path, cfg, paths)
    assert any('index_path_crosses_repository_boundary' in warning for warning in packet['warnings'])


def test_selected_source_collection_reports_nested_repo_and_explicit_root_works(tmp_path):
    selected = tmp_path / 'raw'
    page(selected / 'doc.md', 'doc', 'ordinary')
    child = selected / 'repo'
    page(child / 'item.md', 'child', 'content')
    (child / '.git').mkdir()
    (child / '.git' / 'internal').write_text('metadata')
    with pytest.raises(ValueError, match='source_directory_nested_repository'):
        sha256_directory_listing(selected)
    with pytest.raises(ValueError, match='source_directory_nested_repository'):
        _inventory_raw_path(tmp_path, selected)
    _, count = sha256_directory_listing(child)
    raw, _ = _inventory_raw_path(tmp_path, child)
    assert count == 1
    assert [entry['path'] for entry in raw['entries']] == ['item.md']
