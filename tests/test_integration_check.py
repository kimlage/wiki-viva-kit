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
            'headRepositoryOwner': {'login': 'owner'}, 'isCrossRepository': False, 'mergeStateStatus': 'CLEAN',
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
    assert evaluate(pr)['status'] == 'done'
    def scoped():
        return check.evaluate(pr, {}, ancestry='unknown', human_approved=False, closure_reason_required=True)
    assert scoped()['status'] == 'waiting:verify_closure_reason'
    pr['comments'] = []
    assert scoped()['status'] == 'fix:closure_reason_missing'
    pr['comments'].append({'body': 'Disposition-Reason: superseded by integrated proposal.'})
    assert scoped()['status'] == 'done'


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
        assert args[:2] == ('for-each-ref', '--format=%(refname:short)%09%(objectname)')
        return f'main\t{BASE}\nwiki/one\t{HEAD}\nwiki/local\t{HEAD}\nwiki/merged\t{HEAD}'
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
    assert result['proposals'][2]['status'] == 'done'
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
    assert 'action reconciliation:' in capsys.readouterr().out


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


def test_native_review_order_is_temporal_not_array_order():
    pr = candidate()
    pr['comments'] = []
    def review(state, time):
        return {'author': {'login': 'Reviewer'}, 'state': state, 'commit': {'oid': HEAD},
                'body': f'{state} {HEAD}', 'submittedAt': time}
    old = review('APPROVED', '2026-11-14T10:00:00Z')
    new = review('CHANGES_REQUESTED', '2026-11-14T11:00:00Z')
    new['author']['login'] = 'reviewer'
    pr['reviews'] = [new, old]
    assert evaluate(pr)['status'] == 'fix:conflict_or_changes_requested'
    pr['reviews'] = [old, new]
    assert evaluate(pr)['status'] == 'fix:conflict_or_changes_requested'
    old['submittedAt'] = '2026-11-14T12:00:00Z'
    assert evaluate(pr)['status'] == 'integrable'


def test_native_change_request_blocks_without_sha_in_body():
    pr = candidate()
    pr['reviews'] = [{'author': {'login': 'another'}, 'state': 'CHANGES_REQUESTED',
                      'commit': {'oid': HEAD}, 'body': 'Blocking defect',
                      'submittedAt': '2026-11-14T11:00:00Z'}]
    assert evaluate(pr)['status'] == 'fix:conflict_or_changes_requested'


def test_host_behind_disagreement_waits():
    pr = candidate()
    pr['mergeStateStatus'] = 'BEHIND'
    assert evaluate(pr)['status'] == 'waiting:github_mergeability'


def test_cross_repository_same_owner_and_sha_is_not_origin_branch(monkeypatch, tmp_path):
    pr = candidate() | {'isCrossRepository': True}
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda root, *args: pr)
    def git(root, *args):
        if '--symref' in args:
            return 'ref: refs/heads/main\tHEAD\n' + BASE + '\tHEAD'
        if '--heads' in args:
            return BASE + '\trefs/heads/main\n' + HEAD + '\trefs/heads/wiki/one'
        return 'main'
    monkeypatch.setattr(check, '_git', git)
    monkeypatch.setattr(check, 'policy', lambda *args: {'gate': 'github_pr'})
    monkeypatch.setattr(check, '_worktrees', lambda root: [])
    assert check.inspect(tmp_path, 1)['proposals'][0]['status'] == 'waiting:head_observation'


