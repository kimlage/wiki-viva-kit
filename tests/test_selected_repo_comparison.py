"""Synthetic local comparison; selection is not proof of file consumption."""
import json
from pathlib import Path
import pytest

from tests.test_ingestion_budget import approved
from tests.test_repo_read import repo, git
from tests.test_repo_ingestion_package import prepare, pass_cli
from tests.test_local_result_cache import result_for
from wiki_core.config import load_config
from wiki_core.consolidate import compare_selected_repo
from wiki_core.paths import WikiPaths


def setup_case(approved, repo, monkeypatch, tmp_path, capsys):
    root, source, chosen, request = prepare(approved, repo)
    payload = tmp_path / 'synthetic-result.json'
    payload.write_text(json.dumps(list({row['cache_key']: result_for(request, row) for row in request['chunks']}.values())))
    assert pass_cli(root, source, chosen, payload, monkeypatch).main() == 0
    capsys.readouterr()
    source_page = root / 'area/source.md'
    source_page.write_text('---\npage_id: repo-source\npage_type: source\nplatform: repo\nsource_locator: https://example.test/group/project.git\n---\nSource.\n')
    a = root / 'area/a.md'
    a.write_text('---\npage_id: a\ninformation_requirements:\n  - target: area/source.md\n    fields: [body]\n    temporal: current\n    max_age_days: 30\n---\nA.\n')
    b = root / 'area/b.md'
    b.write_text('---\npage_id: b\n---\nB.\n')
    (repo / 'guide.md').write_text('# Guide\nChanged synthetic content.\n')
    git(repo, 'add', 'guide.md'); git(repo, 'commit', '-qm', 'change synthetic file')
    new_revision = git(repo, 'rev-parse', 'HEAD')
    kwargs = dict(source_page='area/source.md', candidates=['area/a.md', 'area/b.md'],
                  repo_root=str(repo), identity=chosen[1], revision=new_revision, repo_path=chosen[3], entry_folder='area', source_file=str(source))
    return root, request, kwargs


def test_comparison_is_partial_and_never_updates_candidates(approved, repo, monkeypatch, tmp_path, capsys):
    root, request, kwargs = setup_case(approved, repo, monkeypatch, tmp_path, capsys)
    paths = WikiPaths(root, load_config(root))
    original = [(root / x).read_bytes() for x in kwargs['candidates']]
    result = compare_selected_repo(root, paths, request, **kwargs)
    assert result['repository_comparison']['changed'] is True
    assert result['candidates'] == [
        {'path': 'area/a.md', 'state': 'review_pending', 'source_page_requirement': 'declared',
         'reason': 'operator_selected_page_requirement_file_consumption_unknown', 'blocking': False,
         'file_consumption': 'unknown', 'verification_performed': False},
        {'path': 'area/b.md', 'state': 'unknown', 'source_page_requirement': 'unknown',
         'reason': 'insufficient_file_consumption_evidence', 'blocking': False,
         'file_consumption': 'unknown', 'verification_performed': False}]
    assert result['coverage'] == 'explicit_candidates_only; selected_repository_only; file_consumption_unknown'
    assert result['write'] == result['review'] == 'not_performed'
    assert [(root / x).read_bytes() for x in kwargs['candidates']] == original


def test_changed_or_unrecorded_request_never_authorizes_comparison(approved, repo, monkeypatch, tmp_path, capsys):
    root, request, kwargs = setup_case(approved, repo, monkeypatch, tmp_path, capsys)
    paths = WikiPaths(root, load_config(root))
    request['block_context_package']['documents'][-1]['text'] += 'tampered'
    with pytest.raises(ValueError):
        compare_selected_repo(root, paths, request, **kwargs)
    kwargs['identity'] = 'example.test/group/other'
    with pytest.raises(ValueError):
        compare_selected_repo(root, paths, request, **kwargs)


def test_locator_and_explicit_candidate_paths_are_required(approved, repo, monkeypatch, tmp_path, capsys):
    root, request, kwargs = setup_case(approved, repo, monkeypatch, tmp_path, capsys)
    paths = WikiPaths(root, load_config(root))
    page = root / kwargs['source_page']
    page.write_text(page.read_text().replace('https://example.test/group/project.git', 'area/source.md'))
    with pytest.raises(ValueError):
        compare_selected_repo(root, paths, request, **kwargs)


