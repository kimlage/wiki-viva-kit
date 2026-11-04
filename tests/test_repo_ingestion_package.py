"""Independent Git evidence in the existing local ingestion package."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from tests.test_ingestion_budget import approved
from tests.test_repo_read import repo, git
from wiki_core.config import load_config
from wiki_core.ingest import run


def selection(repo):
    return [str(repo), 'example.test/group/project', git(repo, 'rev-parse', 'HEAD'), 'guide.md']


def prepare(approved, repo):
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area/AGENTS.md').write_text('Synthetic local guidance.')
    (root / 'area/index.md').write_text('Synthetic local index.')
    chosen = selection(repo)
    result = run(str(source), 'system', root, load_config(root), entry_folder='area',
                 repo_selections=[chosen], record_score=False)
    assert not result.blocked and result.written
    request = json.loads((root / result.request_path).read_text())
    return root, source, chosen, request


def recorded_result(request):
    fixture = Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json'
    row = request['chunks'][0]
    return {**json.loads(fixture.read_text()), 'perspectives': {},
            **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
            **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')}}


def pass_cli(root, source, chosen, payload, monkeypatch):
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_llm_context_pass.py'
    spec = importlib.util.spec_from_file_location('repo_selected_record', script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(sys, 'argv', [str(script), '--root', str(root), '--source', str(source),
        '--context', 'system', '--folder', 'area', '--repo', *chosen, '--record-result', str(payload)])
    return module


def test_exact_git_selection_is_bound_and_real_record_revalidates(approved, repo, monkeypatch, tmp_path, capsys):
    root, source, chosen, request = prepare(approved, repo)
    doc = next(row for row in request['block_context_package']['documents'] if row['origin'] == 'independent_git')
    receipt = doc['repository_read']
    assert doc['repository_root'] == str(repo.resolve())
    assert (receipt['repository']['identity'], receipt['revision'], receipt['path']) == tuple(chosen[1:])
    assert receipt['blob'] == git(repo, 'rev-parse', f'{chosen[2]}:guide.md')
    assert doc['text'] == '# Guide\nUseful content.\n'
    assert 'caller_authorization_required' in receipt['access']
    # Changing another file advances HEAD but does not rewrite historical evidence.
    (repo / 'other.md').write_text('unrelated\n')
    git(repo, 'add', 'other.md'); git(repo, 'commit', '-qm', 'unrelated change')
    assert git(repo, 'rev-parse', 'HEAD') != chosen[2]
    payload = tmp_path / 'result.json'; payload.write_text(json.dumps(recorded_result(request)))
    module = pass_cli(root, source, chosen, payload, monkeypatch)
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)['count'] == 1
    from wiki_core.llm.context_pass import read_matching_result
    from wiki_core.paths import WikiPaths
    assert read_matching_result(WikiPaths(root, load_config(root)).llm_cache, request, request['chunks'][0], root=root) is not None


def test_changed_repo_identity_blocks_result_without_cache(approved, repo, monkeypatch, tmp_path, capsys):
    root, source, chosen, request = prepare(approved, repo)
    payload = tmp_path / 'result.json'; payload.write_text(json.dumps(recorded_result(request)))
    module = pass_cli(root, source, chosen, payload, monkeypatch)
    git(repo, 'remote', 'set-url', 'origin', 'https://example.test/group/other.git')
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out)['blocked']
    from wiki_core.paths import WikiPaths
    from wiki_core.llm.context_pass import read_matching_result
    assert read_matching_result(WikiPaths(root, load_config(root)).llm_cache, request, request['chunks'][0], root=root) is None


def test_all_selected_git_metadata_is_checked_before_first_body(approved, repo, monkeypatch):
    from wiki_core import repo_read
    from wiki_core.llm.context_pass import ingestion_block_context
    root, _, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area/AGENTS.md').write_text('Local guidance.')
    (root / 'area/index.md').write_text('Local index.')
    chosen = selection(repo)
    second = [*chosen[:3], 'missing.md']
    monkeypatch.setattr(repo_read, '_read_prepared_repo', lambda *_a, **_k: pytest.fail('first body opened before selection validation'))
    with pytest.raises(ValueError):
        ingestion_block_context(root, load_config(root), {}, [], entry_folder='area', repo_selections=[chosen, second])


def test_repo_selection_cannot_replace_approved_context(approved, repo, monkeypatch):
    from wiki_core import repo_read
    root, source, sha, _ = approved
    monkeypatch.setattr(repo_read, '_prepare_repo_read', lambda *_a, **_k: pytest.fail('repo opened'))
    result = run(str(source), 'system', root, load_config(root), approved_revision=sha,
                 policy_context='root', repo_selections=[selection(repo)])
    assert result.blocked and not result.written


def test_origin_change_at_write_fence_blocks_cache(approved, repo, monkeypatch, tmp_path, capsys):
    from wiki_core import repo_read
    from wiki_core.paths import WikiPaths
    root, source, chosen, request = prepare(approved, repo)
    payload = tmp_path / 'result.json'; payload.write_text(json.dumps(recorded_result(request)))
    module = pass_cli(root, source, chosen, payload, monkeypatch)
    original = repo_read._prepare_repo_read
    calls = 0
    def change_at_fence(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            git(repo, 'remote', 'set-url', 'origin', 'https://example.test/group/other.git')
        return original(*args, **kwargs)
    monkeypatch.setattr(repo_read, '_prepare_repo_read', change_at_fence)
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out)['blocked']
    assert calls == 2
    from wiki_core.llm.context_pass import read_matching_result
    assert read_matching_result(WikiPaths(root, load_config(root)).llm_cache, request, request['chunks'][0], root=root) is None


def test_missing_repo_selection_cannot_record_previous_interpretation(approved, repo, monkeypatch, tmp_path, capsys):
    from wiki_core.paths import WikiPaths
    root, source, chosen, request = prepare(approved, repo)
    payload = tmp_path / 'result.json'; payload.write_text(json.dumps(recorded_result(request)))
    module = pass_cli(root, source, chosen, payload, monkeypatch)
    index = sys.argv.index('--repo')
    del sys.argv[index:index + 5]
    assert module.main() == 2
    capsys.readouterr()
    from wiki_core.llm.context_pass import read_matching_result
    assert read_matching_result(WikiPaths(root, load_config(root)).llm_cache, request, request['chunks'][0], root=root) is None


def test_retargeted_repo_root_is_refused_before_reopening(approved, repo, monkeypatch, tmp_path):
    from wiki_core import repo_read
    from wiki_core.ingest import pipeline
    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area/AGENTS.md').write_text('Local guidance.')
    (root / 'area/index.md').write_text('Local index.')
    alias = tmp_path / 'repo-link'
    alias.symlink_to(repo, target_is_directory=True)
    other = tmp_path / 'other-repo'; other.mkdir()
    chosen = [str(alias), *selection(repo)[1:]]
    original_request = pipeline.build_context_request
    original_prepare = repo_read._prepare_repo_read
    calls = 0
    def change_root(*args, **kwargs):
        request = original_request(*args, **kwargs)
        alias.unlink(); alias.symlink_to(other, target_is_directory=True)
        return request
    def guarded(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            pytest.fail('retargeted repo was reopened')
        return original_prepare(*args, **kwargs)
    monkeypatch.setattr(pipeline, 'build_context_request', change_root)
    monkeypatch.setattr(repo_read, '_prepare_repo_read', guarded)
    result = run(str(source), 'system', root, load_config(root), entry_folder='area',
                 repo_selections=[chosen], record_score=False)
    assert result.blocked and not result.written and calls == 1


@pytest.mark.parametrize('allow_unrequested', [False, True])
def test_unrequested_legacy_record_does_not_close_local_git_request(approved, repo, monkeypatch, tmp_path, capsys, allow_unrequested):
    from wiki_core.llm.context_pass import read_matching_result
    from wiki_core.paths import WikiPaths
    root, source, chosen, request = prepare(approved, repo)
    payload = tmp_path / 'result.json'; payload.write_text(json.dumps(recorded_result(request)))
    module = pass_cli(root, source, chosen, payload, monkeypatch)
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--root', str(root), '--context', 'system',
                                     '--record-result', str(payload), *(['--allow-unrequested'] if allow_unrequested else [])])
    assert module.main() == (0 if allow_unrequested else 2)
    capsys.readouterr()
    assert read_matching_result(WikiPaths(root, load_config(root)).llm_cache, request, request['chunks'][0], root=root) is None


@pytest.mark.parametrize('column, replacement', [
    (0, 'relative/root'), (1, 'https://example.test/group/project'),
    (2, 'HEAD'), (3, '../outside.md'), (3, 'guide.md?%2573ig%253Dfake'),
])
def test_invalid_repo_selection_is_refused_before_any_body(approved, repo, monkeypatch, column, replacement):
    from wiki_core import repo_read
    from wiki_core.llm.context_pass import ingestion_block_context
    root, _, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area/AGENTS.md').write_text('Local guidance.')
    (root / 'area/index.md').write_text('Local index.')
    chosen = selection(repo)
    bad = list(chosen); bad[column] = replacement
    monkeypatch.setattr(repo_read, '_read_prepared_repo', lambda *_a, **_k: pytest.fail('repository body opened'))
    with pytest.raises(ValueError) as error:
        ingestion_block_context(root, load_config(root), {}, [], entry_folder='area', repo_selections=[chosen, bad])
    assert replacement not in str(error.value)


def test_same_blob_at_distinct_revisions_has_distinct_bound_result(approved, repo):
    from copy import deepcopy
    from wiki_core.llm.cache import cache_key
    from wiki_core.llm.context_pass import context_fingerprint, ingestion_block_context, result_matches_request
    root, _source, chosen, first = prepare(approved, repo)
    result = recorded_result(first)
    old_row = first['chunks'][0]
    assert result_matches_request(result, first, old_row, recording=True)
    (repo / 'other.md').write_text('unrelated\n')
    git(repo, 'add', 'other.md'); git(repo, 'commit', '-qm', 'unrelated change')
    newer = [chosen[0], chosen[1], git(repo, 'rev-parse', 'HEAD'), chosen[3]]
    second_package = ingestion_block_context(root, load_config(root), {}, [], entry_folder='area', repo_selections=[newer])
    first_repo = next(row for row in first['block_context_package']['documents'] if row['origin'] == 'independent_git')
    second_repo = next(row for row in second_package['documents'] if row['origin'] == 'independent_git')
    assert first_repo['repository_read']['blob'] == second_repo['repository_read']['blob']
    assert first_repo['repository_read']['revision'] != second_repo['repository_read']['revision']
    second = deepcopy(first); second['block_context_package'] = second_package
    fingerprint = context_fingerprint(second, old_row['provenance'])
    new_row = {**old_row, 'context_sha256': fingerprint,
               'cache_key': cache_key(old_row['chunk_hash_sha256'], first['prompt_version'],
                                      first['schema_version'], first['model_profile'], context_sha256=fingerprint)}
    assert first['source_id'] == second['source_id'] and new_row['cache_key'] != old_row['cache_key']
    assert not result_matches_request(result, second, new_row, recording=True)


def test_retargeted_repo_alias_between_capture_and_record_is_refused_before_blob(approved, repo, monkeypatch, tmp_path, capsys):
    import subprocess
    from wiki_core import repo_read
    from wiki_core.llm.context_pass import read_matching_result
    from wiki_core.paths import WikiPaths

    root, source, _, _ = approved
    (root / 'area').mkdir(exist_ok=True)
    (root / 'area/AGENTS.md').write_text('Local guidance.')
    (root / 'area/index.md').write_text('Local index.')
    alias = tmp_path / 'repo-link'
    alias.symlink_to(repo, target_is_directory=True)
    chosen = [str(alias), *selection(repo)[1:]]
    captured = run(str(source), 'system', root, load_config(root), entry_folder='area',
                   repo_selections=[chosen], record_score=False)
    assert not captured.blocked
    request = json.loads((root / captured.request_path).read_text())
    second = tmp_path / 'other-repo'
    subprocess.run(['git', 'clone', '--quiet', '--no-local', str(repo), str(second)], check=True)
    git(second, 'remote', 'set-url', 'origin', 'https://example.test/group/project.git')
    assert git(second, 'rev-parse', 'HEAD') == chosen[2]
    alias.unlink(); alias.symlink_to(second, target_is_directory=True)
    payload = tmp_path / 'result.json'; payload.write_text(json.dumps(recorded_result(request)))
    module = pass_cli(root, source, chosen, payload, monkeypatch)
    monkeypatch.setattr(repo_read, '_read_prepared_repo', lambda *_a, **_k: pytest.fail('retargeted repository body opened'))
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out)['blocked']
    assert read_matching_result(WikiPaths(root, load_config(root)).llm_cache,
                                request, request['chunks'][0], root=root) is None


def test_missing_or_invalid_retained_request_never_opens_repo_body(approved, repo, monkeypatch, tmp_path, capsys):
    from wiki_core import repo_read
    root, source, chosen, request = prepare(approved, repo)
    payload = tmp_path / 'result.json'; payload.write_text(json.dumps(recorded_result(request)))
    module = pass_cli(root, source, chosen, payload, monkeypatch)
    from wiki_core.paths import WikiPaths
    retained = WikiPaths(root, load_config(root)).extraction_events / f"{request['source_id']}-llm-context-request.json"
    other = retained.parent / 'other-source-llm-context-request.json'
    other.write_text(json.dumps(request))
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if path == other:
            pytest.fail('unselected retained request opened')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    monkeypatch.setattr(repo_read, '_read_prepared_repo', lambda *_a, **_k: pytest.fail('repository body opened'))
    for contents in (None, '{"input_stage_status": 1, "input_stage_status": 2}', '[' * 1100 + '0' + ']' * 1100):
        if contents is None:
            retained.unlink(missing_ok=True)
        else:
            retained.write_text(contents)
        assert module.main() == 2
        assert json.loads(capsys.readouterr().out)['blocked']