def test_linked_action_stale_current_terminal_and_indeterminate():
    pr = candidate() | {'state': 'MERGED', 'mergedAt': '2026-11-14T12:00:00Z'}
    fm = {'page_type': 'action', 'page_id': 'action-demo', 'action_state': 'open',
          'updated_at': '2026-11-13', 'next_action': 'Acompanhar PR #1', 'owner': 'team-owner'}
    stale = check._action_observation(fm, '', pr, 'github.com/owner/repo')
    assert stale == {'status': 'fix:action_stale', 'action_id': 'action-demo', 'pr': 1,
                     'responsible': 'team-owner', 'event': 'proposal_closed_after_action'}
    fm['updated_at'] = '2026-11-16'
    assert check._action_observation(fm, '', pr, 'github.com/owner/repo')['status'] == 'current'
    fm['updated_at'] = '2026-11-14'
    assert check._action_observation(fm, '', pr, 'github.com/owner/repo')['status'] == 'current'
    fm['action_state_history'] = [{'at': '2026-11-14T13:00:00Z'}]
    assert check._action_observation(fm, '', pr, 'github.com/owner/repo')['status'] == 'current'
    fm['action_state'] = 'done'
    assert check._action_observation(fm, '', pr, 'github.com/owner/repo')['status'] == 'terminal'


def test_action_reference_in_body_and_evidence():
    pr = candidate() | {'state': 'CLOSED', 'closedAt': '2026-11-14T12:00:00Z'}
    fm = {'page_type': 'action', 'page_id': 'a', 'action_state': 'open', 'updated_at': '2026-11-10'}
    assert check._action_observation(fm, 'Track https://github.com/owner/repo/pull/1', pr, 'github.com/owner/repo')['status'] == 'fix:action_stale'
    assert check._action_observation(fm, 'Track https://github.com/elsewhere/repo/pull/1', pr, 'github.com/owner/repo') is None
    fm['evidence_refs'] = ['PR #1']
    assert check._action_observation(fm, '', pr, 'github.com/owner/repo')['status'] == 'fix:action_stale'


def test_short_number_collision_does_not_associate_a_different_repository():
    pr = candidate() | {'number': 502, 'state': 'MERGED', 'mergedAt': '2026-11-14T12:00:00Z'}
    fm = {'page_type': 'action', 'page_id': 'action-demo', 'action_state': 'open',
          'updated_at': '2026-11-10', 'next_action': 'Acompanhar PR #502', 'evidence_refs': [502]}
    body = 'Kit: https://github.com/example-org/public-kit/pull/502'
    assert check._action_observation(fm, body, pr, 'github.com/example-org/private-wiki') is None
    assert check._action_observation(fm, body, pr, 'github.com/example-org/public-kit')['status'] == 'fix:action_stale'
    body += '\nPrivate: https://github.com/example-org/private-wiki/pull/502'
    assert check._action_observation(fm, body, pr, 'github.com/example-org/private-wiki')['status'] == 'fix:action_stale'
    assert check._action_reference('example-org/public-kit#502 and #502', 502, 'github.com/example-org/private-wiki') is False
    assert check._action_reference('github.com/example-org/public-kit#502 and #502', 502, 'github.com/example-org/private-wiki') is False
    assert check._action_reference('https://github.com/example-org/public-kit/issues/502 and PR #502', 502, 'github.com/example-org/private-wiki') is False
    assert check._action_reference('https://git.example/elsewhere/repo/pull/502 and PR #502', 502, 'github.com/owner/repo') is False
    assert check._action_reference('github.com/example-org/public-kit/pull/502 e PR #502', 502, 'github.com/example-org/private-wiki') is False
    assert check._action_reference('https://git.example/group/repo/-/merge_requests/502 and PR #502', 502, 'github.com/owner/repo') is False
    assert check._action_reference('https://gitlab.com/elsewhere/project#502 and PR #502', 502, 'github.com/owner/repo') is False
    assert check._action_reference('https://bitbucket.org/elsewhere/project/pull-requests/502 and PR #502', 502, 'github.com/owner/repo') is False
    assert check._action_reference('See https://docs.example/guide/details#502 and PR #502', 502, 'github.com/owner/repo') is True
    assert check._action_reference('PR #502 (docs/README.md)', 502, 'github.com/owner/repo') is True
    assert check._action_reference('PR #502 (scripts/wiki_action.py)', 502, 'github.com/owner/repo') is True
    assert check._action_reference('PR #502 (docs/README)', 502, 'github.com/owner/repo') is None
    assert check._action_reference('PR #502 (memories/actions)', 502, 'github.com/owner/repo') is None
    assert check._action_reference('PR #502 (docs/README.md#502)', 502, 'github.com/owner/repo') is True
    assert check._action_reference('PR #502 [doc](docs/README#502)', 502, 'github.com/owner/repo') is None
    assert check._action_reference('PR #502\n\nRepo: other/repo\nPR: #503', 502, 'github.com/owner/repo') is True
    assert check._action_reference('PR #502 local; repo=other/repo PR #503', 502, 'github.com/owner/repo') is True
    assert check._action_reference('PR #502; PR #503 (other/repo)', 502, 'github.com/owner/repo') is True
    assert check._action_reference('https://github.com/example/foreign\nPR #502', 502, 'github.com/example/local') is False
    assert check._action_reference('https://github.com/example/foreign.git\nPR #502', 502, 'github.com/example/local') is False
    assert check._action_reference('github.com/example/foreign\nPR #502', 502, 'github.com/example/local') is False
    assert check._action_reference('example/foreign\nPR #502', 502, 'github.com/example/local') is False
    assert check._action_reference('git@gitlab.com:example/repo.git PR #502', 502, 'github.com/example/repo') is False
    assert check._action_reference('git@gitlab.com:example/repo.git\nPR #502', 502, 'github.com/example/repo') is False
    assert check._action_reference('git@github.com:example/repo.git PR #502', 502, 'github.com/example/repo') is True
    assert check._action_reference('https://github.com/example-org/public-kit.git PR #502', 502, 'github.com/example-org/private-wiki') is False
    assert check._action_reference('repo=example-org/public-kit.git PR #502', 502, 'github.com/example-org/public-kit') is True
    assert check._action_reference('PR: 502', 502, 'github.com/owner/repo') is True
    assert check._action_reference('#502', 502, 'github.com/example-org/private-wiki') is True
    assert check._action_reference('PR #502suffix', 502, 'github.com/example-org/private-wiki') is False


