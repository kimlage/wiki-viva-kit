"""New v1 source operations stop before opening sources or retained results."""
import importlib.util
from pathlib import Path
import sys

import pytest

from wiki_core.config import WikiConfig
from wiki_core.ingest import run

BASE = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('options', [
    {'approved_revision': 'a' * 40},
    {'policy_context': 'root'},
    {'approved_revision': 'a' * 40, 'policy_context': 'root'},
])
def test_pipeline_stops_before_source_or_destination_checks(tmp_path, monkeypatch, options):
    import wiki_core.traversal as traversal
    import wiki_core.ingest.pipeline as pipeline
    def forbidden(*args, **kwargs):
        pytest.fail('retired v1 path accessed a source or destination')
    monkeypatch.setattr(traversal, 'require_wiki_boundaries', forbidden)
    monkeypatch.setattr(pipeline, 'build_manifest', forbidden)
    result = run(str(tmp_path / 'source.md'), 'synthetic', tmp_path, WikiConfig(), **options)
    assert result.blocked and not result.written and result.request_path is None
    assert result.context_error_code == 'v1_ingestion_retired'
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('script', ['wiki_ingest', 'wiki_llm_context_pass'])
@pytest.mark.parametrize('option', ['--approved-revision', '--policy-context'])
def test_cli_refuses_v1_before_opening_config_source_or_result(tmp_path, monkeypatch, capsys, script, option):
    spec = importlib.util.spec_from_file_location('retired_' + script, BASE / 'scripts' / (script + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def forbidden(*args, **kwargs):
        pytest.fail('retired v1 command opened a config, source or result')
    monkeypatch.setattr(module, 'load_config', forbidden)
    args = [script, '--root', str(tmp_path), '--source', 'sentinel.md', '--context', 'synthetic', option, 'sentinel']
    if script == 'wiki_llm_context_pass':
        args += ['--record-result', 'sentinel.json']
    monkeypatch.setattr(sys, 'argv', args)
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert 'wiki_coordination.py --source-stage' in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('mode', ['', 'v1'])
def test_host_v1_packet_composition_stops_before_policy_or_input_reads(tmp_path, monkeypatch, mode):
    from wiki_core import coordination_context as coordination
    env = {'WIKI_COORDINATION_ALLOWED_CONTEXTS': 'root', 'WIKI_COORDINATION_CONTEXT_MODE': mode}
    binding = coordination.CoordinationBinding.from_environment(env)
    monkeypatch.setattr(coordination, 'load_policy', lambda *a, **k: pytest.fail('v1 policy opened'))
    monkeypatch.setattr(coordination, 'build_packet', lambda *a, **k: pytest.fail('v1 packet built'))
    with pytest.raises(coordination.ProtectedCoordinationError) as error:
        coordination.prepare_packet(tmp_path, binding, {})
    assert error.value.code == 'coordination_v1_retired'
    assert not list(tmp_path.iterdir())
