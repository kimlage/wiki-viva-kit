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


def test_merged_worktree_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, 'check', lambda *args: {'ok': True, 'hygiene': [{'status': 'fix:merged_worktree_remaining', 'path': str(tmp_path), 'branch': 'wiki/work'}]})
    monkeypatch.setattr(hook, '_current_branch', lambda root: 'wiki/work')
    result = hook.handle({'hook_event_name': 'Stop', 'stop_hook_active': False}, tmp_path, 'enforce', 'running', {'executor'}, 10)
    assert result['decision'] == 'block' and 'merged_branch_or_worktree_remaining' in result['reason']


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
    observation = {'ok': True, 'hygiene': [{'status': 'fix:dirty_worktree', 'path': str(tmp_path.resolve())}]}
    assert hook.mechanical_findings(observation, hook._repository_root(nested), 'wiki/work') == ['uncommitted_changes']


def test_stop_state_is_rechecked_after_observation(monkeypatch, tmp_path):
    state = tmp_path / 'stop-state'
    state.write_text(json.dumps({'session_id': 'test-session', 'state': 'running'}))
    def delayed_check(*args):
        state.write_text(json.dumps({'session_id': 'test-session', 'state': 'stop'}))
        return {'ok': True, 'hygiene': [{'status': 'fix:dirty_worktree', 'path': str(tmp_path)}]}
    monkeypatch.setattr(hook, 'check', delayed_check)
    monkeypatch.setattr(hook, '_current_branch', lambda root: 'wiki/work')
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
    monkeypatch.setattr(hook, '_current_branch', lambda root: 'wiki/work')
    for event in ({'hook_event_name': 'Stop'}, {'hook_event_name': 'Stop', 'stop_hook_active': 'false'},
                  {'hook_event_name': 'SubagentStop', 'agent_type': 'executor', 'last_assistant_message': 'incomplete'}):
        assert 'decision' not in hook.handle(event, tmp_path, 'enforce', 'running', {'executor'}, 10)


def test_failed_gate_cannot_have_no_pending_items():
    msg = f'Proposal: PR 1 repo=owner/repo target=main\nHead: {HEAD}\nBase: {BASE}\nReview: https://example.test/review {HEAD}\nGates: tests=failed\nPending: none\nResponsible-Thread: thread:sample'
    assert not hook.complete_handoff(msg)
    assert hook.complete_handoff(msg.replace('Pending: none', 'Pending: repair failed tests'))


def test_merged_residue_in_another_worktree_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, 'check', lambda *args: {'ok': True, 'hygiene': [{'status': 'fix:merged_worktree_remaining', 'path': '/other', 'branch': 'wiki/merged'}]})
    monkeypatch.setattr(hook, '_current_branch', lambda root: 'wiki/current')
    result = hook.handle({'hook_event_name': 'Stop', 'stop_hook_active': False}, tmp_path, 'enforce', 'running', {'executor'}, 10)
    assert result['decision'] == 'block' and 'merged_branch_or_worktree_remaining' in result['reason']


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
