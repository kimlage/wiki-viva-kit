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


@pytest.mark.parametrize('error_class,message', [
    ('IntegrationError', 'approved base moved'),
    ('IntegrationError', 'branch head changed'),
    ('IntegrationError', 'result changes do not match branch'),
    ('PolicyError', 'policy revision is not current trusted approval ref'),
    ('ImpactError', 'cross-context folder authority requires requalification'),
    ('PolicyError', 'complete packet exceeds byte budget'),
    ('PolicyError', 'secret detected in packet input'),
])
def test_actionable_domain_errors_are_exact_class_and_message(capsys, error_class, message):
    from wiki_core.cli_errors import report_context_error
    from wiki_core.context_policy import PolicyError
    from wiki_core.context_integration import IntegrationError
    from wiki_core.context_impact import ImpactError
    types = {'PolicyError': PolicyError, 'IntegrationError': IntegrationError, 'ImpactError': ImpactError}
    report_context_error(types[error_class](message))
    assert capsys.readouterr().err.strip() == message
    report_context_error(ValueError(message))
    assert capsys.readouterr().err.strip() == 'context operation unavailable'


def test_coordination_deep_source_stage_json_returns_opaque_blocker(tmp_path):
    import os
    env = {key: value for key, value in os.environ.items() if not key.startswith('WIKI_COORDINATION_')}
    args = ['--root', str(tmp_path), '--source-stage', 'prepare', '--context-id', 'root', '--approved-revision', 'a' * 40]
    deep = '[' * 5000 + '0' + ']' * 5000
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/wiki_coordination.py'), *args],
                            input=deep, capture_output=True, text=True, env=env)
    assert result.returncode == 1 and 'Traceback' not in result.stderr
    assert 'coordination_invalid_request' in result.stdout