def test_ambiguous_extensionless_path_produces_a_named_wait():
    pr = candidate() | {'number': 502, 'state': 'MERGED', 'mergedAt': '2026-11-14T12:00:00Z'}
    fm = {'page_type': 'action', 'page_id': 'a', 'action_state': 'open', 'updated_at': '2026-11-10'}
    result = check._action_observation(fm, 'PR #502 (docs/README)', pr, 'github.com/owner/repo')
    assert result['status'] == 'waiting:action_reconciliation'
    assert result['event'] == 'repository_reference_ambiguous'


@pytest.mark.parametrize('path', ['tools/README', 'bin/check', 'examples/demo', 'assets/icons'])
def test_other_common_extensionless_paths_are_indeterminate(path):
    assert check._action_reference(f'PR #502 ({path})', 502, 'github.com/example/repo') is None


@pytest.mark.parametrize('field', ['next_action', 'body', 'evidence_refs'])
def test_plain_numeric_reference_respects_explicit_repository(field):
    pr = candidate() | {'number': 502, 'state': 'MERGED', 'mergedAt': '2026-11-14T12:00:00Z'}
    fm = {'page_type': 'action', 'page_id': 'a', 'action_state': 'open', 'updated_at': '2026-11-10'}
    body = 'Repo: example-org/public-kit'
    if field == 'body':
        body = '502'
        fm['evidence_refs'] = ['Repo: example-org/public-kit']
    elif field == 'evidence_refs':
        fm[field] = [502]
    else:
        fm[field] = '502'
    assert check._action_observation(fm, body, pr, 'github.com/example-org/private-wiki') is None
    assert check._action_observation(fm, body, pr, 'github.com/example-org/public-kit')['status'] == 'fix:action_stale'


