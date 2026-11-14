"""Synthetic, read-only integration observations; no provider is contacted."""
from pathlib import Path

import pytest

from wiki_core import integration_check as check

HEAD = 'a' * 40
BASE = 'b' * 40


def candidate():
    return {'number': 1, 'url': 'https://example.test/pull/1', 'state': 'OPEN',
            'author': {'login': 'author'}, 'headRefOid': HEAD, 'baseRefOid': BASE,
            'headRefName': 'wiki/one', 'baseRefName': 'main', 'isDraft': False,
            'headRepositoryOwner': {'login': 'owner'}, 'mergeStateStatus': 'CLEAN',
            'statusCheckRollup': [{'conclusion': 'SUCCESS'}], 'reviewDecision': '',
            'reviews': [], 'comments': [{'createdAt': '2026-11-14T10:00:00Z', 'author': {'login': 'independent'}, 'body': f'Head: {HEAD}\nExecutor: agent-a\nReviewer: agent-b\nReview: approved\nReview-Evidence: transcript-1\nResponsible-Thread: thread-1'}]}


def evaluate(pr=None, policy=None, ancestry='current', human=False):
    return check.evaluate(pr or candidate(), policy or {'gate': 'github_pr'}, ancestry=ancestry, human_approved=human)


def test_ready_and_exact_head_review():
    assert evaluate()['status'] == 'integrable'
    pr = candidate()
    pr['comments'][0]['body'] = pr['comments'][0]['body'].replace(HEAD, 'c' * 40)
    assert evaluate(pr)['status'] == 'waiting:exact_head_review'
    pr['comments'][0]['body'] = pr['comments'][0]['body'].replace('c' * 40, HEAD)
    pr['comments'][0]['author'] = {'login': 'author'}
    assert evaluate(pr)['status'] == 'waiting:exact_head_review'


@pytest.mark.parametrize('required,human,expected', [(True, False, 'waiting:human_review_identity'),
                                                       (True, True, 'integrable'),
                                                       (False, False, 'integrable')])
def test_human_policy(required, human, expected):
    result = evaluate(policy={'gate': 'github_pr', 'require_human_review': required}, human=human)
    assert result['status'] == expected


def test_local_gates_need_execution_not_a_comment():
    pr = candidate()
    pr['comments'][0]['body'] += '\nLocal-Gates: passed'
    result = evaluate(pr, {'gate': 'github_pr', 'contribution_validation': 'local_gates'})
    assert result['status'] == 'integrable'
    assert result['required_at_integration'] == ['run_local_gates_on_exact_head']


def test_blockers_and_unknown_adapter():
    assert evaluate(policy={'gate': 'other'})['status'] == 'waiting:policy_adapter'
    assert evaluate(ancestry='outdated')['status'] == 'fix:base_outdated'
    assert evaluate(ancestry='unknown')['status'] == 'waiting:local_git_objects'
    pr = candidate()
    pr['statusCheckRollup'] = [{'conclusion': 'FAILURE'}]
    assert evaluate(pr)['status'] == 'waiting:github_checks'
    pr['isDraft'] = True
    assert evaluate(pr)['status'] == 'waiting:ready_for_review'


def test_closed_requires_identifiable_reason():
    pr = candidate()
    pr['state'] = 'CLOSED'
    assert evaluate(pr)['status'] == 'waiting:verify_closure_reason'
    pr['comments'] = []
    assert evaluate(pr)['status'] == 'fix:closure_reason_missing'
    pr['comments'].append({'body': 'Disposition-Reason: superseded by integrated proposal.'})
    assert evaluate(pr)['status'] == 'done'


