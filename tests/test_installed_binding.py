"""Synthetic separate-code/content operator binding; no private sources."""
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest
from wiki_core.config import WikiConfig
from wiki_core.web import installed_binding as binding
from wiki_core.web import commands, gates, ingestion_plan, source_operations


@pytest.fixture
def content(tmp_path, monkeypatch):
    monkeypatch.setattr(binding, '_binding', None)
    monkeypatch.setattr(binding, '_legacy_sealed', False)
    root = (tmp_path / 'content').resolve()
    root.mkdir()
    (root / 'wiki.config.yaml').write_text('repo_id: synthetic\n')
    (root / 'scripts').mkdir()
    (root / 'scripts/wiki_pr_summary.py').write_text("raise RuntimeError('content script executed')\n")
    (root / 'scripts/wiki_input_stage.py').write_text("raise RuntimeError('content script executed')\n")
    (root / 'wiki_core').mkdir()
    (root / 'wiki_core/__init__.py').write_text("raise RuntimeError('content package executed')\n")
    (root / 'yaml.py').write_text("raise RuntimeError('content module executed')\n")
    binding.configure(root)
    yield root


def test_fixed_code_and_content_outputs_are_distinct(content):
    result = commands.run_action(content, WikiConfig(repo_id='synthetic'), 'pr-summary', dry_run=False)
    assert result['ok'] and '# Wiki PR Summary' in result['results'][0]['stdout']
    release_target = binding._CODE_ROOT / 'memories/system/input-stage.md'
    before = release_target.read_bytes() if release_target.exists() else None
    argv, env = binding.command(content, ['python3', 'scripts/wiki_input_stage.py', '--write'])
    assert argv[:2] == [sys.executable, '-I'] and env['WIKI_INSTALLED_CONTENT_ROOT'] == str(content)
    proc = subprocess.run(argv, cwd=content, env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert (content / 'memories/system/input-stage.md').is_file()
    assert (content / 'data/derived/wiki/input-stage/input-catalog.json').is_file()
    assert (release_target.read_bytes() if release_target.exists() else None) == before


@pytest.mark.parametrize('name', sorted(binding._SCRIPTS))
def test_all_bound_entrypoints_import_installed_code(content, name):
    argv, env = binding.command(content, ['python3', f'scripts/{name}', '--help'])
    proc = subprocess.run(argv, cwd=content, env=env, capture_output=True, text=True, timeout=30)
    assert 'content module executed' not in proc.stderr and 'content package executed' not in proc.stderr
    assert proc.returncode == 0, (name, proc.stderr)


def test_root_binding_is_singleton_and_rejects_invalid_paths(content, tmp_path):
    binding.configure(content)  # same identity is idempotent
    other = (tmp_path / 'other').resolve(); other.mkdir()
    with pytest.raises(ValueError, match='already_configured'):
        binding.configure(other)
    with pytest.raises(ValueError, match='root_changed'):
        binding.command(other, ['python3', 'scripts/wiki_audit.py'])
    with pytest.raises(ValueError, match='not_allowlisted'):
        binding.command(content, ['python3', 'scripts/../evil.py'])
    with pytest.raises(ValueError, match='installed_content_override_forbidden'):
        binding.command(content, ['python3', 'scripts/wiki_ingest.py', '--root', str(other)])
    with pytest.raises(ValueError, match='installed_command_not_allowlisted'):
        binding.command(content, ['sh', '-c', 'true'])
    link = tmp_path / 'link'; link.symlink_to(content, target_is_directory=True)
    with pytest.raises(ValueError, match='root_invalid'):
        binding.configure(link.absolute())


def test_replaced_root_and_changed_code_fail_closed(content, tmp_path, monkeypatch):
    original = binding._code_digest
    monkeypatch.setattr(binding, '_code_digest', lambda code: 'different')
    with pytest.raises(ValueError, match='code_changed'):
        binding.command(content, ['python3', 'scripts/wiki_audit.py'])
    monkeypatch.setattr(binding, '_code_digest', original)
    content.rename(tmp_path / 'old-content'); content.mkdir()
    with pytest.raises(ValueError, match='root_changed'):
        binding.command(content, ['python3', 'scripts/wiki_audit.py'])


def test_gate_and_ingestion_dispatch_use_binding(content, monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout='ok', stderr='')
    monkeypatch.setattr(gates.subprocess, 'run', run)
    monkeypatch.setattr(gates, 'write_receipt', lambda *a, **k: {'finished_at': 'synthetic'})
    assert gates.run_gate(content, WikiConfig(repo_id='synthetic'), 'wiki_audit')['ok']
    assert calls[-1][0][1] == '-I' and calls[-1][1]['cwd'] == content
    plan = {'ok': True, 'stages': [{'id': 'proposal_preview', 'status': 'ready', 'label': 'preview', 'command': ['python3', 'scripts/wiki_new_ingest.py', '--dry-run']} ]}
    monkeypatch.setattr(ingestion_plan, 'build_ingestion_plan', lambda *a, **k: plan)
    result = ingestion_plan.run_ingestion_step(content, WikiConfig(repo_id='synthetic'), 'source', 'system', 'proposal_preview')
    assert result['ok'] and calls[-1][0][1] == '-I' and calls[-1][1]['cwd'] == content


def test_unqualified_adapters_and_contribution_are_refused(content):
    from wiki_core.action_contribution import ContributionError, _gates
    for call in (
        lambda: source_operations._safe_refresh_argv(content, ('python3','scripts/private.py'), source_id='s', locator='x', config_ref='x'),
        lambda: source_operations._safe_ingest_argv(content, ('python3','scripts/private.py'), content/'raw.txt'),
        lambda: source_operations._run_refresh_adapter(['python3','scripts/private.py'], root=content),
    ):
        with pytest.raises(ValueError, match='installed_consumer_adapter_unavailable'):
            call()
    with pytest.raises(ContributionError, match='installed_contribution_gates_unavailable'):
        _gates(content, WikiConfig(repo_id='synthetic'))


def test_indirect_jobs_and_contribution_stop_before_effects(content):
    from wiki_core.action_contribution import run_contribution
    from wiki_core.web.source_review_jobs import run_source_job, submit_source_jobs
    runner = Mock()
    runner.root = content
    runner._source_review_authorities = {'synthetic-job': object()}
    runner._set_status.return_value = {'status': 'failed'}
    result = run_source_job(runner, {'job_id': 'synthetic-job'})
    assert result == {'status': 'failed'}
    assert runner._set_status.call_args.kwargs['reason'] == 'installed_consumer_adapter_unavailable'
    assert not runner._source_review_authorities
    with pytest.raises(ValueError, match='installed_consumer_adapter_unavailable'):
        submit_source_jobs(runner, {}, manager=Mock(), token='x', session_id='x')
    response = run_contribution(content, WikiConfig(repo_id='synthetic'), 'prepare_contribution', {}, dry_run=False)
    assert not response['ok'] and response['error'] == 'installed_contribution_gates_unavailable'


def test_observer_refuses_without_dispatch(content, monkeypatch):
    from wiki_core import answer_observation
    monkeypatch.setattr(answer_observation, '_capture', lambda *a, **k: ({'task_ref': {}}, {'answer_observer': {'argv': ['python3', 'scripts/private.py']}}, 'policy'))
    invoked = Mock(side_effect=AssertionError('observer executed'))
    monkeypatch.setattr(answer_observation.subprocess, 'run', invoked)
    result = answer_observation.observe_canonical_answer(content, 'action.md', 'event-0001', {}, active_policy_sha256='policy')
    assert result['status'] == 'refused' and result['error'] == 'installed_observer_unavailable'
    assert result['answer_committed'] is True and not invoked.called


def test_external_builder_is_not_implicitly_qualified(content):
    from wiki_core.web.vercel_preview import _build_frontend
    with pytest.raises(ValueError, match='installed_external_build_unavailable'):
        _build_frontend(content, 'head')


def test_server_separates_code_content_and_frontend(content, tmp_path, monkeypatch):
    from wiki_core.web import server
    bundle = (tmp_path / 'frontend').resolve(); bundle.mkdir(); (bundle / 'index.html').write_text('synthetic')
    fake = Mock(); monkeypatch.setattr(server, 'CockpitServer', lambda *a, **k: fake)
    server.serve(content, frontend=bundle, installed_code=True)
    assert fake.frontend_dir == bundle and binding._binding[0] != content != bundle
    assert fake.serve_forever.call_count == 1
    nested = content / "bundle"; nested.mkdir(); (nested / "index.html").write_text("synthetic")
    with pytest.raises(ValueError, match="installed_frontend_not_distinct"):
        server.serve(content, frontend=nested, installed_code=True)
    link = tmp_path / "frontend-link"; link.symlink_to(bundle, target_is_directory=True)
    with pytest.raises(ValueError, match="installed_frontend_invalid"):
        server.serve(content, frontend=link, installed_code=True)


def test_real_code_change_and_symlink_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(binding, '_binding', None)
    monkeypatch.setattr(binding, '_legacy_sealed', False)
    code = (tmp_path / 'release').resolve(); content = (tmp_path / 'content').resolve()
    (code / 'wiki_core').mkdir(parents=True); (code / 'scripts').mkdir(); content.mkdir()
    (code / 'wiki_core/mod.py').write_text('VALUE = 1\n')
    prompt = code / 'wiki_core/prompt.md'; prompt.write_text('before')
    schemas = code / 'docs/references/schemas'; schemas.mkdir(parents=True)
    schema = schemas / 'fixture.json'; schema.write_text('{}')
    script = code / 'scripts/wiki_audit.py'; script.write_text('print(1)\n')
    monkeypatch.setattr(binding, '_CODE_ROOT', code)
    monkeypatch.setattr(binding, '_SCRIPTS', frozenset({'wiki_audit.py'}))
    binding.configure(content)
    for path, changed, original in ((script, 'print(2)\n', 'print(1)\n'), (prompt, 'after', 'before'), (schema, '{\"x\":1}', '{}')):
        path.write_text(changed)
        with pytest.raises(ValueError, match='installed_code_changed'):
            binding.command(content, ['python3', 'scripts/wiki_audit.py'])
        path.write_text(original)
    monkeypatch.setattr(binding, '_binding', None)
    script.unlink(); script.symlink_to(code / 'wiki_core/mod.py')
    with pytest.raises(ValueError, match='installed_code_symlink'):
        binding.configure(content)


def test_concurrent_configuration_cannot_replace_binding(tmp_path, monkeypatch):
    import concurrent.futures
    import threading
    monkeypatch.setattr(binding, '_binding', None)
    monkeypatch.setattr(binding, '_legacy_sealed', False)
    roots = [(tmp_path / name).resolve() for name in ('one', 'two')]
    for root in roots:
        root.mkdir()
    barrier = threading.Barrier(2)
    def start(root):
        barrier.wait()
        try:
            binding.configure(root)
            return 'ok'
        except ValueError as exc:
            return str(exc)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(start, roots))
    assert sorted(outcomes) == ['installed_binding_already_configured', 'ok']
    assert binding._binding[1] in roots


