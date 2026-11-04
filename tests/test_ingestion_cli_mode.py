"""CLI mode selection cannot silently fall back to legacy authority."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('name', ['wiki_ingest', 'wiki_llm_context_pass'])
@pytest.mark.parametrize('options', [
    ['--approved-revision', 'a' * 40],
    ['--policy-context', 'root'],
    ['--folder-context', 'a'],
    ['--folder-context', 'a', '--approved-revision', 'a' * 40, '--policy-context', 'root'],
    ['--mode', 'folder'],
    ['--mode', 'v1', '--approved-revision', 'a' * 40],
    ['--mode', 'working-tree', '--approved-revision', 'a' * 40],
    ['--mode', 'working-tree', '--folder-context', 'a'],
    ['--mode', 'working-tree', '--folder-queries', 'queries.json'],
    ['--mode', 'v1', '--approved-revision', 'a' * 40, '--policy-context', 'root',
     '--folder-context', 'a'],
])
def test_cli_rejects_missing_or_mixed_authority_before_config(name, options, monkeypatch):
    spec = importlib.util.spec_from_file_location('mode_' + name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'load_config', lambda *args: pytest.fail('configuration must not load'))
    monkeypatch.setattr(sys, 'argv', [name, '--source', 'unread.md', '--context', 'synthetic', *options])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2


@pytest.mark.parametrize('name', ['wiki_ingest', 'wiki_llm_context_pass'])
@pytest.mark.parametrize('options', [[], ['--approved-revision', 'a' * 40, '--policy-context', 'root']])
def test_existing_selections_reach_configuration_without_mode(name, options, monkeypatch):
    spec = importlib.util.spec_from_file_location('normal_' + name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class ReachedConfiguration(Exception):
        pass
    def reached(*_args):
        raise ReachedConfiguration
    monkeypatch.setattr(module, 'load_config', reached)
    monkeypatch.setattr(sys, 'argv', [name, '--source', 'unread.md', '--context', 'synthetic', *options])
    with pytest.raises(ReachedConfiguration):
        module.main()


@pytest.mark.parametrize('name', ['wiki_ingest', 'wiki_llm_context_pass'])
def test_selected_folder_without_host_never_falls_back(name, monkeypatch):
    spec = importlib.util.spec_from_file_location('folder_' + name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv('WIKI_FOLDER_INGEST_HOST_ROOT', raising=False)
    monkeypatch.delenv('WIKI_FOLDER_INGEST_HOST_FOLDERS', raising=False)
    monkeypatch.setattr(module, 'load_config', lambda *args: pytest.fail('configuration must not load'))
    monkeypatch.setattr(sys, 'argv', [name, '--source', 'unread.md', '--context', 'synthetic',
        '--approved-revision', 'a' * 40, '--folder-context', 'a', '--folder-index', 'a/index.md',
        '--folder-output', 'a/result.md'])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2


def test_existing_ingest_runs_without_mode(tmp_path, monkeypatch, capsys):
    from wiki_core.config import WikiConfig
    spec = importlib.util.spec_from_file_location('normal_ingest_integration', ROOT / 'scripts/wiki_ingest.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / 'source.md'
    source.write_text('Synthetic source for the existing ingestion workflow.\n')
    monkeypatch.setattr(module, 'load_config', lambda _: WikiConfig(repo_id='synthetic-normal-ingest'))
    monkeypatch.setattr(sys, 'argv', ['wiki_ingest.py', '--root', str(tmp_path),
                                    '--source', str(source), '--context', 'synthetic'])
    assert module.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output['written'] and not output['blocked']
    assert (tmp_path / output['manifest_path']).is_file()
    request = json.loads((tmp_path / output['request_path']).read_text())
    assert request['block_context_package']['policy_mode'] == 'legacy_working_tree_compatibility'
    assert not request['block_context_package']['policy_enforced']