def test_inventory_and_cleanup_observations_are_read_only(monkeypatch, tmp_path):
    open_pr = candidate()
    merged = candidate() | {'number': 2, 'state': 'MERGED', 'headRefName': 'wiki/merged'}
    closed = candidate() | {'number': 3, 'state': 'CLOSED', 'headRefName': 'wiki/closed', 'comments': []}
    calls = []
    def gh(root, *args):
        calls.append(args)
        assert args[:2] == ('pr', 'list')
        return [open_pr, merged, closed]
    def git(root, *args):
        calls.append(args)
        if args[:3] == ('ls-remote', '--symref', 'origin'):
            return 'ref: refs/heads/main\tHEAD\n' + BASE + '\tHEAD'
        if args == ('ls-remote', '--heads', 'origin'):
            return f'{BASE}\trefs/heads/main\n{HEAD}\trefs/heads/wiki/one\n{HEAD}\trefs/heads/wiki/remote\n{HEAD}\trefs/heads/wiki/merged'
        assert args[:2] == ('for-each-ref', '--format=%(refname:short)')
        return 'main\nwiki/one\nwiki/local\nwiki/merged'
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', gh)
    monkeypatch.setattr(check, '_git', git)
    monkeypatch.setattr(check, 'policy', lambda root, base: {'gate': 'github_pr'})
    monkeypatch.setattr(check, '_ancestry', lambda *args: 'current')
    monkeypatch.setattr(check, '_worktrees', lambda root: [
        {'path': '/main', 'branch': 'main', 'dirty': False},
        {'path': '/merged', 'branch': 'wiki/merged', 'dirty': False},
        {'path': '/dirty', 'branch': 'wiki/one', 'dirty': True}])
    result = check.inspect(tmp_path)
    assert result['ok']
    assert result['proposals'][1]['status'] == 'fix:merged_branch_or_worktree_remaining'
    assert result['proposals'][2]['status'] == 'fix:closure_reason_missing'
    findings = {(x['status'], x.get('branch')) for x in result['hygiene']}
    assert ('fix:local_branch_without_pr', 'wiki/local') in findings
    assert ('fix:remote_branch_without_pr', 'wiki/remote') in findings
    assert ('fix:merged_worktree_remaining', 'wiki/merged') in findings
    assert ('fix:dirty_worktree', 'wiki/one') in findings
    assert all('fetch' not in call and 'checkout' not in call for call in calls)


def test_human_review_checks_github_type_and_exact_commit(monkeypatch, tmp_path):
    pr = candidate()
    pr['reviews'] = [{'author': {'login': 'human'}, 'state': 'APPROVED', 'commit': {'oid': HEAD}}]
    monkeypatch.setattr(check, '_gh', lambda root, *args: {'type': 'User'})
    assert not check._human_review(tmp_path, 'github.com/owner/repo', pr)
    pr['reviews'][0]['commit']['oid'] = BASE
    assert not check._human_review(tmp_path, 'github.com/owner/repo', pr)


def test_superseded_human_review_is_not_approval(monkeypatch, tmp_path):
    pr = candidate()
    pr['reviews'] = [
        {'author': {'login': 'human'}, 'state': 'APPROVED', 'commit': {'oid': HEAD}},
        {'author': {'login': 'human'}, 'state': 'DISMISSED', 'commit': {'oid': HEAD}},
    ]
    monkeypatch.setattr(check, '_gh', lambda root, *args: {'type': 'User'})
    assert not check._human_review(tmp_path, 'github.com/owner/repo', pr)


def test_blocked_and_simultaneous_waits():
    pr = candidate()
    pr['mergeStateStatus'] = 'BLOCKED'
    pr['reviewDecision'] = 'REVIEW_REQUIRED'
    pr['comments'][0]['author'] = {'login': 'author'}
    result = evaluate(pr, {'gate': 'github_pr', 'contribution_validation': 'local_gates', 'require_human_review': True})
    assert result['status'] != 'integrable'
    assert {'exact_head_review', 'github_mergeability', 'human_review_identity'} <= set(result['pending'])
    assert result['required_at_integration'] == ['run_local_gates_on_exact_head']