def test_plain_number_is_not_bound_to_different_explicit_pr_number():
    pr = candidate() | {'number': 502, 'state': 'MERGED', 'mergedAt': '2026-11-14T12:00:00Z'}
    fm = {'page_type': 'action', 'page_id': 'a', 'action_state': 'open', 'updated_at': '2026-11-10',
          'next_action': '502'}
    result = check._action_observation(fm, 'Repo: other/repo\nPR: #503', pr, 'github.com/owner/repo')
    assert result['status'] == 'fix:action_stale'


@pytest.mark.parametrize('citation', [
    'repo=example-org/public-kit PR #502',
    'repo=github.com/example-org/public-kit PR #502',
    'example-org/public-kit PR #502',
    'example-org/public-kit (#502)',
    'example-org/public-kit #502',
    'PR #502 (example-org/public-kit)',
    'PR #502, repo: example-org/public-kit',
    'PR #502 da public-kit (example-org/public-kit)',
    'Repo: example-org/public-kit\nPR: #502',
    'Repo: example-org/public-kit\nPR: 502',
    'Repo: https://github.com/example-org/public-kit\nPR: #502',
    'Repo: git@github.com:example-org/public-kit.git\nPR #502',
    'Repo: example-org/public-kit\nPR: #503\nPR: #502',
    'Repo: example-org/public-kit\n\nPR: #502',
    'repo=example-org/public-kit PR: 502',
    'PR #502 em example-org/public-kit',
    'PR #502 do repo=example-org/public-kit',
])
@pytest.mark.parametrize('field', ['next_action', 'body', 'evidence_refs'])
def test_separate_repository_and_number_are_bound(citation, field):
    pr = candidate() | {'number': 502, 'state': 'MERGED', 'mergedAt': '2026-11-14T12:00:00Z'}
    fm = {'page_type': 'action', 'page_id': 'a', 'action_state': 'open', 'updated_at': '2026-11-10'}
    body = ''
    if field == 'body':
        body = citation
    else:
        fm[field] = [citation] if field == 'evidence_refs' else citation
    assert check._action_observation(fm, body, pr, 'github.com/example-org/private-wiki') is None
    assert check._action_observation(fm, body, pr, 'github.com/example-org/public-kit')['status'] == 'fix:action_stale'


@pytest.mark.parametrize('state,timestamp', [('MERGED', 'mergedAt'), ('CLOSED', 'closedAt')])
def test_date_only_action_same_or_later_date_is_current(state, timestamp):
    pr = candidate() | {'state': state, timestamp: '2026-11-14T02:00:00Z'}
    fm = {'page_type': 'action', 'page_id': 'a', 'action_state': 'open', 'next_action': 'PR #1'}
    for updated in ('2026-11-14', '2026-11-15'):
        fm['updated_at'] = updated
        assert check._action_observation(fm, '', pr, 'github.com/owner/repo')['status'] == 'current'
    fm['updated_at'] = '2026-11-13'
    assert check._action_observation(fm, '', pr, 'github.com/owner/repo')['status'] == 'waiting:action_reconciliation'


@pytest.mark.parametrize('cutoff,closed,residue,expected', [
    (None, '2020-01-01T12:00:00Z', False, 'out_of_scope'),
    ('2026-01-01', '2025-12-31T12:00:00Z', False, 'out_of_scope'),
    ('2026-01-01', '2026-01-01T12:00:00Z', False, 'out_of_scope'),
    ('2026-01-01', '2026-01-02T12:00:00Z', False, 'required'),
    (None, '2020-01-01T12:00:00Z', True, 'required'),
    ('invalid', '2026-01-02T12:00:00Z', False, 'waiting:closure_reason_policy'),
    ('2026-01-01', None, False, 'waiting:closure_time'),
])
def test_closure_reason_cutoff_and_residue(cutoff, closed, residue, expected):
    approval = {} if cutoff is None else {'closure_reason_after': cutoff}
    assert check._closure_reason_scope({'closedAt': closed}, approval, residue=residue) == expected


