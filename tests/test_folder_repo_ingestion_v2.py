"""Independent local Git context is bound before any synthetic result."""
import copy
import json
import sys

from tests.test_folder_policy_v2 import project, put, git, commit
from tests.test_folder_ingestion_v2 import setup, _synthetic_result, _recording_cli
from wiki_core.config import load_config
from wiki_core.folder_coordination_v2 import FolderHostBinding
from wiki_core.folder_ingestion_v2 import FolderIngestionSelection
from wiki_core.ingest import run
from wiki_core.llm.context_pass import result_matches_request


def repository_fixture(project):
    setup(project)
    put(project, '.gitignore', 'data/derived/\na/clone/\n')
    put(project, 'a/repo-source.md', '---\npage_id: repo-source\npage_type: source\nplatform: repo\nsource_locator: example.test/group/nested\n---\nSynthetic repository node.\n')
    commit(project)
    sha = git(project, 'rev-parse', 'HEAD')
    clone = project / 'a/clone'; clone.mkdir()
    git(clone, 'init', '-q'); git(clone, 'config', 'user.name', 'Synthetic')
    git(clone, 'config', 'user.email', 'synthetic@example.invalid')
    git(clone, 'remote', 'add', 'origin', 'https://example.test/group/nested.git')
    put(clone, 'guide.md', '# Synthetic guide\n\nAuthorized repository context.\n')
    git(clone, 'add', '-A'); git(clone, 'commit', '-qm', 'synthetic')
    revision = git(clone, 'rev-parse', 'HEAD')
    identity = 'example.test/group/nested'
    binding = FolderHostBinding(project, ('a',), (('a', clone, identity, 'guide.md'),))
    chosen = (str(clone), identity, revision, 'guide.md')
    selection = FolderIngestionSelection(binding, 'a', 'a/index.md', 'a/result.md', None, chosen)
    return sha, selection, chosen


def test_selected_repository_is_in_request_and_bound_to_result(project, monkeypatch, tmp_path, capsys):
    sha, selection, chosen = repository_fixture(project)
    result = run(str(project / 'a/repo-source.md'), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=selection)
    assert not result.blocked and result.written
    request = json.loads((project / result.request_path).read_text())
    receipt = request['source_authorization']['independent_repo_read']
    assert 'text' not in receipt and receipt['path'] == 'guide.md' and receipt['revision'] == chosen[2]
    assert request['independent_repo_content'] == '# Synthetic guide\n\nAuthorized repository context.\n'
    reported = _synthetic_result(request)
    assert result_matches_request(reported, request, request['chunks'][0], recording=True)
    altered = copy.deepcopy(request); altered['independent_repo_content'] += 'changed'
    assert not result_matches_request(reported, altered, altered['chunks'][0], recording=True)
    altered = copy.deepcopy(request); altered['source_authorization']['independent_repo_read']['path'] = 'other.md'
    assert not result_matches_request(reported, altered, altered['chunks'][0], recording=True)
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path, source='a/repo-source.md')
    monkeypatch.setenv('WIKI_FOLDER_INGEST_HOST_REPOSITORIES', json.dumps([['a', chosen[0], chosen[1], chosen[3]]]))
    sys.argv.extend(['--folder-repo', *chosen])
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)['count'] == 1
    repeated = run(str(project / 'a/repo-source.md'), 'system', project, load_config(project),
                   approved_revision=sha, folder_selection=selection, write=False)
    assert not repeated.blocked and repeated.pending_llm_calls == 0


def test_repository_requires_exact_trusted_binding_before_read(project, monkeypatch):
    sha, selection, chosen = repository_fixture(project)
    import wiki_core.repo_read as reader
    monkeypatch.setattr(reader, 'read_independent_repo', lambda *a, **k: __import__('pytest').fail('unauthorized repository read'))
    bad = FolderIngestionSelection(FolderHostBinding(project, ('a',)), 'a', 'a/index.md', 'a/result.md', None, chosen)
    result = run(str(project / 'a/repo-source.md'), 'system', project, load_config(project),
                 approved_revision=sha, folder_selection=bad)
    assert result.blocked and not result.written


def test_repository_identity_change_blocks_result_recording(project, monkeypatch, tmp_path, capsys):
    sha, selection, chosen = repository_fixture(project)
    initial = run(str(project / 'a/repo-source.md'), 'system', project, load_config(project),
                  approved_revision=sha, folder_selection=selection)
    request = json.loads((project / initial.request_path).read_text())
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path, source='a/repo-source.md')
    monkeypatch.setenv('WIKI_FOLDER_INGEST_HOST_REPOSITORIES', json.dumps([['a', chosen[0], chosen[1], chosen[3]]]))
    sys.argv.extend(['--folder-repo', *chosen])
    git(project / 'a/clone', 'remote', 'set-url', 'origin', 'https://example.test/group/other.git')
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out)['blocked']
    from wiki_core.paths import WikiPaths
    cache = WikiPaths(project, load_config(project)).llm_cache / 'folder-v2' / (request['chunks'][0]['cache_key'] + '.json')
    assert not cache.exists()


def test_repository_request_helper_requires_unambiguous_binding(project):
    from wiki_core.folder_ingestion_v2 import independent_repo_selection_for_request
    import pytest
    sha, selection, chosen = repository_fixture(project)
    initial = run(str(project / 'a/repo-source.md'), 'system', project, load_config(project),
                  approved_revision=sha, folder_selection=selection)
    request = json.loads((project / initial.request_path).read_text())
    assert independent_repo_selection_for_request(selection.host, 'a', request['source_authorization']) == chosen
    other = FolderHostBinding(project, ('a',))
    with pytest.raises(ValueError):
        independent_repo_selection_for_request(other, 'a', request['source_authorization'])
