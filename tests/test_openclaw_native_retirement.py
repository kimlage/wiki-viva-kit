"""Native startup cleanup needs reviewed failure, exclusive custody and exact CAS."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import pytest
from tests.test_openclaw_commands import runtime
from tests.test_openclaw_interrupted_resolution import interrupted
from wiki_core.web import openclaw as oc


def fixture(runtime,monkeypatch):
    root,cfg,*_=runtime
    # C1 source lives in the consuming checkout, just as the qualified loader.
    module=root/'scripts/openclaw/mission-retirement.mjs';module.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).parents[1]/'scripts/openclaw/mission-retirement.mjs',module)
    for args in (['add','.'],['commit','-qm','Synthetic adapter adoption']):
        subprocess.run(['git',*args],cwd=root,check=True,capture_output=True)
    plan,d,q=interrupted(runtime,monkeypatch)
    prepared=oc.plan_failure_resolution(root,cfg,q);oc.resolve_failed(root,cfg,q,prepared)
    inference=d/'guard-inference.jsonl'
    inference.write_text(inference.read_text()*2) # Two actual JSONL records, as the failed live turn.
    subprocess.run(['git','update-ref','refs/remotes/origin/main','HEAD'],cwd=root,check=True,capture_output=True)
    return root,module,plan,d


def run(root,module,plan,d,change):
    data={'module':str(module),'run':plan['effect_key'],'directory':str(d.parent),
          'resolution':str(d/'failure-resolution.json'),'change':change}
    script=Path(__file__).parent/'node/openclaw-retirement-driver.mjs'
    result=subprocess.run(['node',str(script)],input=json.dumps(data),capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_exact_reviewed_native_retirement_once_preserves_all_original_bytes(runtime,monkeypatch):
    root,module,p,d=fixture(runtime,monkeypatch)
    before={f.name:f.read_bytes() for f in d.iterdir()}
    got=run(root,module,p,d,'valid')
    assert got['ok'] and got['result']=='settled' and got['again'] is None and got['committed']==1
    assert all((d/name).read_bytes()==raw for name,raw in before.items())
    assert not (d/'result.json').exists() and not (d.parent/'mission-active.json').exists()


@pytest.mark.parametrize('change',['writer','claim','cycle','delivery','harness','competing','live','queue',
    'late_competing','late_queue','revoked','commit_entry','receipt','precommit_crash'])
def test_native_or_review_race_refuses_without_retirement(runtime,monkeypatch,change):
    root,module,p,d=fixture(runtime,monkeypatch)
    got=run(root,module,p,d,change)
    assert not got['ok'] and got['committed']==0,got


def test_lost_response_does_not_repeat_committed_retirement(runtime,monkeypatch):
    root,module,p,d=fixture(runtime,monkeypatch)
    got=run(root,module,p,d,'postcommit_crash')
    assert not got['ok'] and got['committed']==1 and got['again'] is None


@pytest.mark.parametrize('change',['branch','dirty','root','original_head','contract','reviewer','review_hash',
 'inference','terminal','continuation','result','unexpired'])
def test_retirement_refuses_unapproved_or_rewritten_provenance(runtime,monkeypatch,change):
    root,module,p,d=fixture(runtime,monkeypatch)
    if change=='branch':
        for args in (['switch','-c','wiki/unapproved'],['update-ref','refs/remotes/origin/wiki/unapproved','HEAD']):
            subprocess.run(['git',*args],cwd=root,check=True,capture_output=True)
    elif change=='dirty':(root/'unapproved.txt').write_text('changed')
    elif change in {'terminal','continuation','result'}:
        (d/{'terminal':'guard-terminal.json','continuation':'guard-recovery.json','result':'result.json'}[change]).write_text('{}')
    elif change=='inference':(d/'guard-inference.jsonl').write_text('')
    else:
        file=d/('mission.json' if change in {'root','original_head','contract','unexpired'} else 'failure-resolution.json')
        v=json.loads(file.read_text())
        if change=='root':v['recovery']['repo_root']=str(root.parent)
        elif change=='original_head':v['recovery']['approved_head']='0'*40
        elif change=='contract':v['action_id']='foreign-action'
        elif change=='unexpired':v['expires_at']='2099-01-01T00:00:00+00:00'
        elif change=='reviewer':v['review']['reviewer']=v['review']['author']
        else:v['review_sha256']='0'*64
        file.write_text(json.dumps(v))
    got=run(root,module,p,d,change)
    assert not got['ok'] and got['committed']==0,got


def test_pinned_actual_native_writer_and_missing_hook_negative_control():
    import os
    core=os.environ.get('WIKI_TEST_OPENCLAW_CORE_ROOT')
    if not core:pytest.skip('Pinned native OpenClaw core not supplied')
    node=os.environ.get('WIKI_TEST_OPENCLAW_NODE') or shutil.which('node')
    root=Path(__file__).parents[1]
    args=[node,'--import','./tests/node/openclaw-retirement-native-preload.mjs',
          'tests/node/openclaw-retirement-native-worker.mjs']
    env={**os.environ,'WIKI_OPENCLAW_GUARD_BOOTSTRAP':'0'}
    good=subprocess.run(args,cwd=root,env=env,capture_output=True,text=True,timeout=60)
    assert good.returncode==0,good.stdout+good.stderr
    assert next(json.loads(line) for line in good.stdout.splitlines() if line.startswith('{"ok"'))['real_native_worker']
    bad=subprocess.run(args,cwd=root,env={**env,'WIKI_TEST_RETIREMENT_SKIP_WRITER_HOOK':'1'},
                       capture_output=True,text=True,timeout=60)
    assert bad.returncode!=0 and 'actual writer ignored the full-entry CAS' in bad.stderr,bad.stdout+bad.stderr


def test_sqlite_worker_source_and_integrity_refusals():
    root=Path(__file__).parents[1]
    got=subprocess.run(['node','--test','tests/node/openclaw-retirement-workers.test.mjs'],cwd=root,
                       capture_output=True,text=True,timeout=20)
    assert got.returncode==0,got.stdout+got.stderr