def test_cli_compares_only_explicit_inputs_and_refuses_empty_request(approved, repo, monkeypatch, tmp_path, capsys):
    import sys
    from tests.test_local_result_cache import module
    root, request, kwargs = setup_case(approved, repo, monkeypatch, tmp_path, capsys)
    paths = WikiPaths(root, load_config(root))
    from wiki_core.llm.context_pass import local_request_path
    retained = local_request_path(paths, request)
    unrelated = root / 'area/unselected.md'
    unrelated.write_text('never open this file')
    original_open = Path.open
    def guard(path, *args, **options):
        if path == unrelated:
            pytest.fail('unselected page opened')
        return original_open(path, *args, **options)
    monkeypatch.setattr(Path, 'open', guard)
    cli = module('wiki_consolidate')
    monkeypatch.setattr(cli, 'ROOT', root)
    args = ['wiki_consolidate.py', '--source', request['source_id'], '--request', str(retained),
            '--source-page', kwargs['source_page'], '--folder', kwargs['entry_folder'], '--source-file', kwargs['source_file'],
            '--candidate', kwargs['candidates'][0], '--candidate', kwargs['candidates'][1],
            '--repo-compare', kwargs['repo_root'], kwargs['identity'], kwargs['revision'], kwargs['repo_path']]
    monkeypatch.setattr(sys, 'argv', args)
    assert cli.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report['repository_comparison']['changed'] is True
    assert report['candidates'][0]['file_consumption'] == 'unknown'
    assert report['review'] == 'not_performed'
    args[args.index('--request') + 1] = ''
    with pytest.raises(SystemExit):
        cli.main()
    assert not capsys.readouterr().out


def test_changed_folder_or_crossed_repository_is_not_reopened(approved, repo, monkeypatch, tmp_path, capsys):
    from wiki_core import repo_read
    root, request, kwargs = setup_case(approved, repo, monkeypatch, tmp_path, capsys)
    paths = WikiPaths(root, load_config(root))
    (root / 'area/index.md').write_text('changed after capture')
    monkeypatch.setattr(repo_read, '_read_prepared_repo', lambda *_a, **_k: pytest.fail('repository body opened'))
    with pytest.raises(ValueError):
        compare_selected_repo(root, paths, request, **kwargs)


def test_unscoped_page_id_is_not_guessed_as_selected_source(approved, repo, monkeypatch, tmp_path, capsys):
    root, request, kwargs = setup_case(approved, repo, monkeypatch, tmp_path, capsys)
    candidate = root / kwargs['candidates'][0]
    candidate.write_text(candidate.read_text().replace('target: area/source.md', 'target: repo-source'))
    report = compare_selected_repo(root, WikiPaths(root, load_config(root)), request, **kwargs)
    assert report['candidates'][0]['state'] == 'unknown'
    assert report['candidates'][0]['source_page_requirement'] == 'unknown'
    assert report['candidates'][0]['file_consumption'] == 'unknown'


def test_changed_captured_source_blocks_before_reopening_repository(approved, repo, monkeypatch, tmp_path, capsys):
    from wiki_core import repo_read
    root, request, kwargs = setup_case(approved, repo, monkeypatch, tmp_path, capsys)
    source = approved[1]
    source.write_text(source.read_text() + '\nchanged synthetic source')
    monkeypatch.setattr(repo_read, '_read_prepared_repo', lambda *_a, **_k: pytest.fail('repository body opened'))
    with pytest.raises(ValueError, match='source changed'):
        compare_selected_repo(root, WikiPaths(root, load_config(root)), request, **kwargs)


def test_mismatched_selected_source_is_not_read(approved, repo, monkeypatch, tmp_path, capsys):
    root, request, kwargs = setup_case(approved, repo, monkeypatch, tmp_path, capsys)
    selected = root / 'area/other-source.md'; selected.write_text('different synthetic source')
    kwargs['source_file'] = str(selected)
    original = Path.open
    def guarded(path, *args, **options):
        if path in (selected, approved[1]):
            pytest.fail('source body opened before matching explicit selection')
        return original(path, *args, **options)
    monkeypatch.setattr(Path, 'open', guarded)
    with pytest.raises(ValueError, match='selected source differs'):
        compare_selected_repo(root, WikiPaths(root, load_config(root)), request, **kwargs)


