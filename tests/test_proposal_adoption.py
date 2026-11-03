"""Generic exact-head adoption with real local Git and a synthetic PR provider."""
import json
import subprocess
import pytest
from tests.test_normal_proposal_admission import prepared, _git
from tests.test_admin_commands import _plan, _execute
from tests.test_admin_sessions import _arm, _code
from wiki_core.web import git_workflows as workflows
from wiki_core.web.admin.sessions import ADMIN_SESSION_HEADER


def execute(srv, token, command, params):
    status, plan = _plan(srv, token, command, params=params)
    assert status == 200, plan
    status, result = _execute(srv, token, plan, confirmation=plan['plan']['confirmation']['text'])
    assert status == 200 and result['ok'], result
    return result['output'], result


@pytest.fixture
def adoption(prepared, monkeypatch, tmp_path_factory):
    srv, root, params, unlock, _clock = prepared
    # Derived artifacts are ignored in deployed repositories; retain them locally.
    (root / ".git/info/exclude").write_text("data/derived/\n")
    token = unlock()
    output, _ = execute(srv, token, 'wiki.proposal.prepare', params)
    branch = _git(root, 'branch', '--show-current')
    bare = tmp_path_factory.mktemp('approved-origin')
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    subprocess.run(['git', 'push', str(bare), 'HEAD:refs/heads/main'], cwd=root, check=True, capture_output=True)
    pr = {'number': 7, 'state': 'MERGED', 'headRefOid': output['head'], 'baseRefName': 'main',
          'isCrossRepository': False, 'mergeCommit': {'oid': output['head']}}
    native = workflows._run
    effects = []
    def provider(where, argv, **kwargs):
        effects.append(list(argv))
        if argv[0] == 'gh': return {'ok': True, 'stdout': json.dumps(pr)}
        if argv[:2] in (['git', 'ls-remote'], ['git', 'fetch']):
            argv = [str(bare) if a == 'origin' else a for a in argv]
        return native(where, argv, **kwargs)
    monkeypatch.setattr(workflows, '_run', provider)
    request = {'expected_head': output['head'], 'proposal_head': output['head'], 'pr': '7'}
    return srv, root, token, request, pr, effects, branch, bare, {}


@pytest.mark.parametrize('cleanup_branch', [False, True])
def test_adopts_exact_approved_commit_and_replay_only_observes(adoption, cleanup_branch):
    srv, root, token, request, _, effects, branch, _, _ = adoption
    output, _ = execute(srv, token, 'wiki.proposal.adopt', request)
    assert output['status'] == 'approved_checkout_updated' and not output['served_adoption_verified']
    assert _git(root, 'branch', '--show-current') == 'main'
    assert _git(root, 'rev-parse', branch) == request['proposal_head']
    if cleanup_branch: subprocess.run(['git', 'branch', '-d', branch], cwd=root, check=True, capture_output=True)
    count = len([a for a in effects if a[:2] in (['git', 'fetch'], ['git', 'switch'], ['git', 'merge'])])
    replay, _ = execute(srv, token, 'wiki.proposal.adopt', request)
    assert replay['status'] == 'observed_adopted' and not replay['new_effect']
    assert count == len([a for a in effects if a[:2] in (['git', 'fetch'], ['git', 'switch'], ['git', 'merge'])])


@pytest.mark.parametrize('field,value', [('state', 'OPEN'), ('headRefOid', 'a'*40), ('isCrossRepository', True), ('baseRefName', 'other')])
def test_adoption_refuses_unmerged_or_unrelated_provider_state(adoption, field, value):
    srv, root, token, request, pr, effects, branch, _, _ = adoption
    pr[field] = value
    status, out = _plan(srv, token, 'wiki.proposal.adopt', params=request)
    assert status == 400 and not out['ok']
    assert _git(root, 'branch', '--show-current') == branch
    assert not any(a[:2] == ['git', 'fetch'] for a in effects)


def test_remote_target_change_requires_new_reviewed_plan(adoption):
    srv, root, token, request, _, effects, branch, bare, _ = adoption
    status, plan = _plan(srv, token, 'wiki.proposal.adopt', params=request); assert status == 200
    # Simulate a separate approved commit after planning without touching this checkout.
    tree = _git(root, 'rev-parse', 'HEAD^{tree}')
    new = subprocess.check_output(['git', 'commit-tree', tree, '-p', request['proposal_head'], '-m', 'Later approved state'], cwd=root, text=True).strip()
    subprocess.run(['git', 'push', str(bare), new+':refs/heads/main'], cwd=root, check=True, capture_output=True)
    status, out = _execute(srv, token, plan, confirmation=plan['plan']['confirmation']['text'])
    assert not out['ok'] and 'proposal_adoption_target_changed' in out['failed_preconditions']
    assert _git(root, 'branch', '--show-current') == branch
    assert not any(a[:2] == ['git', 'fetch'] for a in effects)