def test_closed_proposals_require_reason_only_in_scope(monkeypatch, tmp_path):
    old = candidate() | {'number': 1, 'state': 'CLOSED', 'closedAt': '2020-01-01T12:00:00Z',
                         'headRefName': 'old', 'comments': []}
    residual = candidate() | {'number': 2, 'state': 'CLOSED', 'closedAt': '2020-01-01T12:00:00Z',
                              'headRefName': 'retained', 'comments': [{'body': 'discussion'}]}
    recent = candidate() | {'number': 3, 'state': 'CLOSED', 'closedAt': '2026-11-14T12:00:00Z',
                            'headRefName': 'recent', 'comments': []}
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda root, *args: [old, residual, recent])
    def git(root, *args):
        if '--symref' in args:
            return f'ref: refs/heads/main\tHEAD\n{BASE}\tHEAD'
        if '--heads' in args:
            return f'{BASE}\trefs/heads/main\n{HEAD}\trefs/heads/retained'
        return 'main'
    monkeypatch.setattr(check, '_git', git)
    monkeypatch.setattr(check, 'policy', lambda *args: {'closure_reason_after': '2026-01-01'})
    monkeypatch.setattr(check, '_worktrees', lambda root: [])
    monkeypatch.setattr(check, '_action_findings', lambda *args: ([], True))
    proposals = check.inspect(tmp_path)['proposals']
    assert [item['status'] for item in proposals] == ['done', 'waiting:verify_closure_reason', 'fix:closure_reason_missing']


def test_closed_main_worktree_same_sha_is_not_residue_and_merged_is_not_closed_unmerged(monkeypatch, tmp_path):
    closed = candidate() | {'state': 'CLOSED', 'headRefName': 'gone', 'comments': [],
                            'closedAt': '2020-01-01T12:00:00Z'}
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda root, *args: closed)
    def git(root, *args):
        if '--symref' in args:
            return f'ref: refs/heads/main\tHEAD\n{BASE}\tHEAD'
        if '--heads' in args:
            return f'{BASE}\trefs/heads/main'
        return 'main'
    monkeypatch.setattr(check, '_git', git)
    monkeypatch.setattr(check, 'policy', lambda *args: {})
    monkeypatch.setattr(check, '_worktrees', lambda root: [{'path': '/main', 'branch': 'main', 'head': HEAD, 'dirty': False}])
    monkeypatch.setattr(check, '_action_findings', lambda *args: ([], True))
    assert check.inspect(tmp_path, 1)['proposals'][0]['status'] == 'done'
    closed['mergedAt'] = '2020-01-01T12:00:00Z'
    monkeypatch.setattr(check, '_worktrees', lambda root: [{'path': '/detached', 'branch': None, 'head': HEAD, 'dirty': False}])
    assert check.inspect(tmp_path, 1)['proposals'][0]['status'] == 'done'


def test_reused_branch_on_different_open_head_is_not_closed_pr_residue(monkeypatch, tmp_path):
    new_head = 'c' * 40
    closed = candidate() | {'state': 'CLOSED', 'headRefName': 'wiki/reused', 'comments': [{'body': 'old discussion'}]}
    opened = candidate() | {'number': 2, 'headRefName': 'wiki/reused', 'headRefOid': new_head}
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda root, *args: [closed, opened])
    def git(root, *args):
        if '--symref' in args:
            return f'ref: refs/heads/main\tHEAD\n{BASE}\tHEAD'
        if '--heads' in args:
            return f'{BASE}\trefs/heads/main\n{new_head}\trefs/heads/wiki/reused'
        return f'main\t{BASE}\nwiki/reused\t{new_head}'
    monkeypatch.setattr(check, '_git', git)
    monkeypatch.setattr(check, 'policy', lambda *args: {})
    monkeypatch.setattr(check, '_ancestry', lambda *args: 'current')
    monkeypatch.setattr(check, '_worktrees', lambda root: [{'path': '/wt', 'branch': 'wiki/reused', 'head': new_head, 'dirty': False}])
    monkeypatch.setattr(check, '_action_findings', lambda *args: ([], True))
    assert check.inspect(tmp_path)['proposals'][0]['status'] == 'done'


