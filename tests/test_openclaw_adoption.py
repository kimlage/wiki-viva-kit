"""Product return/adoption with real local Git and a synthetic PR provider."""
import json
import subprocess

import pytest

from tests.test_openclaw_product import product, execute
from tests.test_admin_commands import _plan, _execute
from tests.test_admin_sessions import _arm, _code
from wiki_core.web import git_workflows as workflows
from wiki_core.web import openclaw as oc
from wiki_core.web.admin.sessions import ADMIN_SESSION_HEADER


@pytest.fixture
def adoption(product, monkeypatch, tmp_path_factory):
    srv, root, action, params, unlock, calls = product
    token = unlock()
    sent, _ = execute(srv, token, 'agents.openclaw.dispatch', params)
    query = {'profile': 'research', 'action_id': params['action_id'], 'effect_key': sent['effect_key']}
    execute(srv, token, 'agents.openclaw.inspect', query)
    material, _ = execute(srv, token, 'agents.openclaw.receipt', query)
    prepared, _ = execute(srv, token, 'wiki.proposal.prepare', {k: material[k] for k in ('material_path', 'material_sha256')})
    branch = oc.git(root, 'branch', '--show-current')
    bare = tmp_path_factory.mktemp('approved-origin')
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    subprocess.run(['git', 'push', str(bare), 'HEAD:refs/heads/main'], cwd=root, check=True, capture_output=True)
    pr = {'number': 7, 'state': 'MERGED', 'headRefOid': prepared['head'], 'baseRefName': 'main',
          'isCrossRepository': False, 'mergeCommit': {'oid': prepared['head']}}
    native = workflows._run
    effects = []
    def provider(where, argv, **kwargs):
        effects.append(list(argv))
        if argv[0] == 'gh':
            return {'ok': True, 'stdout': json.dumps(pr)}
        if argv[:2] in (['git', 'ls-remote'], ['git', 'fetch']):
            argv = [str(bare) if a == 'origin' else a for a in argv]
        return native(where, argv, **kwargs)
    monkeypatch.setattr(workflows, '_run', provider)
    request = {'expected_head': prepared['head'], 'proposal_head': prepared['head'], 'pr': '7'}
    return srv, root, token, request, pr, effects, branch, bare, query


def test_card_adopts_exact_approved_commit_and_replay_only_observes(adoption):
    srv, root, token, request, _, effects, branch, _, query = adoption
    out, _ = execute(srv, token, 'wiki.proposal.adopt', request)
    assert out['status'] == 'approved_checkout_updated' and not out['served_adoption_verified']
    assert oc.git(root, 'branch', '--show-current') == 'main'
    assert oc.git(root, 'rev-parse', branch) == request['proposal_head']
    status, coord = srv.get('/api/coordination')
    assert status == 200
    attempt = next(a for a in coord['actions'] if a['action_id'] == query['action_id'])['runtime_attempts'][0]
    assert attempt['proposal']['status'] == 'received_in_main'
    count = len([a for a in effects if a[:2] in (['git', 'fetch'], ['git', 'switch'], ['git', 'merge'])])
    repeated, _ = execute(srv, token, 'wiki.proposal.adopt', request)
    assert repeated['status'] == 'observed_adopted' and not repeated['new_effect']
    assert count == len([a for a in effects if a[:2] in (['git', 'fetch'], ['git', 'switch'], ['git', 'merge'])])


@pytest.mark.parametrize('field,value', [('state', 'OPEN'), ('headRefOid', 'a'*40), ('isCrossRepository', True), ('baseRefName', 'other')])
def test_adoption_refuses_unmerged_or_unrelated_provider_state(adoption, field, value):
    srv, root, token, request, pr, effects, branch, _, _ = adoption
    pr[field] = value
    status, out = _plan(srv, token, 'wiki.proposal.adopt', params=request)
    assert status == 400 and not out['ok']
    assert oc.git(root, 'branch', '--show-current') == branch
    assert not any(a[:2] == ['git', 'fetch'] for a in effects)


def test_remote_target_change_requires_new_reviewed_plan(adoption):
    srv, root, token, request, _, effects, branch, bare, _ = adoption
    status, plan = _plan(srv, token, 'wiki.proposal.adopt', params=request); assert status == 200
    # Simulate a separate approved commit after planning without touching this checkout.
    tree = oc.git(root, 'rev-parse', 'HEAD^{tree}')
    new = subprocess.check_output(['git', 'commit-tree', tree, '-p', request['proposal_head'], '-m', 'Later approved state'], cwd=root, text=True).strip()
    subprocess.run(['git', 'push', str(bare), new+':refs/heads/main'], cwd=root, check=True, capture_output=True)
    status, out = _execute(srv, token, plan, confirmation=plan['plan']['confirmation']['text'])
    assert not out['ok'] and 'proposal_adoption_target_changed' in out['failed_preconditions']
    assert oc.git(root, 'branch', '--show-current') == branch
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
    assert oc.git(root, 'branch', '--show-current') == 'main'
    assert oc.git(root, 'rev-parse', 'HEAD') != request['proposal_head']
    status, coord = srv.get('/api/coordination')
    assert status == 200 and coord['actions'][0]['runtime_attempts'][0]['proposal']['status'] == 'awaiting_adoption'
    assert not any(a[:2] == ['git', 'merge'] for a in effects)
    monkeypatch.setattr(workflows, '_run', native)
    lines, _ = _arm(srv)
    _, challenge = srv.post('/api/admin/session/challenge', {})
    status, renewed = srv.post('/api/admin/session/unlock', {'challenge': challenge['challenge'], 'code': _code(lines)})
    assert status == 200
    resumed, _ = execute(srv, renewed['token'], 'wiki.proposal.adopt', {**request, 'expected_head': oc.git(root, 'rev-parse', 'HEAD')})
    assert resumed['status'] == 'approved_checkout_updated'
    assert oc.git(root, 'rev-parse', branch) == request['proposal_head']


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
    tree = oc.git(root, 'rev-parse', 'main^{tree}')
    other = subprocess.check_output(['git', 'commit-tree', tree, '-p', oc.git(root,'rev-parse','main'), '-m', 'Concurrent local main'], cwd=root,text=True).strip()
    subprocess.run(['git', 'update-ref', 'refs/heads/main', other], cwd=root,check=True)
    status, out = _execute(srv, token, plan, confirmation=plan['plan']['confirmation']['text'])
    assert not out['ok'] and oc.git(root, 'rev-parse','main') == other
    assert oc.git(root,'branch','--show-current') == branch
    assert not any(a[:2] == ['git','switch'] for a in effects)
