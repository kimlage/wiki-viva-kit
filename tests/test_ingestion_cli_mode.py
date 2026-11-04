"""CLI mode selection cannot silently fall back to legacy authority."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('name', ['wiki_ingest', 'wiki_llm_context_pass'])
@pytest.mark.parametrize('options', [
    [],
    ['--approved-revision', 'a' * 40, '--policy-context', 'root'],
    ['--mode', 'v1', '--approved-revision', 'a' * 40],
    ['--mode', 'working-tree', '--approved-revision', 'a' * 40],
    ['--mode', 'working-tree', '--folder-context', 'a'],
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
