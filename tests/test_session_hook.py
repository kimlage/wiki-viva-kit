import importlib.util
import json
import subprocess
import sys
import pytest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/wiki_session_hook.py'
spec = importlib.util.spec_from_file_location('wiki_session_hook', SCRIPT)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)
HEAD = 'a' * 40
BASE = 'b' * 40


def test_session_start_injects_bounded_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, 'check', lambda *args: {'ok': True, 'proposals': [{'status': 'waiting:checks'}, {'status': 'integrable'}], 'hygiene': [{'status': 'fix:dirty_worktree'}]})
    output = hook.handle({'hook_event_name': 'SessionStart'}, tmp_path, 'observe', 'unknown', {'executor'}, 10)
    assert output['hookSpecificOutput']['additionalContext'] == 'Integration observations: fix=1, integrable=1, waiting=1'


def test_stop_observe_and_bounded_enforce(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, 'check', lambda *args: pytest.fail('Stop must not access network'))
    monkeypatch.setattr(hook, '_worktree_dirty', lambda root: True)
    event = {'hook_event_name': 'Stop', 'stop_hook_active': False}
    observe = hook.handle(event, tmp_path, 'observe', 'running', {'executor'}, 10)
    assert 'decision' not in observe and 'uncommitted_changes' in observe['systemMessage']
    enforced = hook.handle(event, tmp_path, 'enforce', 'running', {'executor'}, 10)
    assert enforced['decision'] == 'block' and 'uncommitted_changes' in enforced['reason']
    assert 'decision' not in hook.handle(event | {'stop_hook_active': True}, tmp_path, 'enforce', 'running', {'executor'}, 10)
    for state in ('stop', 'unknown'):
        assert 'decision' not in hook.handle(event, tmp_path, 'enforce', state, {'executor'}, 10)
    assert 'decision' not in hook.handle(event | {'stop_requested': True}, tmp_path, 'enforce', 'running', {'executor'}, 10)
    assert 'decision' not in hook.handle(event | {'last_assistant_message': 'STOP requested'}, tmp_path, 'enforce', 'running', {'executor'}, 10)


def test_executor_handoff_and_non_executor(tmp_path):
    event = {'hook_event_name': 'SubagentStop', 'agent_type': 'executor', 'last_assistant_message': 'incomplete', 'stop_hook_active': False}
    result = hook.handle(event, tmp_path, 'observe', 'running', {'executor'}, 10)
    assert 'decision' not in result and 'proposal' in result['systemMessage']
    assert 'decision' not in hook.handle(event | {'stop_hook_active': True}, tmp_path, 'observe', 'running', {'executor'}, 10)
    assert hook.handle(event | {'agent_type': 'reviewer'}, tmp_path, 'enforce', 'running', {'executor'}, 10) == {}
    handoff = f'Proposal: PR 1 repo=owner/repo target=main\nHead: {HEAD}\nBase: {BASE}\nReview: https://example.test/review {HEAD}\nGates: pytest=passed\nPending: none\nResponsible-Thread: thread:sample'
    assert hook.handle(event | {'last_assistant_message': handoff}, tmp_path, 'observe', 'running', {'executor'}, 10) == {}


def test_unknown_observation_never_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, 'check', lambda *args: {'ok': False})
    out = hook.handle({'hook_event_name': 'Stop', 'stop_hook_active': False}, tmp_path, 'enforce', 'running', {'executor'}, 1)
    assert 'decision' not in out