@pytest.mark.parametrize('head', [HEAD, None])
def test_closed_branch_changed_or_unobservable_needs_reconciliation(monkeypatch, tmp_path, head):
    changed = 'c' * 40
    closed = candidate() | {'state': 'CLOSED', 'headRefName': 'wiki/closed', 'headRefOid': head,
                            'comments': [{'body': 'discussion'}]}
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda root, *args: closed if 'view' in args else [closed])
    def git(root, *args):
        if '--symref' in args:
            return f'ref: refs/heads/main\tHEAD\n{BASE}\tHEAD'
        if '--heads' in args:
            return f'{BASE}\trefs/heads/main\n{changed}\trefs/heads/wiki/closed'
        return f'main\t{BASE}\nwiki/closed\t{changed}'
    monkeypatch.setattr(check, '_git', git)
    monkeypatch.setattr(check, 'policy', lambda *args: {})
    monkeypatch.setattr(check, '_worktrees', lambda root: [])
    monkeypatch.setattr(check, '_action_findings', lambda *args: ([], True))
    assert check.inspect(tmp_path)['proposals'][0]['status'] == 'waiting:verify_closure_reason'
    assert check.inspect(tmp_path, 1)['proposals'][0]['status'] == 'waiting:verify_branch_reuse'


def test_closed_branch_with_unknown_repository_owner_waits(monkeypatch, tmp_path):
    closed = candidate() | {'state': 'CLOSED', 'headRefName': 'wiki/closed', 'headRepositoryOwner': None,
                            'isCrossRepository': None, 'comments': []}
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda root, *args: [closed])
    def git(root, *args):
        if '--symref' in args:
            return f'ref: refs/heads/main\tHEAD\n{BASE}\tHEAD'
        if '--heads' in args:
            return f'{BASE}\trefs/heads/main\n{HEAD}\trefs/heads/wiki/closed'
        return f'main\t{BASE}\nwiki/closed\t{HEAD}'
    monkeypatch.setattr(check, '_git', git)
    monkeypatch.setattr(check, 'policy', lambda *args: {})
    monkeypatch.setattr(check, '_worktrees', lambda root: [])
    monkeypatch.setattr(check, '_action_findings', lambda *args: ([], True))
    assert check.inspect(tmp_path)['proposals'][0]['status'] == 'waiting:head_repository'


def test_closure_cutoff_uses_target_branch_policy(monkeypatch, tmp_path):
    target = 'c' * 40
    closed = candidate() | {'state': 'CLOSED', 'baseRefName': 'develop', 'headRefName': 'gone',
                            'closedAt': '2026-11-14T12:00:00Z', 'comments': []}
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda root, *args: closed)
    def git(root, *args):
        if '--symref' in args:
            return f'ref: refs/heads/main\tHEAD\n{BASE}\tHEAD'
        if '--heads' in args:
            return f'{BASE}\trefs/heads/main\n{target}\trefs/heads/develop'
        return f'main\t{BASE}'
    monkeypatch.setattr(check, '_git', git)
    monkeypatch.setattr(check, 'policy', lambda root, sha: {'closure_reason_after': '2026-01-01'} if sha == target else {})
    monkeypatch.setattr(check, '_worktrees', lambda root: [])
    monkeypatch.setattr(check, '_action_findings', lambda *args: ([], True))
    assert check.inspect(tmp_path, 1)['proposals'][0]['status'] == 'fix:closure_reason_missing'
    monkeypatch.setattr(check, 'policy', lambda root, sha: None if sha == target else {})
    assert check.inspect(tmp_path, 1)['proposals'][0]['status'] == 'waiting:destination_policy'