def test_missing_worktree_is_individual_wait(monkeypatch, tmp_path):
    monkeypatch.setattr(check, '_git', lambda root, *args: 'worktree /definitely/missing/worktree\nbranch refs/heads/wiki/missing')
    assert check._worktrees(tmp_path)[0]['dirty'] is None


def test_empty_remote_head_is_named_wait(monkeypatch, tmp_path):
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda root, *args: [])
    monkeypatch.setattr(check, '_git', lambda root, *args: '')
    assert check.inspect(tmp_path) == {'ok': False, 'status': 'waiting:default_branch'}


def test_closed_and_merged_hygiene_survive_missing_target_policy(monkeypatch, tmp_path):
    pr = candidate() | {'state': 'MERGED', 'headRefName': 'wiki/merged', 'baseRefName': 'deleted'}
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda root, *args: pr)
    def git(root, *args):
        if args[:3] == ('ls-remote', '--symref', 'origin'):
            return 'ref: refs/heads/main\tHEAD\n' + BASE + '\tHEAD'
        if args == ('ls-remote', '--heads', 'origin'):
            return f'{BASE}\trefs/heads/main\n{HEAD}\trefs/heads/wiki/merged'
        return 'main\nwiki/merged'
    monkeypatch.setattr(check, '_git', git)
    monkeypatch.setattr(check, 'policy', lambda *args: {})
    monkeypatch.setattr(check, '_worktrees', lambda root: [])
    assert check.inspect(tmp_path, 2)['proposals'][0]['status'] == 'waiting:verify_branch_reuse'
    pr['state'] = 'CLOSED'
    pr['comments'] = []
    assert check.inspect(tmp_path, 2)['proposals'][0]['status'] == 'fix:closure_reason_missing'


def test_target_branch_must_match_destination_policy():
    pr = candidate()
    pr['baseRefName'] = 'develop'
    assert evaluate(pr, {'gate': 'github_pr', 'default_branch': 'main'})['status'] == 'fix:wrong_base'
    assert evaluate(pr, {'gate': 'github_pr', 'default_branch': 'develop'})['status'] == 'integrable'


@pytest.mark.parametrize('gates', ['invalid', [[]], [[1]], [['']]])
def test_invalid_local_gates_are_not_integrable(gates):
    result = evaluate(policy={'gate': 'github_pr', 'contribution_validation': 'local_gates', 'contribution_gates': gates})
    assert result['status'] == 'fix:invalid_policy_gates'


def test_detached_worktree_at_merged_head_needs_reconciliation(monkeypatch, tmp_path):
    pr = candidate() | {'number': 2, 'state': 'MERGED', 'headRefName': 'wiki/merged'}
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda root, *args: pr)
    def git(root, *args):
        if args[:3] == ('ls-remote', '--symref', 'origin'):
            return 'ref: refs/heads/main\tHEAD\n' + BASE + '\tHEAD'
        if args == ('ls-remote', '--heads', 'origin'):
            return f'{BASE}\trefs/heads/main'
        return 'main'
    monkeypatch.setattr(check, '_git', git)
    monkeypatch.setattr(check, 'policy', lambda *args: {'gate': 'github_pr'})
    monkeypatch.setattr(check, '_worktrees', lambda root: [{'path': '/detached', 'branch': None, 'head': HEAD, 'dirty': False}])
    assert check.inspect(tmp_path, 2)['proposals'][0]['status'] == 'waiting:verify_detached_worktree'