def test_protocol_json_for_both_hosts(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    state = tmp_path / 'state'
    state.write_text(json.dumps({'session_id': 'test-session', 'state': 'stop'}))
    for provider in ('Codex', 'Claude'):
        event = {'hook_event_name': 'SubagentStop', 'agent_type': 'executor', 'cwd': str(tmp_path), 'last_assistant_message': 'incomplete', 'provider': provider, 'session_id': 'test-session'}
        proc = subprocess.run([sys.executable, str(SCRIPT), '--stop-state-file', str(state)], input=json.dumps(event), capture_output=True, text=True)
        assert proc.returncode == 0 and 'decision' not in json.loads(proc.stdout)


def test_subdirectory_resolves_actual_repository_root(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    nested = tmp_path / 'nested'
    nested.mkdir()
    assert hook._repository_root(nested) == tmp_path.resolve()
    (nested / 'new.txt').write_text('synthetic')
    assert hook._worktree_dirty(hook._repository_root(nested)) is True


def test_stop_state_is_rechecked_after_observation(monkeypatch, tmp_path):
    state = tmp_path / 'stop-state'
    state.write_text(json.dumps({'session_id': 'test-session', 'state': 'running'}))
    def dirty(root):
        state.write_text(json.dumps({'session_id': 'test-session', 'state': 'stop'}))
        return True
    monkeypatch.setattr(hook, '_worktree_dirty', dirty)
    result = hook.handle({'hook_event_name': 'Stop', 'stop_hook_active': False}, tmp_path, 'enforce', lambda: hook._stop_state(state, 'test-session'), {'executor'}, 10)
    assert 'decision' not in result


def test_placeholder_handoff_is_incomplete():
    message = f'Proposal: none\nHead: {"0" * 40}\nBase: {"0" * 40}\nReview: unknown\nGates: unknown\nPending: unknown\nResponsible-Thread: unknown'
    assert not hook.complete_handoff(message)


def test_hook_accepts_filled_canonical_brief():
    brief = (SCRIPT.parents[1] / 'docs/references/templates/wiki/subagent-brief.md').read_text()
    replacements = {
        '<PR URL or PR number with repo=owner/repo, then target=branch>': 'PR #123 repo=owner/repo target=main',
        '<full final head SHA>': HEAD, '<full base SHA>': BASE,
        '<independent review reference and full head SHA>': 'https://example.test/review ' + HEAD,
        '<gate=passed, gate=pending>': 'pytest=passed', '<items and wait events, or none>': 'none',
        '<executor thread reference>': 'thread:sample',
    }
    for old, new in replacements.items():
        brief = brief.replace(old, new)
    assert hook.complete_handoff(brief)


def test_handoff_rejects_unnamed_gates_and_unbound_review():
    message = f'Proposal: PR 1 repo=owner/repo target=main\nHead: {HEAD}\nBase: {BASE}\nReview: https://example.test/review {HEAD}\nGates: not passed\nPending: none\nResponsible-Thread: thread:sample'
    assert not hook.complete_handoff(message)
    assert not hook.complete_handoff(message.replace('Gates: not passed', 'Gates: tests=passed').replace('review ' + HEAD, 'review'))


def test_handoff_rejects_partial_sha():
    short = 'a' * 41
    message = f'Proposal: PR 1 repo=owner/repo target=main\nHead: {short}\nBase: {BASE}\nReview: https://example.test/review {short}\nGates: pytest=passed\nPending: none\nResponsible-Thread: thread:sample'
    assert not hook.complete_handoff(message)


def test_stop_state_requires_fresh_matching_session(tmp_path):
    import os
    state = tmp_path / 'state'
    state.write_text(json.dumps({'session_id': 'session-one', 'state': 'running'}))
    assert hook._stop_state(state, 'session-one') == 'running'
    assert hook._stop_state(state, 'session-two') == 'unknown'
    os.utime(state, (1, 1))
    assert hook._stop_state(state, 'session-one') == 'unknown'


def test_offline_still_detects_local_dirty_worktree(monkeypatch, tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'new.txt').write_text('synthetic')
    monkeypatch.setattr(hook, 'check', lambda *args: {'ok': False})
    result = hook.handle({'hook_event_name': 'Stop', 'stop_hook_active': False}, tmp_path, 'enforce', 'running', {'executor'}, 10)
    assert result['decision'] == 'block' and 'uncommitted_changes' in result['reason']


def test_missing_attempt_state_never_continues(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, 'check', lambda *args: {'ok': True, 'hygiene': [{'status': 'fix:dirty_worktree', 'path': str(tmp_path)}]})
    for event in ({'hook_event_name': 'Stop'}, {'hook_event_name': 'Stop', 'stop_hook_active': 'false'},
                  {'hook_event_name': 'SubagentStop', 'agent_type': 'executor', 'last_assistant_message': 'incomplete'}):
        assert 'decision' not in hook.handle(event, tmp_path, 'enforce', 'running', {'executor'}, 10)


def test_failed_gate_cannot_have_no_pending_items():
    msg = f'Proposal: PR 1 repo=owner/repo target=main\nHead: {HEAD}\nBase: {BASE}\nReview: https://example.test/review {HEAD}\nGates: tests=failed\nPending: none\nResponsible-Thread: thread:sample'
    assert not hook.complete_handoff(msg)
    assert hook.complete_handoff(msg.replace('Pending: none', 'Pending: repair failed tests'))


def test_handoff_requires_destination_repository_and_branch():
    msg = f'Proposal: PR 1\nHead: {HEAD}\nBase: {BASE}\nReview: https://example.test/review {HEAD}\nGates: tests=passed\nPending: none\nResponsible-Thread: thread:sample'
    assert not hook.complete_handoff(msg)
    assert not hook.complete_handoff(msg.replace('Proposal: PR 1', 'Proposal: PR 1 repo=owner/repo'))
    assert hook.complete_handoff(msg.replace('Proposal: PR 1', 'Proposal: PR 1 repo=owner/repo target=main'))


def test_subagent_stop_always_observes_and_names_missing_fields(tmp_path):
    message = f'Proposal: PR 1 repo=owner/repo target=main\nHead: {HEAD}'
    for state in ('running', 'stop', 'unknown'):
        for mode in ('observe', 'enforce'):
            out = hook.handle({'hook_event_name': 'SubagentStop', 'agent_type': 'executor',
                               'stop_hook_active': False, 'last_assistant_message': message},
                              tmp_path, mode, state, {'executor'}, 10)
            assert 'decision' not in out
            assert 'base' in out['systemMessage'] and 'review' in out['systemMessage']
            assert 'proposal' not in out['systemMessage'] and 'head' not in out['systemMessage']


def _process_running(pid):
    import os
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return bool(ok and code.value == 259)
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip()) and not result.stdout.strip().startswith('Z')


def test_timeout_kills_worker_and_sleeping_descendant(tmp_path):
    import time
    pidfile = tmp_path / 'child.pid'
    source = tmp_path / 'spawn.py'
    source.write_text('import pathlib, subprocess, sys, time\n'
                      'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
                      'pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n'
                      'time.sleep(60)\n')
    started = time.monotonic()
    assert hook._run_group([sys.executable, str(source), str(pidfile)], '', 1) is None
    assert time.monotonic() - started < 3
    assert pidfile.exists()
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 2
    while _process_running(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _process_running(pid)


def test_success_still_cleans_up_detached_stdio_descendant(tmp_path):
    import time
    pidfile = tmp_path / 'child.pid'
    source = tmp_path / 'spawn_exit.py'
    source.write_text('import pathlib, subprocess, sys\n'
                      'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n'
                      'pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n'
                      'print("ok")\n')
    assert hook._run_group([sys.executable, str(source), str(pidfile)], '', 3).strip() == 'ok'
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 2
    while _process_running(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _process_running(pid)


def test_event_deadline_covers_unfinished_stdin():
    import time
    started = time.monotonic()
    proc = subprocess.Popen([sys.executable, str(SCRIPT), '--timeout', '0.3'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert proc.wait(timeout=3) == 0
        assert time.monotonic() - started < 2
        assert 'timed out' in json.loads(proc.stdout.read())['systemMessage']
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdin.close()
        proc.stdout.close()
        proc.stderr.close()
