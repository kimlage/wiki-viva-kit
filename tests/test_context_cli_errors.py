from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = 'SYNTHETIC_PRIVATE_SENTINEL'


def _module(name):
    path = ROOT / 'scripts' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name + '_safe_error_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('script,args', [
    ('wiki_context.py', ['--approved-revision', 'a' * 40, 'resolve', 'root', '--unknown', SENTINEL]),
    ('wiki_context.py', ['--approved-revision', 'a' * 40, SENTINEL]),
    ('wiki_context_flow.py', ['--approved-revision', 'a' * 40, 'impact', '--before', 'a', '--after', 'b', '--context', 'root', '--limit', SENTINEL]),
    ('wiki_context_flow.py', ['--approved-revision', 'a' * 40, 'review', '--candidate', 'a', '--disposition', SENTINEL, '--reason', 'x', '--evidence-revision', 'a']),
    ('wiki_coordination.py', ['--source-stage', SENTINEL]),
    ('wiki_coordination.py', ['--unknown', SENTINEL]),
])
def test_argument_errors_never_echo_values(script, args):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script), *args], capture_output=True, text=True)
    assert result.returncode == 2 and result.stdout == ''
    assert SENTINEL not in result.stderr and 'Traceback' not in result.stderr
    assert 'invalid arguments' in result.stderr and 'usage:' in result.stderr


@pytest.mark.parametrize('script', ['wiki_context.py', 'wiki_context_flow.py', 'wiki_coordination.py'])
def test_cli_help_stays_available(script):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script), '--help'], capture_output=True, text=True)
    assert result.returncode == 0 and 'usage:' in result.stdout


@pytest.mark.parametrize('name,command', [
    ('wiki_context', ['pack', 'root', '--content-revision', 'a', '--request']),
    ('wiki_context_flow', ['requirements', '--result', 'result', '--output', 'out', '--proposal-head', 'a', '--temporal', 'current', '--max-age-days', '1', '--packet']),
])
@pytest.mark.parametrize('kind', ['missing', 'invalid_json'])
def test_context_input_failures_do_not_echo_path_or_content(tmp_path, monkeypatch, capsys, name, command, kind):
    module = _module(name)
    selected = tmp_path / SENTINEL
    if kind == 'invalid_json':
        selected.write_text(SENTINEL)
    monkeypatch.setattr(module, 'load_policy', lambda *_a, **_k: SimpleNamespace())
    monkeypatch.setattr(sys, 'argv', [name, '--repo', str(tmp_path), '--approved-revision', 'a' * 40, *command, str(selected)])
    assert module.main() == 1
    result = capsys.readouterr()
    assert result.out == '' and SENTINEL not in result.err and 'Traceback' not in result.err
    assert 'context operation unavailable' in result.err


@pytest.mark.parametrize('name,command', [
    ('wiki_context', ['resolve', 'root']),
    ('wiki_context_flow', ['revalidate', '--consumer', 'synthetic', '--context', 'root']),
])
def test_context_domain_error_is_exactly_whitelisted(tmp_path, monkeypatch, capsys, name, command):
    module = _module(name)
    monkeypatch.setattr(sys, 'argv', [name, '--repo', str(tmp_path), '--approved-revision', 'a' * 40, *command])
    def unavailable(*_a, **_k):
        raise module.PolicyError('coordination host binding required')
    monkeypatch.setattr(module, 'load_policy', unavailable)
    assert module.main() == 1
    assert capsys.readouterr().err.strip() == 'coordination host binding required'
    def sensitive(*_a, **_k):
        raise module.PolicyError('unavailable: ' + SENTINEL)
    monkeypatch.setattr(module, 'load_policy', sensitive)
    assert module.main() == 1
    result = capsys.readouterr()
    assert SENTINEL not in result.err and 'context operation unavailable' in result.err


def test_coordination_missing_event_input_is_opaque(tmp_path):
    args = ['--root', str(tmp_path), '--profile', 'synthetic', '--action-id', 'a', '--action-path', 'a.md',
            '--expected-sha256', 'a' * 64, '--event-file', str(tmp_path / SENTINEL)]
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/wiki_coordination.py'), *args], capture_output=True, text=True)
    assert result.returncode == 2 and result.stdout == ''
    assert 'event input unavailable' in result.stderr and SENTINEL not in result.stderr
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize('name,command', [
    ('wiki_context', ['resolve', 'root']),
    ('wiki_context_flow', ['revalidate', '--consumer', 'synthetic', '--context', 'root']),
])
@pytest.mark.parametrize('error_type', [FileNotFoundError, PermissionError, KeyError, RecursionError])
def test_context_exception_values_do_not_reach_stderr(tmp_path, monkeypatch, capsys, name, command, error_type):
    module = _module(name)
    monkeypatch.setattr(sys, 'argv', [name, '--repo', str(tmp_path), '--approved-revision', 'a' * 40, *command])
    def fail(*_a, **_k):
        raise error_type(SENTINEL)
    monkeypatch.setattr(module, 'load_policy', fail)
    assert module.main() == 1
    result = capsys.readouterr()
    assert result.out == '' and SENTINEL not in result.err and 'Traceback' not in result.err
    assert 'context operation unavailable' in result.err
