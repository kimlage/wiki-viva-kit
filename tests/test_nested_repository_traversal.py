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


@pytest.mark.parametrize('boundary', ['git_file', 'git_directory', 'directory_symlink', 'database_symlink'])
def test_derived_consumers_refuse_repository_and_symlink_boundaries(tmp_path, monkeypatch, capsys, boundary):
    import sys
    from scripts import wiki_build_index, wiki_gc, wiki_consolidate
    from wiki_core.ingest import pipeline
    cfg = WikiConfig(repo_id='synthetic-boundary')
    paths = WikiPaths(tmp_path, cfg)
    node = paths.memory_root / 'node' / 'index.md'
    page(node, 'node', 'nodeword')
    source = tmp_path / 'source.md'
    source.write_text('Synthetic source\n')
    if boundary == 'directory_symlink':
        foreign = tmp_path / 'foreign'; foreign.mkdir()
        paths.derived_root.parent.mkdir(parents=True, exist_ok=True)
        paths.derived_root.symlink_to(foreign, target_is_directory=True)
    else:
        paths.derived_root.mkdir(parents=True)
        if boundary == 'git_file':
            (paths.derived_root / '.git').write_text('gitdir: ../separate')
        elif boundary == 'git_directory':
            (paths.derived_root / '.git').mkdir()
    paths.indexes.mkdir(parents=True)
    db = paths.indexes / 'wiki.sqlite'
    if boundary == 'database_symlink':
        foreign_db = tmp_path / 'foreign.sqlite'
        foreign_db.write_bytes(b'synthetic protected index')
        db.symlink_to(foreign_db)
        sentinel = foreign_db
    else:
        db.write_bytes(b'synthetic protected index')
        sentinel = db
    before = sentinel.read_bytes()
    monkeypatch.setattr(wiki_build_index, 'ROOT', tmp_path)
    monkeypatch.setattr(wiki_build_index, 'load_config', lambda _: cfg)
    monkeypatch.setattr(wiki_gc, 'ROOT', tmp_path)
    monkeypatch.setattr(wiki_gc, 'load_config', lambda _: cfg)
    monkeypatch.setattr(wiki_consolidate, 'ROOT', tmp_path)
    monkeypatch.setattr(wiki_consolidate, 'load_config', lambda _: cfg)
    monkeypatch.setattr(WikiPaths, 'ensure', lambda _: pytest.fail('derived paths created before guard'))
    monkeypatch.setattr(pipeline, 'build_manifest', lambda *a, **k: pytest.fail('source read before derived guard'))
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **k: pytest.fail('SQLite opened before guard'))
    for args in (['--check'], ['--rebuild']):
        monkeypatch.setattr(sys, 'argv', ['wiki_build_index.py', *args])
        assert wiki_build_index.main() == 2
        assert 'derived_path_crosses_repository_boundary' in capsys.readouterr().err
    result = pipeline.run(str(source), 'synthetic', tmp_path, cfg)
    assert result.blocked and not result.written
    assert wiki_gc.main([]) == (0 if boundary == 'database_symlink' else 2)
    assert wiki_gc.main(['--apply']) == 2
    if boundary != 'database_symlink':
        for args in (['--check'], ['--source', 'synthetic', '--packet']):
            monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', *args])
            assert wiki_consolidate.main() == 2
    assert sentinel.read_bytes() == before
    assert node.read_text().endswith('nodeword\n')


def test_derived_file_symlinks_are_rejected_before_use(tmp_path, monkeypatch, capsys):
    import sys
    from scripts import wiki_build_index, wiki_gc
    from wiki_core.ingest import pipeline
    from wiki_core.llm.context_pass import read_matching_result
    from wiki_core.source_manifest import build_manifest
    cfg = WikiConfig(repo_id='synthetic-boundary')
    paths = WikiPaths(tmp_path, cfg)
    paths.ensure()
    source = tmp_path / 'source.md'; source.write_text('Synthetic source\n')
    target = tmp_path / 'sentinel.json'; target.write_text('{"sentinel":true}')
    source_id = build_manifest(str(source), 'synthetic', root=tmp_path)['source_id']
    (paths.source_manifests / f'{source_id}.json').symlink_to(target)
    result = pipeline.run(str(source), 'synthetic', tmp_path, cfg)
    assert result.blocked and not result.written
    orphan = paths.chunks / 'orphan.json'; orphan.symlink_to(target)
    monkeypatch.setattr(wiki_build_index, 'ROOT', tmp_path)
    monkeypatch.setattr(wiki_build_index, 'load_config', lambda _: cfg)
    monkeypatch.setattr(sys, 'argv', ['wiki_build_index.py', '--rebuild'])
    monkeypatch.setattr(WikiPaths, 'ensure', lambda _: pytest.fail('ensure called before symlink check'))
    assert wiki_build_index.main() == 2
    capsys.readouterr()
    monkeypatch.setattr(wiki_gc, 'ROOT', tmp_path)
    monkeypatch.setattr(wiki_gc, 'load_config', lambda _: cfg)
    assert wiki_gc.main(['--apply']) == 2
    key = 'a' * 64
    (paths.llm_cache / f'{key}.json').symlink_to(target)
    with pytest.raises(ValueError, match='derived_path_crosses_repository_boundary'):
        read_matching_result(paths.llm_cache, {}, {'cache_key':key}, root=tmp_path)
    assert orphan.is_symlink() and target.read_text() == '{"sentinel":true}'


