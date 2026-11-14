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
            'reviews': [], 'comments': [{'author': {'login': 'independent'}, 'body': f'Head: {HEAD}\nExecutor: agent-a\nReviewer: agent-b\nReview: approved\nReview-Evidence: transcript-1\nResponsible-Thread: thread-1'}]}


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
    assert evaluate(pr, {'gate': 'github_pr', 'contribution_validation': 'local_gates'})['status'] == 'waiting:local_gates_at_integration'


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
            return f'{BASE}\trefs/heads/main\n{HEAD}\trefs/heads/wiki/remote\n{HEAD}\trefs/heads/wiki/merged'
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
    assert {'exact_head_review', 'github_mergeability', 'human_review_identity', 'local_gates_at_integration'} <= set(result['pending'])


def test_missing_worktree_is_individual_wait(monkeypatch, tmp_path):
    monkeypatch.setattr(check, '_git', lambda root, *args: 'worktree /definitely/missing/worktree\nbranch refs/heads/wiki/missing')
    assert check._worktrees(tmp_path)[0]['dirty'] is None