def test_source_over_limit_is_not_opened(approved, repo, monkeypatch, tmp_path, capsys):
    root, request, kwargs = setup_case(approved, repo, monkeypatch, tmp_path, capsys)
    source = approved[1]
    with source.open('ab') as stream:
        stream.truncate(16_000_001)
    original = Path.open
    def guarded(path, *args, **options):
        if path == source:
            pytest.fail('oversized source was opened')
        return original(path, *args, **options)
    monkeypatch.setattr(Path, 'open', guarded)
    with pytest.raises(ValueError, match='source exceeds'):
        compare_selected_repo(root, WikiPaths(root, load_config(root)), request, **kwargs)


def test_source_growing_during_read_is_not_truncated(approved, repo, monkeypatch, tmp_path, capsys):
    import io
    root, request, kwargs = setup_case(approved, repo, monkeypatch, tmp_path, capsys)
    source = approved[1]
    original = Path.open
    def growing(path, *args, **options):
        if path == source:
            return io.BytesIO(b'x' * 16_000_001)
        return original(path, *args, **options)
    monkeypatch.setattr(Path, 'open', growing)
    with pytest.raises(ValueError, match='source exceeds'):
        compare_selected_repo(root, WikiPaths(root, load_config(root)), request, **kwargs)


def test_invalid_candidate_blocks_before_any_selected_body(approved, repo, monkeypatch, tmp_path, capsys):
    import sys
    from tests.test_local_result_cache import module
    from wiki_core.llm.context_pass import local_request_path
    root, request, kwargs = setup_case(approved, repo, monkeypatch, tmp_path, capsys)
    paths = WikiPaths(root, load_config(root)); retained = local_request_path(paths, request)
    kwargs['candidates'].append('../outside.md')
    originals = {approved[1], retained, root / 'area/index.md', root / 'area/source.md',
                 root / 'area/a.md', root / 'area/b.md'}
    original_open = Path.open
    def guarded(path, *args, **options):
        if path in originals:
            pytest.fail('selected body opened before complete selection validation')
        return original_open(path, *args, **options)
    monkeypatch.setattr(Path, 'open', guarded)
    with pytest.raises(ValueError):
        compare_selected_repo(root, paths, request, **kwargs)
    cli = module('wiki_consolidate'); monkeypatch.setattr(cli, 'ROOT', root)
    monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', '--source', request['source_id'],
        '--request', str(retained), '--source-page', kwargs['source_page'], '--source-file', kwargs['source_file'],
        '--folder', 'area', '--candidate', 'area/a.md', '--candidate', '../outside.md',
        '--repo-compare', kwargs['repo_root'], kwargs['identity'], kwargs['revision'], kwargs['repo_path']])
    assert cli.main() == 2
    assert not capsys.readouterr().out


def test_retargeted_repo_alias_is_refused_before_any_git_command(approved, repo, monkeypatch, tmp_path, capsys):
    import sys
    from tests.test_local_result_cache import module
    from wiki_core import repo_read
    from wiki_core.llm.context_pass import local_request_path

    root, request, kwargs = setup_case(approved, repo, monkeypatch, tmp_path, capsys)
    other = tmp_path / 'unselected-git-root'
    other.mkdir()
    alias = tmp_path / 'repo-alias'
    alias.symlink_to(other, target_is_directory=True)
    kwargs['repo_root'] = str(alias)
    original_git = repo_read._git
    def guarded_git(path, *args):
        if Path(path).resolve() == other.resolve():
            pytest.fail('Git command reached the retargeted repository')
        return original_git(path, *args)
    monkeypatch.setattr(repo_read, '_git', guarded_git)
    original_reader_git = repo_read._LocalRepositoryReader._git
    def guarded_reader_git(reader, *args):
        if reader.root.resolve() == other.resolve():
            pytest.fail('Git object command reached the retargeted repository')
        return original_reader_git(reader, *args)
    monkeypatch.setattr(repo_read._LocalRepositoryReader, '_git', guarded_reader_git)
    paths = WikiPaths(root, load_config(root))
    with pytest.raises(ValueError):
        compare_selected_repo(root, paths, request, **kwargs)

    cli = module('wiki_consolidate')
    monkeypatch.setattr(cli, 'ROOT', root)
    retained = local_request_path(paths, request)
    monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', '--source', request['source_id'],
        '--request', str(retained), '--source-page', kwargs['source_page'], '--source-file', kwargs['source_file'],
        '--folder', kwargs['entry_folder'], '--candidate', kwargs['candidates'][0],
        '--repo-compare', str(alias), kwargs['identity'], kwargs['revision'], kwargs['repo_path']])
    assert cli.main() == 2
    assert not capsys.readouterr().out


