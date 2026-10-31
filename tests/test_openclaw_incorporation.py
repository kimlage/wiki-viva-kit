"""A received comment cannot consume the useful body-incorporation obligation."""
import hashlib
import subprocess

import pytest
from tests.test_openclaw_product import product, execute
from wiki_core.web import openclaw as oc
from wiki_core.action_transition import integrate_action_body, _parse_document, action_transition_diagnostics


def commit(root, message, *, published=True):
    for args in [('add','.'),('commit','-qm',message)]:
        subprocess.run(['git',*args],cwd=root,check=True,capture_output=True)
    if published:oc.git(root,'update-ref','refs/remotes/origin/main','HEAD')


@pytest.fixture
def received(product):
    srv,root,action,params,unlock,calls=product;token=unlock()
    sent,_=execute(srv,token,'agents.openclaw.dispatch',params)
    query={'profile':'research','action_id':params['action_id'],'effect_key':sent['effect_key']}
    execute(srv,token,'agents.openclaw.inspect',query)
    material,_=execute(srv,token,'agents.openclaw.receipt',query)
    execute(srv,token,'wiki.proposal.prepare',{k:material[k] for k in ('material_path','material_sha256')})
    branch=oc.git(root,'branch','--show-current')
    oc.git(root,'switch','main');oc.git(root,'merge','--ff-only',branch)
    oc.git(root,'update-ref','refs/remotes/origin/main','HEAD')
    directory,plan,_,_=oc.retained_intent(root,srv.server.config,query)
    return root,srv.server.config,action,directory,plan


def status(fixture):
    root,cfg,_,d,p=fixture
    return oc.proposal_status(root,cfg,d,p)


def curate(fixture, *, run=None):
    root,cfg,action,d,p=fixture
    _,body=_parse_document(action.read_text())
    paragraph=('The synthetic recurring operation now uses one bounded continuation and preserves the original '
               'mission identity. A received response must be reviewed and incorporated before another occurrence.')
    new=body+'\n\n'+paragraph+'\n'
    integrate_action_body(root,action,new,expected_sha256=hashlib.sha256(action.read_bytes()).hexdigest(),
        contribution={'effect_key':'curation-'+p['effect_key'],'run_id':run or p['effect_key'],
                      'material_sha256':hashlib.sha256(new.encode()).hexdigest()})
    return paragraph


def test_received_comment_is_not_body_incorporation(received):
    got=status(received)
    assert got['status']=='received_in_main' and got['content_incorporated_in_main'] is False


def test_exact_run_real_body_and_approved_main_are_required(received):
    curate(received)
    assert not status(received)['content_incorporated_in_main']  # WIP is not main content.
    commit(received[0],'Reviewed useful body incorporation')
    got=status(received)
    assert got['status']=='received_in_main' and got['content_incorporated_in_main']


def test_another_run_body_does_not_consume_this_result(received):
    curate(received,run='another-synthetic-run');commit(received[0],'Different reviewed contribution')
    assert status(received)['status']=='received_in_main'
    assert not status(received)['content_incorporated_in_main']


def test_unreceipted_body_change_cannot_claim_incorporation(received):
    root,cfg,action,d,p=received
    action.write_text(action.read_text()+'\nUnreceipted change.\n');commit(root,'Unreceipted synthetic change')
    got=status(received)
    assert not got['content_incorporated_in_main']
    assert got['status']=='received_in_main'  # communication remains distinct from unassociated body edits.


def test_later_separately_committed_consolidation_preserves_valid_incorporation(received):
    root,cfg,action,d,p=received
    paragraph=curate(received);commit(root,'Reviewed factual contribution')
    text=action.read_text();fm,body=_parse_document(text)
    sibling=action.parent/'shared-procedure.md'
    sibling.write_text('---\npage_id: shared-procedure\npage_type: action\naction_state: open\n---\n\n# Shared procedure\n\n'+paragraph+'\n')
    commit(root,'Approved canonical sibling procedure')
    records=[{'paragraph':paragraph,'canonical_ref':sibling.relative_to(root).as_posix(),
              'canonical_sha256':hashlib.sha256(sibling.read_bytes()).hexdigest(),'label':'Shared procedure'}]
    new=body.replace(paragraph,'[Shared procedure](shared-procedure.md).')
    integrate_action_body(root,action,new,expected_sha256=hashlib.sha256(action.read_bytes()).hexdigest(),
        contribution={'effect_key':'editorial-'+p['effect_key'],'run_id':'separate-editorial-run',
                      'material_sha256':hashlib.sha256(new.encode()).hexdigest()},consolidations=records)
    commit(root,'Separate reviewed editorial consolidation')
    received_text=oc.read_receipt(d/'receipt-material-integrity.json')['action_after_text']
    assert action_transition_diagnostics(received_text,action.read_text())  # mixed aggregate is still refused.
    got=status(received)
    assert got['status']=='received_in_main' and got['content_incorporated_in_main']


