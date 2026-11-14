import importlib.util
import json
import subprocess
import sys
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
    observation = {'ok': True, 'hygiene': [
        {'status': 'fix:dirty_worktree', 'path': str(tmp_path)},
        {'status': 'fix:local_branch_without_pr', 'branch': 'wiki/work'},
        {'status': 'fix:action_stale', 'branch': 'wiki/work'},
        {'status': 'fix:merged_branch_remaining', 'branch': 'other'},
    ]}
    monkeypatch.setattr(hook, 'check', lambda *args: observation)
    monkeypatch.setattr(hook, '_current_branch', lambda root: 'wiki/work')
    event = {'hook_event_name': 'Stop', 'stop_hook_active': False}
    observe = hook.handle(event, tmp_path, 'observe', 'running', {'executor'}, 10)
    assert 'decision' not in observe and 'uncommitted_changes' in observe['systemMessage']
    enforced = hook.handle(event, tmp_path, 'enforce', 'running', {'executor'}, 10)
    assert enforced['decision'] == 'block' and 'current_branch_without_proposal' in enforced['reason']
    assert 'action_stale' not in enforced['reason']
    assert 'decision' not in hook.handle(event | {'stop_hook_active': True}, tmp_path, 'enforce', 'running', {'executor'}, 10)
    for state in ('stop', 'unknown'):
        assert 'decision' not in hook.handle(event, tmp_path, 'enforce', state, {'executor'}, 10)
    assert 'decision' not in hook.handle(event | {'stop_requested': True}, tmp_path, 'enforce', 'running', {'executor'}, 10)
    assert 'decision' not in hook.handle(event | {'last_assistant_message': 'STOP requested'}, tmp_path, 'enforce', 'running', {'executor'}, 10)


def test_only_current_merged_worktree_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, 'check', lambda *args: {'ok': True, 'hygiene': [{'status': 'fix:merged_worktree_remaining', 'path': str(tmp_path), 'branch': 'wiki/work'}]})
    monkeypatch.setattr(hook, '_current_branch', lambda root: 'wiki/work')
    result = hook.handle({'hook_event_name': 'Stop'}, tmp_path, 'enforce', 'running', {'executor'}, 10)
    assert result['decision'] == 'block' and 'merged_branch_or_worktree_remaining' in result['reason']


def test_executor_handoff_and_non_executor(tmp_path):
    event = {'hook_event_name': 'SubagentStop', 'agent_type': 'executor', 'last_assistant_message': 'incomplete'}
    assert hook.handle(event, tmp_path, 'observe', 'running', {'executor'}, 10)['decision'] == 'block'
    assert 'decision' not in hook.handle(event | {'stop_hook_active': True}, tmp_path, 'observe', 'running', {'executor'}, 10)
    assert hook.handle(event | {'agent_type': 'reviewer'}, tmp_path, 'enforce', 'running', {'executor'}, 10) == {}
    handoff = f'Proposal: PR 1\nHead: {HEAD}\nBase: {BASE}\nReview: review link\nGates: passed\nPending: none\nResponsible-Thread: thread 1'
    assert hook.handle(event | {'last_assistant_message': handoff}, tmp_path, 'observe', 'running', {'executor'}, 10) == {}


def test_unknown_observation_never_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, 'check', lambda *args: {'ok': False})
    out = hook.handle({'hook_event_name': 'Stop'}, tmp_path, 'enforce', 'running', {'executor'}, 1)
    assert 'decision' not in out


def test_protocol_json_for_both_hosts(tmp_path):
    state = tmp_path / 'state'
    state.write_text('stop')
    for provider in ('Codex', 'Claude'):
        event = {'hook_event_name': 'SubagentStop', 'agent_type': 'executor', 'cwd': str(tmp_path), 'last_assistant_message': 'incomplete', 'provider': provider}
        proc = subprocess.run([sys.executable, str(SCRIPT), '--stop-state-file', str(state)], input=json.dumps(event), capture_output=True, text=True)
        assert proc.returncode == 0 and 'decision' not in json.loads(proc.stdout)
