"""Literal folder search never widens the selected source or owner."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from tests.test_folder_policy_v2 import project, put, git, commit
from wiki_core.folder_coordination_v2 import FolderHostBinding
from wiki_core.folder_search_v2 import search_folder, FolderSearchError
from wiki_core.repository_reader import RepositoryReader
from wiki_core.source_manifest import source_origin


def test_scope_excludes_other_owners_denials_and_instructions_before_read(project, monkeypatch):
    controls = yaml.safe_load((project/'wiki-context-controls.yaml').read_text())
    controls['controls']['a']['policy']['deny'] = {'read':['a/denied']}
    put(project, 'wiki-context-controls.yaml', yaml.safe_dump(controls))
    put(project, 'a/document.md', '# Wiki\nneedle here\nother\nNeedle again\n')
    put(project, 'a/denied/secret.md', 'needle in denied folder\n')
    put(project, 'a/aux/b/other.md', 'needle in child folder\n')
    commit(project); approved = git(project, 'rev-parse', 'HEAD')
    original = RepositoryReader.read
    def guarded(reader, path, *args, **kwargs):
        if path in ('a/denied/secret.md', 'a/aux/b/other.md', 'a/aux/AGENTS.md'):
            pytest.fail('unselected or unauthorized content opened')
        return original(reader, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    out = search_folder(project, FolderHostBinding(project, ('a',)), approved_revision=approved,
        folder='a', index_path='a/index.md', scope='a', query='needle', max_hits=1)
    assert out['hits'][0]['path'] == 'a/document.md' and out['hits'][0]['line'] == 2
    assert out['truncated'] and out['coverage'] == 'authorized_tracked_markdown_in_selected_owner_only'
    assert out['freshness'] == 'not_assessed' and out['read_verification'] == 'not_performed'
    assert 'a/denied/secret.md' not in json.dumps(out)
    empty = search_folder(project, FolderHostBinding(project, ('a',)), approved_revision=approved,
        folder='a', index_path='a/index.md', scope='a', query='synthetic-phrase-not-present')
    assert empty['status'] == 'no_matches_in_selection' and not empty['hits']
    assert empty['index_path'] == 'a/index.md' and empty['selection'] == {'kind':'scope', 'scope':'a'}
    assert empty['policy_revision'] == approved
    with pytest.raises(FolderSearchError):
        search_folder(project, FolderHostBinding(project, ('a',)), approved_revision=approved,
            folder='a', index_path='a/index.md', scope='a/aux/b', query='needle')
    with pytest.raises(FolderSearchError, match='folder_search_budget_exceeded'):
        search_folder(project, FolderHostBinding(project, ('a',)), approved_revision=approved,
            folder='a', index_path='a/index.md', scope='a', query='needle', max_files=1)
    with pytest.raises(FolderSearchError):
        search_folder(project, FolderHostBinding(project, ('a',)), approved_revision=approved,
            folder='a', index_path='a/index.md', scope='a/not-present', query='needle')


def test_raw_search_rechecks_current_bytes_and_authority(project, monkeypatch):
    put(project, '.gitignore', 'a/raw/\n')
    source = '---\npage_id: source-raw\npage_type: source\nplatform: drive\nsource_locator: synthetic\n---\nSource\n'
    put(project, 'a/source.md', source); commit(project)
    approved = git(project, 'rev-parse', 'HEAD')
    put(project, 'a/raw/source.txt', 'local observation\nneedle in raw\n' + 'synthetic padding\n' * 100)
    ref = 'a/raw/source.txt'; path = project/ref
    capture = {'source_kind':'staged_raw', 'ref':ref, 'source_revision':None,
        'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'source_origin':source_origin(str(path), project),
        'canonical_ref':'a/source.md', 'canonical_revision':approved,
        'canonical_sha256':hashlib.sha256(source.encode()).hexdigest(),
        'association':'caller_selected_unverified', 'external_origin_verification':'not_verified',
        'external_freshness':'not_verified'}
    args = {'approved_revision':approved, 'folder':'a', 'index_path':'a/index.md',
            'raw_capture':capture, 'query':'needle'}
    out = search_folder(project, FolderHostBinding(project, ('a',)), **args)
    assert out['hits'][0]['path'] == ref and out['hits'][0]['line'] == 2
    assert out['coverage'] == 'explicit_selected_raw_utf8_file_only'
    assert out['freshness'] == 'not_assessed'
    empty = search_folder(project, FolderHostBinding(project, ('a',)), **{**args, 'query':'not-present'})
    assert not empty['hits'] and empty['selection'] == {
        'kind':'raw', 'path':ref, 'source_ref':'a/source.md', 'source_revision':approved,
        'source_sha256':capture['canonical_sha256'], 'sha256':capture['source_sha256']}
    assert empty['index_path'] == 'a/index.md' and empty['policy_revision'] == approved
    capture_file = project/'synthetic-capture.json'; capture_file.write_text(json.dumps(capture))
    script = Path(__file__).resolve().parents[1]/'scripts/wiki_context.py'
    cmd = [sys.executable, str(script), '--repo', str(project), '--approved-revision', approved,
           'search', 'a', '--raw-capture', str(capture_file), '--literal', 'needle']
    env = {**os.environ, 'WIKI_FOLDER_INGEST_HOST_ROOT':str(project), 'WIKI_FOLDER_INGEST_HOST_FOLDERS':'a'}
    called = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert called.returncode == 0 and json.loads(called.stdout)['hits'][0]['path'] == ref
    original = Path.open
    def budget_guard(selected, *open_args, **open_kwargs):
        if selected == path: pytest.fail('over-budget RAW opened')
        return original(selected, *open_args, **open_kwargs)
    with monkeypatch.context() as m:
        m.setattr(Path, 'open', budget_guard)
        with pytest.raises(FolderSearchError, match='folder_search_budget_exceeded'):
            search_folder(project, FolderHostBinding(project, ('a',)), **args, max_bytes=300)
    put(project, ref, 'changed after capture\n')
    with pytest.raises(FolderSearchError): search_folder(project, FolderHostBinding(project, ('a',)), **args)
    with pytest.raises(FolderSearchError): search_folder(project, FolderHostBinding(project, ('a/aux/b',)), **args)
    controls = yaml.safe_load((project/'wiki-context-controls.yaml').read_text())
    controls['controls']['a']['policy']['deny'] = {'read':['a/raw']}
    put(project, 'wiki-context-controls.yaml', yaml.safe_dump(controls)); commit(project)
    latest = git(project, 'rev-parse', 'HEAD')
    original = Path.open
    def deny_before_read(selected, *open_args, **open_kwargs):
        if selected == path: pytest.fail('revoked RAW opened')
        return original(selected, *open_args, **open_kwargs)
    monkeypatch.setattr(Path, 'open', deny_before_read)
    with pytest.raises(FolderSearchError):
        search_folder(project, FolderHostBinding(project, ('a',)), **{**args, 'approved_revision':latest})


def test_repository_search_requires_exact_host_binding_and_blob_limit(project, monkeypatch, tmp_path):
    put(project, '.gitignore', 'a/clone/\n')
    put(project, 'a/repo.md', '---\npage_id: source-repo\npage_type: source\nplatform: repo\n'
        'source_locator: example.test/group/project\n---\nRepository\n')
    commit(project); approved = git(project, 'rev-parse', 'HEAD')
    clone = project/'a/clone'; clone.mkdir()
    git(clone, 'init', '-q'); git(clone, 'config', 'user.name', 'Synthetic'); git(clone, 'config', 'user.email', 'synthetic@example.invalid')
    git(clone, 'remote', 'add', 'origin', 'https://example.test/group/project.git')
    put(clone, 'guide.md', '# Synthetic\nNeedle in repository\n')
    put(clone, 'big.md', 'synthetic content\n' * 100)
    git(clone, 'add', '-A'); git(clone, 'commit', '-qm', 'source')
    rev = git(clone, 'rev-parse', 'HEAD'); identity = 'example.test/group/project'
    choice = {'source_ref':'a/repo.md', 'root':str(clone), 'identity':identity, 'revision':rev, 'path':'guide.md'}
    binding = FolderHostBinding(project, ('a',), (('a', clone, identity, 'guide.md'), ('a', clone, identity, 'big.md')))
    args = {'approved_revision':approved, 'folder':'a', 'index_path':'a/index.md', 'repository':choice, 'query':'needle'}
    out = search_folder(project, binding, **args)
    assert out['hits'][0]['line'] == 2 and out['hits'][0]['revision'] == rev
    assert out['coverage'] == 'explicit_selected_repository_git_blob_only'
    empty = search_folder(project, binding, **{**args, 'query':'not-present'})
    assert not empty['hits'] and empty['selection']['kind'] == 'repository'
    assert empty['selection']['source_ref'] == 'a/repo.md'
    assert empty['selection']['repository'] == identity and empty['selection']['revision'] == rev
    assert empty['selection']['path'] == 'guide.md' and empty['selection']['source_revision'] == approved
    assert empty['index_path'] == 'a/index.md' and empty['policy_revision'] == approved
    script = Path(__file__).resolve().parents[1]/'scripts/wiki_context.py'
    cmd = [sys.executable, str(script), '--repo', str(project), '--approved-revision', approved,
           'search', 'a', '--index', 'a/index.md', '--source-ref', 'a/repo.md',
           '--source-repository', str(clone), identity, rev, 'guide.md', '--literal', 'needle']
    env = {**os.environ, 'WIKI_FOLDER_INGEST_HOST_ROOT':str(project), 'WIKI_FOLDER_INGEST_HOST_FOLDERS':'a',
           'WIKI_FOLDER_INGEST_HOST_REPOSITORIES':json.dumps([['a',str(clone),identity,'guide.md']])}
    called = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert called.returncode == 0 and json.loads(called.stdout)['hits'][0]['revision'] == rev
    import wiki_core.repo_read
    alias = tmp_path / 'repo-alias'; alias.symlink_to(clone, target_is_directory=True)
    other = tmp_path / 'unbound'; other.mkdir()
    original_read = wiki_core.repo_read.read_independent_repo
    def retarget(root, *read_args, **read_kwargs):
        alias.unlink(); alias.symlink_to(other, target_is_directory=True)
        assert root == clone.resolve()
        return original_read(root, *read_args, **read_kwargs)
    with monkeypatch.context() as m:
        m.setattr(wiki_core.repo_read, 'read_independent_repo', retarget)
        via_alias = search_folder(project, binding, **{**args, 'repository':{**choice, 'root':str(alias)}})
        assert via_alias['hits'][0]['revision'] == rev
    original = RepositoryReader.read
    def budget_guard(reader, path, *read_args, **read_kwargs):
        if path == 'big.md': pytest.fail('over-budget repository blob opened')
        return original(reader, path, *read_args, **read_kwargs)
    with monkeypatch.context() as m:
        m.setattr(RepositoryReader, 'read', budget_guard)
        with pytest.raises(FolderSearchError, match='folder_search_budget_exceeded'):
            search_folder(project, binding, **{**args, 'repository':{**choice, 'path':'big.md'}}, max_bytes=300)
    def forbidden(*args, **kwargs): pytest.fail('unbound repository opened')
    monkeypatch.setattr(wiki_core.repo_read, 'read_independent_repo', forbidden)
    with pytest.raises(FolderSearchError):
        search_folder(project, FolderHostBinding(project, ('a',)), **args)
    with pytest.raises(FolderSearchError):
        search_folder(project, binding, **{**args, 'repository':{**choice, 'path':'other.md'}})
    with pytest.raises(FolderSearchError):
        search_folder(project, binding, **args, max_bytes=20)


def test_normal_cli_requires_host_binding_and_returns_bounded_hits(project):
    put(project, 'a/document.md', '# Synthetic\nneedle\n'); commit(project)
    approved = git(project, 'rev-parse', 'HEAD')
    script = Path(__file__).resolve().parents[1]/'scripts/wiki_context.py'
    cmd = [sys.executable, str(script), '--repo', str(project), '--approved-revision', approved,
           'search', 'a', '--index', 'a/index.md', '--scope', 'a', '--literal', 'needle']
    env = {**os.environ, 'WIKI_FOLDER_INGEST_HOST_ROOT':str(project), 'WIKI_FOLDER_INGEST_HOST_FOLDERS':'a'}
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['hits'][0]['path'] == 'a/document.md'
    env['WIKI_FOLDER_INGEST_HOST_FOLDERS'] = 'a/aux/b'
    assert subprocess.run(cmd, capture_output=True, text=True, env=env).returncode != 0


def test_root_scope_respects_owners_denials_and_unsupported_objects(project, monkeypatch):
    put(project, 'AGENTS.md', '# Project\n\n## Wiki v2: indexes\n\n- [Root index](README.md)\n')
    controls = yaml.safe_load((project/'wiki-context-controls.yaml').read_text())
    controls['controls']['.']['policy']['deny'] = {'read':['private']}
    put(project, 'wiki-context-controls.yaml', yaml.safe_dump(controls))
    put(project, 'docs/visible.md', '# Synthetic\nneedle\n')
    put(project, 'private/hidden.md', 'needle denied\n')
    put(project, 'a/other-owner.md', 'needle other owner\n')
    (project/'private/ignored-link.md').symlink_to('hidden.md')
    (project/'a/other-owner-link.md').symlink_to('other-owner.md')
    commit(project); approved = git(project, 'rev-parse', 'HEAD')
    original = RepositoryReader.read
    def guarded(reader, path, *args, **kwargs):
        if path.startswith(('private/', 'a/')):
            pytest.fail('denied or other-owner content opened')
        return original(reader, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    args = {'approved_revision':approved, 'folder':'.', 'index_path':'README.md',
            'scope':'.', 'query':'needle'}
    binding = FolderHostBinding(project, ('.',))
    out = search_folder(project, binding, **args)
    assert [hit['path'] for hit in out['hits']] == ['docs/visible.md']
    assert out['selection'] == {'kind':'scope', 'scope':'.'} and out['index_path'] == 'README.md'
    assert 'private/' not in json.dumps(out) and 'a/other-owner' not in json.dumps(out)
    empty = search_folder(project, binding, **{**args, 'query':'not-present'})
    assert empty['status'] == 'no_matches_in_selection' and not empty['hits']
    assert empty['selection'] == {'kind':'scope', 'scope':'.'}
    (project/'docs/unsupported.md').symlink_to('visible.md')
    commit(project); current = git(project, 'rev-parse', 'HEAD')
    with pytest.raises(FolderSearchError, match='folder_search_unsupported_content') as exc:
        search_folder(project, binding, **{**args, 'approved_revision':current})
    assert 'docs/unsupported.md' not in str(exc.value)


def test_root_scope_requires_rootwide_read_grant(project):
    put(project, 'AGENTS.md', '# Project\n\n## Wiki v2: indexes\n\n- [Root](README.md)\n')
    controls = yaml.safe_load((project/'wiki-context-controls.yaml').read_text())
    controls['controls']['.']['policy']['read'] = ['README.md']
    controls['controls']['a']['policy']['read'] = []
    controls['controls']['a/aux/b']['policy']['read'] = []
    put(project, 'wiki-context-controls.yaml', yaml.safe_dump(controls))
    commit(project); approved = git(project, 'rev-parse', 'HEAD')
    with pytest.raises(FolderSearchError):
        search_folder(project, FolderHostBinding(project, ('.',)), approved_revision=approved,
                      folder='.', index_path='README.md', scope='.', query='needle')
