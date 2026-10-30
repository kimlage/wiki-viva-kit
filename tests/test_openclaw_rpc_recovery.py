import copy,datetime as dt,hashlib,json,subprocess
from pathlib import Path
import pytest
from tests.test_openclaw_commands import runtime
from tests.test_openclaw_failure import review_inputs
from wiki_core.web import openclaw as oc


def unaccepted(runtime,monkeypatch):
    root,cfg,params,h,calls,_=runtime
    original=oc.Gateway.call
    def refusal(self,method,params):
        if method=='chat.send':raise oc.GatewayRequestError({'type':'rpc_rejection','code':'INVALID_REQUEST','reason':'system_provenance_requires_admin'})
        return original(self,method,params)
    monkeypatch.setattr(oc.Gateway,'call',refusal)
    plan=oc.plan_dispatch(root,cfg,params)
    with pytest.raises(oc.GatewayRequestError):oc.dispatch(root,cfg,plan)
    monkeypatch.setattr(oc.Gateway,'call',original)
    directory=oc.storage(root,cfg,plan['effect_key']);contract=oc.read_receipt(directory/'mission.json')
    contract['expires_at']=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=1)).isoformat()
    # Synthetic fixture models a naturally expired original contract.
    (directory/'mission.json').write_text(json.dumps(contract));sha=hashlib.sha256((directory/'mission.json').read_bytes()).hexdigest()
    active=directory.parent/'mission-active.json';a=json.loads(active.read_text());a['contract_sha256']=sha;active.write_text(json.dumps(a))
    q,rp,ep=review_inputs(root,cfg,plan)
    evidence={'status':'expired_unaccepted','runId':plan['effect_key'],'contract_sha256':sha,'expires_at':contract['expires_at']}
    ep.write_text(json.dumps(evidence));r=json.loads(rp.read_text());r['evidence_sha256']=hashlib.sha256(ep.read_bytes()).hexdigest();rp.write_text(json.dumps(r));q['review_sha256']=hashlib.sha256(rp.read_bytes()).hexdigest()
    return plan,directory,q,rp,ep


def test_expired_unaccepted_is_reviewed_without_native_terminal_or_replay(runtime,monkeypatch):
    root,cfg,_,h,calls,_=runtime
    plan,d,q,_,_=unaccepted(runtime,monkeypatch)
    before={p.name:p.read_bytes() for p in d.iterdir()}
    assert oc.read_receipt(d/'dispatch-error.json')['stage']=='send'
    prepared=oc.plan_failure_resolution(root,cfg,q)
    result=oc.resolve_failed(root,cfg,q,prepared)
    assert result['status']=='resolved_without_result' and not result['new_dispatch']
    assert result['resolution']['external_effects']=='not_determined_by_this_receipt'
    assert all((d/k).read_bytes()==v for k,v in before.items())
    assert not (d/'accepted.json').exists() and not (d/'result.json').exists()
    assert not (d.parent/'mission-active.json').exists()
    assert oc.inspect(root,cfg,q)['reconciled']
    assert oc.resolve_failed(root,cfg,q,prepared)==result


@pytest.mark.parametrize('change',['claim','inference','accepted','leaf','last_run','queued','contract','expiry'])
def test_expired_recovery_refuses_ambiguous_or_changed_execution(runtime,monkeypatch,change):
    root,cfg,_,h,_,_=runtime;plan,d,q,_,ep=unaccepted(runtime,monkeypatch)
    prepared=oc.plan_failure_resolution(root,cfg,q)
    if change=='claim':(d/'guard-turn.json').write_text('{}')
    elif change=='inference':(d/'guard-inference.jsonl').write_text('{}')
    elif change=='accepted':oc.write_new(d/'accepted.json',{'plan_sha256':oc.digest(plan),'run_id':plan['effect_key']})
    elif change=='leaf':h['sessionInfo']['activeLeafEntryId']='changed'
    elif change=='last_run':h['sessionInfo']['lastRunId']=plan['effect_key']
    elif change=='queued':h['pendingInputs']={'total':1,'queuedCount':1,'items':[{'id':'x','runId':plan['effect_key'],'state':'queued'}]}
    else:
        c=json.loads((d/'mission.json').read_text());c['expires_at' if change=='expiry' else 'model']='2999-01-01T00:00:00+00:00' if change=='expiry' else 'other';(d/'mission.json').write_text(json.dumps(c))
    with pytest.raises(ValueError):oc.resolve_failed(root,cfg,q,prepared)
    assert not (d/'failure-resolution.json').exists()
    assert (d.parent/'mission-active.json').exists()


def test_gateway_keeps_structured_failure_before_returncode_and_uses_stdin(monkeypatch):
    rt={'profile':'synthetic','state_dir':'/synthetic/state','node_binary':'/synthetic/node','entrypoint':'/synthetic/core/openclaw.mjs','gateway':'ws://127.0.0.1:19880'}
    captured=[]
    def run(argv,**kwargs):
        captured.append((argv,kwargs));return subprocess.CompletedProcess(argv,1,json.dumps({'ok':False,'error':{'type':'rpc_rejection','code':'INVALID_REQUEST','reason':'system_provenance_requires_admin'}}),'arbitrary private stderr')
    monkeypatch.setattr(oc.subprocess,'run',run)
    with pytest.raises(oc.GatewayRequestError) as error:oc.Gateway(rt,{}).call('chat.send',{'message':'synthetic'})
    assert error.value.diagnostic['reason']=='system_provenance_requires_admin'
    argv,kw=captured[0];assert 'synthetic' not in ' '.join(argv[1:2]);assert json.loads(kw['input'])['params']=={'message':'synthetic'}
    assert '--token' not in argv and '--params' not in argv