def test_action_findings_read_canonical_git_blobs(monkeypatch, tmp_path):
    pr = candidate() | {'state': 'MERGED', 'mergedAt': '2026-11-14T12:00:00Z'}
    blobs = {
        'wiki.config.yaml': 'repo_id: synthetic\ncontexts: example\n',
        'memories/example/actions/demo.md': '---\npage_id: action-demo\npage_type: action\naction_state: open\nupdated_at: 2026-11-13\nnext_action: "PR #1"\n---\nBody\n',
    }
    monkeypatch.setattr(check, '_blob', lambda root, rev, path: blobs[path])
    monkeypatch.setattr(check, '_git', lambda root, *args: 'memories/example/actions/demo.md\x00')
    findings, available = check._action_findings(tmp_path, BASE, [pr], 'github.com/owner/repo')
    assert available and findings[0]['status'] == 'fix:action_stale'
    assert findings[0]['action_id'] == 'action-demo'


def test_last_receipt_alone_and_timezone_date_ambiguity():
    pr = candidate() | {'state': 'MERGED', 'mergedAt': '2026-11-14T02:00:00Z'}
    fm = {'page_type': 'action', 'page_id': 'action-demo', 'action_state': 'open',
          'next_action': 'PR #1', 'action_state_history': [{'at': '2026-11-13T01:00:00Z'}]}
    assert check._action_observation(fm, '', pr, 'github.com/owner/repo')['status'] == 'fix:action_stale'
    fm['updated_at'] = '2026-11-13'
    assert check._action_observation(fm, '', pr, 'github.com/owner/repo')['status'] == 'waiting:action_reconciliation'


def test_numeric_reference_and_unreadable_last_receipt():
    pr = candidate() | {'state': 'MERGED', 'mergedAt': '2026-11-14T12:00:00Z'}
    fm = {'page_type': 'action', 'page_id': 'a', 'action_state': 'open',
          'updated_at': '2026-11-10', 'evidence_refs': [1]}
    assert check._action_observation(fm, '', pr, 'github.com/owner/repo')['status'] == 'fix:action_stale'
    fm['action_state_history'] = [{'at': 'invalid'}]
    assert check._action_observation(fm, '', pr, 'github.com/owner/repo')['status'] == 'waiting:action_reconciliation'


def test_yaml_datetime_receipt_is_observed():
    fm, body = check.parse_frontmatter('---\npage_id: action-a\npage_type: action\naction_state: open\nnext_action: "PR #1"\naction_state_history:\n  - at: 2026-11-12T10:00:00Z\n---\n')
    pr = candidate() | {'state': 'MERGED', 'mergedAt': '2026-11-14T12:00:00Z'}
    assert check._action_observation(fm, body, pr, 'github.com/owner/repo')['status'] == 'fix:action_stale'


@pytest.mark.parametrize('body', ['Proposta 1', 'Pull request 1', '1'])
def test_explicit_proposal_number_in_body(body):
    pr = candidate() | {'state': 'MERGED', 'mergedAt': '2026-11-14T12:00:00Z'}
    fm = {'page_type': 'action', 'page_id': 'a', 'action_state': 'open', 'updated_at': '2026-11-10'}
    assert check._action_observation(fm, body, pr, 'github.com/owner/repo')['status'] == 'fix:action_stale'