def test_binding_failure_writes_no_gate_receipt(content, monkeypatch):
    receipt = Mock(side_effect=AssertionError("receipt should not be written"))
    monkeypatch.setattr(gates, "write_receipt", receipt)
    monkeypatch.setattr(binding, "command", Mock(side_effect=ValueError("installed_code_changed")))
    result = gates.run_gate(content, WikiConfig(repo_id="synthetic"), "wiki_audit")
    assert not result["ok"] and result["stderr"] == "installed_code_changed"
    assert not receipt.called


def test_legacy_start_cannot_switch_into_installed_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(binding, '_binding', None)
    monkeypatch.setattr(binding, '_legacy_sealed', False)
    content = (tmp_path / 'content').resolve(); content.mkdir()
    binding.seal_legacy()
    with pytest.raises(ValueError, match='installed_mode_after_legacy_start'):
        binding.configure(content)


@pytest.fixture
def copied_release(tmp_path, monkeypatch):
    import shutil
    monkeypatch.setattr(binding, '_binding', None)
    monkeypatch.setattr(binding, '_legacy_sealed', False)
    release = (tmp_path / 'release').resolve(); release.mkdir()
    source = binding._CODE_ROOT
    for directory in ('wiki_core', 'scripts', 'docs/references/schemas'):
        shutil.copytree(source / directory, release / directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    content = (tmp_path / 'content').resolve(); content.mkdir()
    (content / 'wiki.config.yaml').write_text('repo_id: synthetic\n')
    monkeypatch.setattr(binding, '_CODE_ROOT', release)
    return release, content


def test_child_restores_exact_binding_and_refuses_adapter(copied_release):
    release, content = copied_release
    script = release / 'scripts/wiki_pr_summary.py'
    script.write_text('''from pathlib import Path
from wiki_core.web import installed_binding as b
from wiki_core.web.source_operations import _safe_ingest_argv
from scripts._common import ROOT
assert b.enabled() and b.active(ROOT)
try:
    _safe_ingest_argv(ROOT, ('python3','scripts/private.py'), ROOT/'raw')
except ValueError as e:
    assert str(e) == 'installed_consumer_adapter_unavailable'
else:
    raise AssertionError('adapter was not blocked')
try:
    b.command(ROOT, ['python3','scripts/private.py'])
except ValueError as e:
    assert str(e) == 'installed_script_not_allowlisted'
else:
    raise AssertionError('content script was not blocked')
print('child-binding-restored')
''')
    binding.configure(content)
    argv, env = binding.command(content, ['python3', 'scripts/wiki_pr_summary.py'])
    result = subprocess.run(argv, cwd=content, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'child-binding-restored'


@pytest.mark.parametrize('swap', ['root', 'code', 'guard'])
def test_child_rejects_swap_after_command_preparation(copied_release, tmp_path, swap):
    release, content = copied_release
    script = release / 'scripts/wiki_pr_summary.py'
    script.write_text("from pathlib import Path\nPath('entrypoint-ran').write_text('bad')\n")
    binding.configure(content)
    argv, env = binding.command(content, ['python3', 'scripts/wiki_pr_summary.py'])
    if swap == 'root':
        content.rename(tmp_path / 'original-content'); content.mkdir()
    elif swap == 'code':
        (release / 'wiki_core' / 'changed.py').write_text('VALUE = 2\n')
    else:
        (release / 'wiki_core/web/installed_binding.py').write_text("from pathlib import Path; Path('guard-ran').write_text('bad')\n")
    result = subprocess.run(argv, cwd=content, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'installed_child_binding_mismatch' in result.stderr
    assert not (content / 'entrypoint-ran').exists()
    assert not (content / 'guard-ran').exists()


def test_installed_job_runner_never_autostarts_or_admits(content):
    from wiki_core.web.codex_jobs import JobRunner
    from wiki_core.web.server import CockpitServer
    cfg = WikiConfig(repo_id='synthetic')
    with pytest.raises(ValueError, match='installed_job_runner_unavailable'):
        JobRunner(content, cfg, autostart=True)
    runner = JobRunner(content, cfg, autostart=False, reconcile_retained=False)
    with pytest.raises(ValueError, match='installed_job_runner_unavailable'):
        runner.start()
    assert runner.submit(brief_id='x', brief_sha='x')['error'] == 'installed_job_runner_unavailable'
    assert runner.run_job('x')['error'] == 'installed_job_runner_unavailable'
    enabled = WikiConfig(repo_id='synthetic', codex={'enabled': True})
    with pytest.raises(ValueError, match='installed_job_runner_unavailable'):
        CockpitServer(('127.0.0.1', 0), content, enabled)


def test_installed_pytest_is_unavailable_without_overwriting_legacy_receipt(content, monkeypatch):
    config = WikiConfig(repo_id='synthetic')
    for gate_id, _ in gates.GATE_COMMANDS:
        gates.write_receipt(content, config, gate_id, ok=True, returncode=0)
    history = gates._receipts_dir(content, config) / 'pytest.json'
    original = history.read_bytes()
    payload = gates.gates_payload(content, config)
    pytest_gate = next(g for g in payload['gates'] if g['id'] == 'pytest')
    assert pytest_gate['status'] == 'not_run' and pytest_gate['available'] is False
    assert pytest_gate['unavailable_reason'] == 'installed_gate_unavailable' and pytest_gate['finished_at'] is None
    assert payload['status'] == 'partial' and history.read_bytes() == original
    command = Mock(side_effect=AssertionError('dispatch attempted'))
    run = Mock(side_effect=AssertionError('subprocess attempted'))
    writer = Mock(side_effect=AssertionError('receipt written'))
    monkeypatch.setattr(binding, 'command', command)
    monkeypatch.setattr(gates.subprocess, 'run', run)
    monkeypatch.setattr(gates, 'write_receipt', writer)
    result = gates.run_gate(content, config, 'pytest')
    assert result['error'] == 'installed_gate_unavailable' and not result['ok']
    assert not command.called and not run.called and not writer.called and history.read_bytes() == original


def test_pytest_gate_legacy_mode_retains_old_receipt_and_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(binding, '_binding', None)
    monkeypatch.setattr(binding, '_legacy_sealed', False)
    config = WikiConfig(repo_id='synthetic')
    gates.write_receipt(tmp_path, config, 'pytest', ok=True, returncode=0)
    gate = next(g for g in gates.gates_payload(tmp_path, config)['gates'] if g['id'] == 'pytest')
    assert gate['status'] == 'pass' and 'available' not in gate
    called = Mock(return_value=subprocess.CompletedProcess(['python3'], 0, stdout='ok', stderr=''))
    monkeypatch.setattr(gates.subprocess, 'run', called)
    result = gates.run_gate(tmp_path, config, 'pytest')
    assert result['ok'] and called.call_args.args[0] == ['python3', '-m', 'pytest', 'tests/']