@pytest.mark.parametrize('selection', ['request', 'cache', 'packet'])
def test_legacy_consolidation_rejects_selected_symlink(tmp_path, monkeypatch, selection):
    import sys
    from scripts import wiki_consolidate
    cfg = WikiConfig(repo_id='synthetic-boundary'); paths = WikiPaths(tmp_path, cfg)
    paths.ensure()
    target = tmp_path / 'sentinel.json'; target.write_text('{"sentinel":true}')
    request_file = paths.extraction_events / 'synthetic-llm-context-request.json'
    key = 'a' * 64
    if selection == 'request':
        request_file.symlink_to(target)
    elif selection == 'cache':
        request_file.write_text(json.dumps({'source_id':'synthetic', 'chunks':[{'cache_key':key}]}))
        (paths.llm_cache / f'{key}.json').symlink_to(target)
    else:
        (paths.extraction_events / 'synthetic-integration-packet.json').symlink_to(target)
    monkeypatch.setattr(wiki_consolidate, 'ROOT', tmp_path)
    monkeypatch.setattr(wiki_consolidate, 'load_config', lambda _: cfg)
    if selection != 'packet':
        monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', '--check'])
        assert wiki_consolidate.main() == 2
    monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', '--source', 'synthetic', '--packet'])
    assert wiki_consolidate.main() == 2
    assert target.read_text() == '{"sentinel":true}'


def test_boundary_guard_accepts_relative_selected_root(tmp_path, monkeypatch):
    from wiki_core.traversal import require_wiki_boundaries
    (tmp_path / 'nested').mkdir()
    monkeypatch.chdir(tmp_path / 'nested')
    root = Path('..')
    require_wiki_boundaries(root, directories=(root / 'data/derived',))
    (tmp_path / 'data/derived').mkdir(parents=True)
    (tmp_path / 'data/derived/.git').mkdir()
    with pytest.raises(ValueError, match='derived_path_crosses_repository_boundary'):
        require_wiki_boundaries(root, directories=(root / 'data/derived',))


def test_search_and_page_signature_accept_relative_wiki_root(tmp_path, monkeypatch):
    from wiki_core.index.page_collection import current_page_signature
    from wiki_core.index.sqlite import search, search_detailed
    cfg = WikiConfig()
    paths = WikiPaths(tmp_path, cfg)
    page(paths.memory_root / 'node/index.md', 'node', 'relativeword')
    db = paths.indexes / 'wiki.sqlite'
    index_pages(db, collect_page_chunks(tmp_path, paths, cfg))
    (tmp_path / 'nested').mkdir()
    monkeypatch.chdir(tmp_path / 'nested')
    root = Path('..')
    relative_paths = WikiPaths(root, cfg)
    signature = current_page_signature(relative_paths)
    relative_db = relative_paths.indexes / 'wiki.sqlite'
    assert search(relative_db, 'relativeword', page_signature=signature, wiki_root=root)
    assert search_detailed(relative_db, 'relativeword', page_signature=signature, wiki_root=root)['hits']
    assert find(root, cfg, 'relativeword')['hits'][0]['provenance']['path'] == 'memories/node/index.md'
    assert not wiki_markdown_files(root / 'memories/../memories', wiki_root=root)


def test_stream_cursor_boundary_blocks_before_ingestion(tmp_path, monkeypatch):
    from wiki_core.ingest import pipeline
    cfg = WikiConfig(repo_id='synthetic-boundary')
    paths = WikiPaths(tmp_path, cfg)
    paths.source_state.mkdir(parents=True)
    (paths.source_state / '.git').mkdir()
    source = tmp_path / 'source.md'; source.write_text('Synthetic source\n')
    monkeypatch.setattr(pipeline, 'build_manifest', lambda *a, **k: pytest.fail('source opened before cursor boundary'))
    result = pipeline.run(str(source), 'synthetic', tmp_path, cfg, stream_id='synthetic')
    assert result.blocked and not result.written and not result.stream_cursor_written
    assert not paths.source_manifests.exists()


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