def test_ci_failure_is_reported_for_each_open_pr_not_only_ready(monkeypatch, tmp_path):
    failed = candidate() | {'number': 10, 'isDraft': True, 'comments': [],
                            'statusCheckRollup': [{'__typename': 'CheckRun', 'name': 'audit-and-test',
                                                   'status': 'COMPLETED', 'conclusion': 'FAILURE'}]}
    green = candidate() | {'number': 11, 'headRefName': 'wiki/green',
                           'statusCheckRollup': [{'__typename': 'CheckRun', 'name': 'tests',
                                                  'status': 'COMPLETED', 'conclusion': 'SUCCESS'}]}
    pending = candidate() | {'number': 12, 'headRefName': 'wiki/pending',
                             'statusCheckRollup': [{'__typename': 'CheckRun', 'name': 'build',
                                                    'status': 'IN_PROGRESS', 'conclusion': None}]}
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda root, *args: [failed, green, pending])
    def git(root, *args):
        if '--symref' in args:
            return 'ref: refs/heads/main\tHEAD\n' + BASE + '\tHEAD'
        if '--heads' in args:
            return f'{BASE}\trefs/heads/main\n{HEAD}\trefs/heads/wiki/one\n{HEAD}\trefs/heads/wiki/green\n{HEAD}\trefs/heads/wiki/pending'
        return 'main'
    monkeypatch.setattr(check, '_git', git)
    monkeypatch.setattr(check, 'policy', lambda *args: {'gate': 'github_pr'})
    monkeypatch.setattr(check, '_ancestry', lambda *args: 'current')
    monkeypatch.setattr(check, '_worktrees', lambda root: [])
    monkeypatch.setattr(check, '_action_findings', lambda *args: ([], True))
    proposals = check.inspect(tmp_path)['proposals']
    assert proposals[0]['status'] == 'fix:ci_failed'
    assert proposals[0]['ci_failed_checks'] == ['audit-and-test']
    assert proposals[1]['status'] != 'fix:ci_failed'
    assert proposals[2]['status'] != 'fix:ci_failed'


def test_completed_ci_failures_and_status_contexts():
    pr = candidate() | {'statusCheckRollup': [
        {'__typename': 'CheckRun', 'name': 'tests', 'status': 'COMPLETED', 'conclusion': 'FAILURE'},
        {'__typename': 'StatusContext', 'context': 'external-ci', 'state': 'ERROR'},
        {'__typename': 'CheckRun', 'name': 'running', 'status': 'IN_PROGRESS', 'conclusion': None},
        {'__typename': 'CheckRun', 'name': 'successful', 'status': 'COMPLETED', 'conclusion': 'SUCCESS'},
    ]}
    result = evaluate(pr, ancestry='unknown')
    assert result['status'] == 'fix:ci_failed'
    assert result['ci_failed_checks'] == ['tests', 'external-ci']
    assert result['head'] == HEAD


def test_ci_failure_names_are_printed(monkeypatch, capsys):
    import importlib
    import sys
    scripts = str(Path(__file__).resolve().parents[1] / 'scripts')
    monkeypatch.syspath_prepend(scripts)
    cli = importlib.import_module('wiki_integration_check')
    monkeypatch.setattr(cli, 'inspect', lambda *args: {'ok': True, 'proposals': [
        {'number': 2, 'status': 'fix:ci_failed', 'ci_failed_checks': ['audit-and-test']}], 'hygiene': []})
    monkeypatch.setattr(sys, 'argv', ['wiki_integration_check.py'])
    assert cli.main() == 0
    assert 'failed checks: audit-and-test' in capsys.readouterr().out


def test_failed_check_for_superseded_head_requires_reconciliation(monkeypatch, tmp_path):
    pr = candidate() | {'statusCheckRollup': [{'__typename': 'CheckRun', 'name': 'tests',
                                              'status': 'COMPLETED', 'conclusion': 'FAILURE'}]}
    monkeypatch.setattr(check, '_repository', lambda root: 'github.com/owner/repo')
    monkeypatch.setattr(check, '_gh', lambda root, *args: [pr])
    def git(root, *args):
        if '--symref' in args:
            return 'ref: refs/heads/main\tHEAD\n' + BASE + '\tHEAD'
        if '--heads' in args:
            return BASE + '\trefs/heads/main\n' + 'c' * 40 + '\trefs/heads/wiki/one'
        return 'main'
    monkeypatch.setattr(check, '_git', git)
    monkeypatch.setattr(check, 'policy', lambda *args: {'gate': 'github_pr'})
    monkeypatch.setattr(check, '_worktrees', lambda root: [])
    monkeypatch.setattr(check, '_action_findings', lambda *args: ([], True))
    assert check.inspect(tmp_path)['proposals'][0]['status'] == 'waiting:head_observation'