@pytest.mark.parametrize('explicit_index', [False, True])
def test_auxiliary_repo_comparison_uses_retained_ancestor_index(approved, repo, monkeypatch, tmp_path, capsys, explicit_index):
    import sys
    from tests.test_local_result_cache import module
    from tests.test_repo_ingestion_package import selection
    from wiki_core.ingest import run
    root, source, _, _ = approved
    auxiliary = root / 'area/aux'
    auxiliary.mkdir(parents=True)
    (root / 'area/AGENTS.md').write_text('Area guidance')
    (root / 'area/index.md').write_text('Area index')
    (auxiliary / 'AGENTS.override.md').write_text('Auxiliary guidance')
    chosen = selection(repo)
    config = load_config(root)
    produced = run(str(source), 'system', root, config, entry_folder='area/aux', repo_selections=[chosen], record_score=False)
    assert not produced.blocked
    request = json.loads((root / produced.request_path).read_text())
    assert request['block_context_package']['entry_index'] == 'area/index.md'
    payload = tmp_path / 'results.json'
    payload.write_text(json.dumps(list({row['cache_key']: result_for(request, row) for row in request['chunks']}.values())))
    pass_module = module('wiki_llm_context_pass')
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--root', str(root), '--source', str(source),
        '--context', 'system', '--folder', 'area/aux', '--repo', *chosen, '--request', produced.request_path,
        '--record-result', str(payload)])
    assert pass_module.main() == 0
    capsys.readouterr()
    (root / 'area/source.md').write_text('---\npage_id: repo-source\npage_type: source\nplatform: repo\nsource_locator: https://example.test/group/project.git\n---\n')
    (root / 'area/candidate.md').write_text('---\npage_id: candidate\n---\n')
    (repo / 'guide.md').write_text('# Guide\nNew content.\n')
    git(repo, 'add', 'guide.md'); git(repo, 'commit', '-qm', 'new synthetic revision')
    kwargs = dict(source_page='area/source.md', candidates=['area/candidate.md'], repo_root=str(repo),
                  identity=chosen[1], revision=git(repo, 'rev-parse', 'HEAD'), repo_path=chosen[3],
                  entry_folder='area/aux', source_file=str(source),
                  entry_index='area/index.md' if explicit_index else None)
    result = compare_selected_repo(root, WikiPaths(root, config), request, **kwargs)
    assert result['repository_comparison']['changed'] is True
    assert result['coverage'] == 'explicit_candidates_only; selected_repository_only; file_consumption_unknown'
    cli = module('wiki_consolidate')
    monkeypatch.setattr(cli, 'ROOT', root)
    args = ['wiki_consolidate.py', '--source', request['source_id'], '--request', produced.request_path,
            '--source-page', kwargs['source_page'], '--candidate', kwargs['candidates'][0],
            '--folder', 'area/aux', '--source-file', str(source), '--repo-compare',
            str(repo), chosen[1], kwargs['revision'], chosen[3]]
    if explicit_index:
        args.extend(['--index', 'area/index.md'])
    monkeypatch.setattr(sys, 'argv', args)
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)['repository_comparison']['changed'] is True

    # A missing retained index fails before any selected body is opened.
    retained_index = root / 'area/index.md'
    backup = root / 'area/index.bak'
    retained_index.rename(backup)
    original = Path.open
    def no_body(path, *args, **options):
        if path in (source, root / 'area/AGENTS.md', root / 'area/source.md', root / 'area/candidate.md'):
            pytest.fail('opened content before checking the retained index')
        return original(path, *args, **options)
    with monkeypatch.context() as guard:
        guard.setattr(Path, 'open', no_body)
        with pytest.raises(ValueError):
            compare_selected_repo(root, WikiPaths(root, config), request, **kwargs)
    backup.rename(retained_index)

    # An explicitly different index cannot fall back to the retained ancestor.
    wrong = auxiliary / 'index.md'
    wrong.write_text('Unselected index')
    kwargs['entry_index'] = 'area/aux/index.md'
    original = Path.open
    def guarded(path, *args, **options):
        if path in (wrong, source, root / 'area/source.md', root / 'area/candidate.md'):
            pytest.fail('opened content after an invalid selection')
        return original(path, *args, **options)
    monkeypatch.setattr(Path, 'open', guarded)
    with pytest.raises(ValueError):
        compare_selected_repo(root, WikiPaths(root, config), request, **kwargs)