def test_unsupported_policy_is_detected_before_github(monkeypatch, tmp_path):
    monkeypatch.setattr(check, '_repository', lambda root: 'gitlab.example/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda *args: pytest.fail('unexpected GitHub request'))
    monkeypatch.setattr(check, '_git', lambda root, *args: ('ref: refs/heads/main\tHEAD\n' + BASE + '\tHEAD') if '--symref' in args else (BASE + '\trefs/heads/main'))
    monkeypatch.setattr(check, 'policy', lambda *args: {'gate': 'gitlab_mr'})
    assert check.inspect(tmp_path)['status'] == 'waiting:policy_adapter'


def test_head_changed_between_github_and_remote(monkeypatch, tmp_path):
    pr = candidate()
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda root, *args: pr)
    def git(root, *args):
        if '--symref' in args:
            return 'ref: refs/heads/main\tHEAD\n' + BASE + '\tHEAD'
        if '--heads' in args:
            return BASE + '\trefs/heads/main\n' + 'c' * 40 + '\trefs/heads/wiki/one'
        return 'main'
    monkeypatch.setattr(check, '_git', git)
    monkeypatch.setattr(check, 'policy', lambda *args: {'gate': 'github_pr'})
    monkeypatch.setattr(check, '_worktrees', lambda root: [])
    assert check.inspect(tmp_path, 1)['proposals'][0]['status'] == 'waiting:head_observation'


def test_missing_approval_block_uses_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(check, '_blob', lambda *args: 'repo_id: synthetic\ncontexts: example\n')
    assert check.policy(tmp_path, BASE) == {}
    assert evaluate(policy=check.policy(tmp_path, BASE))['status'] == 'integrable'


def test_later_rejection_blocks_even_with_another_approval():
    pr = candidate()
    pr['comments'].append({'createdAt': '2026-11-14T11:00:00Z', 'author': {'login': 'independent'}, 'body': f'Head: {HEAD}\nReview: rejected'})
    pr['comments'].append({'author': {'login': 'other'}, 'body': f'Head: {HEAD}\nReview: approved'})
    assert evaluate(pr)['status'] == 'fix:conflict_or_changes_requested'


def test_untrusted_thread_text_is_not_forwarded():
    pr = candidate()
    pr['comments'][0]['body'] += '\nResponsible-Thread: \x1b[31munsafe'
    assert 'responsible_thread' not in evaluate(pr)
    assert check._thread_ref('mcp:launch:' + 'a' * 64) == 'mcp:launch:' + 'a' * 64
    assert check._thread_ref('https://example.test/private-token') is None


def test_cli_text_exposes_action_reconciliation(monkeypatch, capsys):
    import importlib
    import sys
    scripts = str(Path(__file__).resolve().parents[1] / 'scripts')
    monkeypatch.syspath_prepend(scripts)
    cli = importlib.import_module('wiki_integration_check')
    monkeypatch.setattr(cli, 'inspect', lambda *args: {'ok': True, 'proposals': [
        {'number': 2, 'status': 'done', 'action_reconciliation': 'unverified'}], 'hygiene': []})
    monkeypatch.setattr(sys, 'argv', ['wiki_integration_check.py'])
    assert cli.main() == 0
    assert 'action reconciliation: unverified' in capsys.readouterr().out


def test_later_native_review_resolves_rejection_but_reverse_blocks():
    pr = candidate()
    pr['comments'][0]['body'] = f'Head: {HEAD}\nReview: rejected'
    pr['reviews'] = [{'author': {'login': 'independent'}, 'state': 'APPROVED', 'commit': {'oid': HEAD},
                      'body': f'Approved {HEAD}', 'submittedAt': '2026-11-14T11:00:00Z'}]
    assert evaluate(pr)['status'] == 'integrable'
    pr['reviews'][0]['submittedAt'] = '2026-11-14T09:00:00Z'
    assert evaluate(pr)['status'] == 'fix:conflict_or_changes_requested'
    pr['reviews'][0]['submittedAt'] = None
    assert evaluate(pr)['status'] == 'waiting:review_event_order'


def test_github_logins_are_case_insensitive():
    pr = candidate()
    pr['author']['login'] = 'Alice'
    pr['comments'][0]['author']['login'] = 'alice'
    assert evaluate(pr)['status'] == 'waiting:exact_head_review'