@pytest.mark.parametrize('damage,error', [('missing', r'receipt-material\.json'), ('corrupt', 'openclaw_material_changed')])
def test_observation_preserves_valid_result_when_proposal_material_is_unavailable(received, monkeypatch, damage, error):
    root, cfg, action, directory, plan = received
    result = oc.verified_result(directory, plan)
    assert status(received)['status'] == 'received_in_main'
    params = {'profile': plan['binding']['profile'], 'action_id': plan['binding']['action_id'],
              'action_sha256': hashlib.sha256(action.read_bytes()).hexdigest(),
              'mission_id': plan['mission']['id'], 'message': 'A distinct synthetic follow-up.'}
    prepared = oc.plan_dispatch(root, cfg, params)
    material = directory / 'receipt-material.json'
    if damage == 'missing':
        material.unlink()
    else:
        material.write_text('Corrupt synthetic proposal material.')
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir() if p.is_file()}
    native_call = oc.Gateway.call
    def forbidden(*args, **kwargs):
        raise AssertionError('observation entered a native API or writer')
    monkeypatch.setattr(oc.Gateway, 'call', forbidden)
    for name in ('inspect', 'write_new', 'release_mission_lock'):
        monkeypatch.setattr(oc, name, forbidden)

    observed = oc.runtime_observations(root, cfg)
    assert len(observed['attempts']) == 1
    attempt = observed['attempts'][0]
    assert attempt['run_id'] == attempt['effect_key'] == plan['effect_key']
    assert attempt['action_id'] == params['action_id'] and attempt['profile'] == params['profile']
    assert attempt['status'] == 'result_retained' and attempt['result_captured_at'] == result['captured_at']
    assert attempt['result'] == {'excerpt': result['text'][:oc.MAX_RESULT_EXCERPT_CHARS],
        'text_sha256': result['text_sha256'], 'truncated': len(result['text']) > oc.MAX_RESULT_EXCERPT_CHARS}
    assert attempt['proposal'] is None
    assert attempt['proposal_error_code'] == 'openclaw_proposal_unavailable_reconcile'
    assert observed['errors'] == ['openclaw_proposal_unavailable_reconcile']
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir() if p.is_file()}

    # The observational fallback must not relax either execution admission path.
    with pytest.raises((OSError, ValueError), match=error):
        oc.attempts(root, cfg, params['profile'], params['action_id'])
    with pytest.raises((OSError, ValueError), match=error):
        oc.plan_dispatch(root, cfg, params)
    def history_only(self, method, payload):
        assert method == 'chat.history', 'corrupt proposal admitted an execution effect'
        return native_call(self, method, payload)
    monkeypatch.setattr(oc.Gateway, 'call', history_only)
    with pytest.raises((OSError, ValueError), match=error):
        oc.dispatch(root, cfg, prepared)
    assert not (oc.storage(root, cfg, prepared['effect_key']) / 'intent.json').exists()


def test_unpublished_main_body_is_not_approved_incorporation(received):
    curate(received);commit(received[0],'Local unreviewed body',published=False)
    assert not status(received)['content_incorporated_in_main']
    oc.git(received[0],'update-ref','refs/remotes/origin/main','HEAD')
    assert status(received)['content_incorporated_in_main']


def test_later_unreceipted_rewrite_drops_prior_incorporation_proof(received):
    root,cfg,action,d,p=received
    curate(received);commit(root,'Reviewed contribution')
    assert status(received)['content_incorporated_in_main']
    fm,body=_parse_document(action.read_text())
    from wiki_core.action_transition import _render_document
    action.write_text(_render_document(fm,'\n\n# Unassociated replacement\n\nNo curated material remains.\n'))
    commit(root,'Unreceipted replacement of all prose')
    assert not status(received)['content_incorporated_in_main']


@pytest.mark.parametrize('kind,qualifies',[('structured',True),('both_equal',True),('contradictory',False)])
def test_flat_and_structured_run_identity_are_unambiguous(received,kind,qualifies):
    root,cfg,action,d,p=received
    _,body=_parse_document(action.read_text());new=body+'\n\nA reviewed technical result has now been incorporated.\n'
    metadata={'effect_key':'identity-'+p['effect_key'],'material_sha256':hashlib.sha256(new.encode()).hexdigest(),
              'run_ref':{'run_id':p['effect_key']}}
    if kind!='structured':metadata['run_id']=p['effect_key'] if kind=='both_equal' else 'contradictory-run'
    integrate_action_body(root,action,new,expected_sha256=hashlib.sha256(action.read_bytes()).hexdigest(),contribution=metadata)
    commit(root,'Reviewed identity contribution')
    assert status(received)['content_incorporated_in_main'] is qualifies