def test_revocation_after_switch_leaves_recoverable_main_then_resumes(adoption, monkeypatch):
    srv, root, token, request, _, effects, branch, _, _ = adoption
    native = workflows._run
    locked = []
    def revoke(where, argv, **kwargs):
        result = native(where, argv, **kwargs)
        if argv[:2] == ['git', 'switch']:
            status, _ = srv.post('/api/admin/session/lock', {}, headers={ADMIN_SESSION_HEADER: token})
            locked.append(status)
        return result
    monkeypatch.setattr(workflows, '_run', revoke)
    status, plan = _plan(srv, token, 'wiki.proposal.adopt', params=request); assert status == 200
    status, out = _execute(srv, token, plan, confirmation=plan['plan']['confirmation']['text'])
    assert not out['ok'] and locked and out['output']['status'] == 'reconciliation_required'
    assert _git(root, 'branch', '--show-current') == 'main'
    assert _git(root, 'rev-parse', 'HEAD') != request['proposal_head']
    assert not any(a[:2] == ['git', 'merge'] for a in effects)
    monkeypatch.setattr(workflows, '_run', native)
    lines, _ = _arm(srv)
    _, challenge = srv.post('/api/admin/session/challenge', {})
    status, renewed = srv.post('/api/admin/session/unlock', {'challenge': challenge['challenge'], 'code': _code(lines)})
    assert status == 200
    resumed, _ = execute(srv, renewed['token'], 'wiki.proposal.adopt', {**request, 'expected_head': _git(root, 'rev-parse', 'HEAD')})
    assert resumed['status'] == 'approved_checkout_updated'
    assert _git(root, 'rev-parse', branch) == request['proposal_head']


def test_lost_fast_forward_response_is_observed_without_repeating(adoption, monkeypatch):
    srv, root, token, request, _, effects, _, _, _ = adoption
    native = workflows._run
    def lost(where, argv, **kwargs):
        result = native(where, argv, **kwargs)
        return {**result, 'ok': False} if argv[:2] == ['git', 'merge'] else result
    monkeypatch.setattr(workflows, '_run', lost)
    status, plan = _plan(srv, token, 'wiki.proposal.adopt', params=request); assert status == 200
    status, out = _execute(srv, token, plan, confirmation=plan['plan']['confirmation']['text'])
    assert not out['ok'] and out['output']['head'] == request['proposal_head']
    count = len(effects)
    observed, _ = execute(srv, token, 'wiki.proposal.adopt', request)
    assert observed['status'] == 'observed_adopted'
    assert not any(a[:2] in (['git', 'fetch'], ['git', 'switch'], ['git', 'merge']) for a in effects[count:])


def test_adoption_cannot_overwrite_main_changed_after_plan(adoption):
    srv, root, token, request, _, effects, branch, _, _ = adoption
    status, plan = _plan(srv, token, 'wiki.proposal.adopt', params=request); assert status == 200
    tree = _git(root, 'rev-parse', 'main^{tree}')
    other = subprocess.check_output(['git', 'commit-tree', tree, '-p', _git(root,'rev-parse','main'), '-m', 'Concurrent local main'], cwd=root,text=True).strip()
    subprocess.run(['git', 'update-ref', 'refs/heads/main', other], cwd=root,check=True)
    status, out = _execute(srv, token, plan, confirmation=plan['plan']['confirmation']['text'])
    assert not out['ok'] and _git(root, 'rev-parse','main') == other
    assert _git(root,'branch','--show-current') == branch
    assert not any(a[:2] == ['git','switch'] for a in effects)


def test_adoption_rejects_origin_userinfo_without_exposing_it(adoption):
    srv,root,token,request,_,effects,_,_,_=adoption
    credential='synthetic-access-material'
    subprocess.run(['git','remote','set-url','origin','https://'+credential+'@github.com/synthetic/wiki.git'],cwd=root,check=True)
    status,out=_plan(srv,token,'wiki.proposal.adopt',params=request)
    assert status==400 and credential not in json.dumps(out)
    assert out['detail']=='proposal_origin_credentials_not_allowed'
    assert not any(a[0]=='gh' for a in effects)


def test_already_current_main_does_not_prove_unrelated_merge_inclusion(adoption):
    srv,root,token,request,pr,_,_,_,_=adoption
    execute(srv,token,'wiki.proposal.adopt',request)
    tree=_git(root,'rev-parse','HEAD^{tree}')
    orphan=subprocess.check_output(['git','commit-tree',tree,'-m','Unrelated merge'],cwd=root,text=True).strip()
    pr['mergeCommit']['oid']=orphan
    status,plan=_plan(srv,token,'wiki.proposal.adopt',params=request);assert status==200
    status,out=_execute(srv,token,plan,confirmation=plan['plan']['confirmation']['text'])
    assert not out['ok'] and 'proposal_adoption_merge_not_in_approved_history' in out['failed_preconditions']