def test_coordination_transition_failure_reports_uncertain_state(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    module = _module('wiki_coordination')
    event = tmp_path / 'event.json'
    event.write_text('{"coordinator":"synthetic"}')
    args = ['--root', str(tmp_path), '--profile', 'synthetic', '--action-id', 'a', '--action-path', SENTINEL,
            '--expected-sha256', 'a' * 64, '--event-file', str(event)]
    monkeypatch.setattr(sys, 'argv', ['wiki_coordination.py', *args])
    def failure(*_a, **_k):
        raise ValueError('synthetic failure with ' + SENTINEL)
    monkeypatch.setattr(module, 'transition_dialogue_action', failure)
    with pytest.raises(ValueError) as internal:
        module.main()
    assert type(internal.value) is ValueError and SENTINEL in str(internal.value)
    with pytest.raises(SystemExit) as error:
        module._run_cli()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert SENTINEL not in captured.err and 'Traceback' not in captured.err
    assert 'inspect action state before retry' in captured.err


def test_coordination_read_failure_does_not_echo_path(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    module = _module('wiki_coordination')
    monkeypatch.setattr(sys, 'argv', ['wiki_coordination.py', '--root', str(tmp_path)])
    def failure(*_a, **_k):
        raise OSError(SENTINEL)
    monkeypatch.setattr(module, 'load_config', failure)
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert SENTINEL not in captured.err and 'coordination read unavailable' in captured.err


def test_coordination_fifo_event_does_not_wait_where_nonblocking_exists(tmp_path):
    import os
    if not hasattr(os, 'mkfifo') or not hasattr(os, 'O_NONBLOCK'):
        pytest.skip('FIFO or nonblocking open unavailable')
    event = tmp_path / 'event.fifo'
    os.mkfifo(event)
    args = ['--root', str(tmp_path), '--profile', 'synthetic', '--action-id', 'a', '--action-path', 'a.md',
            '--expected-sha256', 'a' * 64, '--event-file', str(event)]
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/wiki_coordination.py'), *args],
                            capture_output=True, text=True, timeout=3)
    assert result.returncode == 2 and 'event input unavailable' in result.stderr
    assert 'Traceback' not in result.stderr


def test_coordination_deep_packet_request_returns_opaque_blocker(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    module = _module('wiki_coordination')
    request = tmp_path / SENTINEL
    request.write_text('[' * 5000 + '0' + ']' * 5000)
    monkeypatch.setattr(module.CoordinationBinding, 'from_environment', classmethod(lambda cls: None))
    monkeypatch.setattr(module, '_policy', lambda *_a, **_k: None)
    monkeypatch.setattr(sys, 'argv', ['wiki_coordination.py', '--root', str(tmp_path), '--context-id', 'root',
        '--approved-revision', 'a' * 40, '--packet-request', str(request)])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert 'coordination_invalid_request' in captured.out
    assert SENTINEL not in captured.out + captured.err and 'Traceback' not in captured.err


def test_dialogue_event_growth_is_bounded(tmp_path, monkeypatch):
    import os
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    module = _module('wiki_coordination')
    event = tmp_path / 'event.json'
    event.write_text('{}')
    original = os.fstat
    calls = 0
    def grow_after_metadata(fd):
        nonlocal calls
        info = original(fd)
        calls += 1
        if calls == 2:
            event.write_bytes(b' ' * 16_001)
        return info
    monkeypatch.setattr(os, 'fstat', grow_after_metadata)
    with pytest.raises(ValueError, match='event file exceeds limit'):
        module._read_dialogue_event(event)


@pytest.mark.parametrize('script,args', [
    ('wiki_context.py', ['--repo', '{loop}', '--approved-revision', 'a' * 40, 'resolve', 'root']),
    ('wiki_context_flow.py', ['--repo', '{loop}', '--approved-revision', 'a' * 40, 'revalidate', '--consumer', 'x', '--context', 'root']),
    ('wiki_coordination.py', ['--root', '{loop}', '--show-host-binding']),
    ('wiki_coordination.py', ['--root', '{loop}', '--source-stage', 'prepare', '--context-id', 'root', '--approved-revision', 'a' * 40]),
    ('wiki_coordination.py', ['--root', '{loop}', '--context-id', 'root', '--approved-revision', 'a' * 40, '--packet-request', 'synthetic.json']),
])
def test_cyclic_root_errors_do_not_expose_selected_path(tmp_path, script, args):
    import os
    loop = tmp_path / SENTINEL
    loop.symlink_to(loop.name)
    env = {key: value for key, value in os.environ.items() if not key.startswith('WIKI_COORDINATION_')}
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script),
                             *(str(loop) if arg == '{loop}' else arg for arg in args)],
                            input='{}', text=True, capture_output=True, env=env)
    assert result.returncode != 0 and 'Traceback' not in result.stderr
    assert SENTINEL not in result.stdout + result.stderr


def test_coordination_direct_caller_keeps_structured_transition_error(tmp_path, monkeypatch, capsys):
    from wiki_core.action_transition import ActionTransitionError
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    module = _module('wiki_coordination')
    event = tmp_path / 'event.json'
    event.write_text('{"coordinator":"synthetic"}')
    args = ['--root', str(tmp_path), '--profile', 'synthetic', '--action-id', 'a', '--action-path', 'a.md',
            '--expected-sha256', 'a' * 64, '--event-file', str(event)]
    monkeypatch.setattr(sys, 'argv', ['wiki_coordination.py', *args])
    original = ActionTransitionError(code='synthetic_stale', current_state='pending')
    def fail(*_a, **_k):
        raise original
    monkeypatch.setattr(module, 'transition_dialogue_action', fail)
    with pytest.raises(ActionTransitionError) as error:
        module.main()
    assert error.value is original and error.value.to_dict()['error_code'] == 'synthetic_stale'
    with pytest.raises(SystemExit) as cli_error:
        module._run_cli()
    assert cli_error.value.code == 1
    captured = capsys.readouterr()
    assert 'synthetic_stale' not in captured.err and 'inspect action state before retry' in captured.err
