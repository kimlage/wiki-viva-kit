"""Scoped replay proves only a one-manifest root case; no global fallback."""
import subprocess

import pytest
import yaml

from wiki_core.context_packet import build_packet
from wiki_core.context_policy import load_policy
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.scoped_v1_replay import ScopedReplayError, replay_root_only_v1


def git(root,*args):
    return subprocess.run(['git','-C',str(root),*args],check=True,text=True,capture_output=True).stdout.strip()


def put(root,path,text):
    dst=root/path; dst.parent.mkdir(parents=True,exist_ok=True); dst.write_text(text,encoding='utf-8')


def commit(root):
    git(root,'add','-A'); git(root,'commit','-qm','synthetic')
    git(root,'update-ref','refs/remotes/origin/main','HEAD')


@pytest.fixture
def root_only(tmp_path):
    git(tmp_path,'init','-q'); git(tmp_path,'config','user.name','Synthetic'); git(tmp_path,'config','user.email','synthetic@example.invalid')
    put(tmp_path,'AGENTS.md','# Instructions\n\n## Wiki v2: mandatory references\n\n- [Rule](docs/rule.md)\n\n## Wiki v2: indexes\n\n- [Index](memories/index.md)\n')
    put(tmp_path,'docs/rule.md','Synthetic rule\n'); put(tmp_path,'memories/index.md','Synthetic index\n')
    put(tmp_path,'source.md','---\nstatus: recorded\n---\nSynthetic source\n')
    limits={'read':['self'],'write':['self'],'capabilities':[],'deny':{},'publication':[]}
    legacy={'schema_version':'wiki.context/v1','id':'root','parent':None,'root':'.','purpose':'synthetic',
            'owner':'fixture','instructions':['AGENTS.md','docs/rule.md'],'skills':[],'templates':[],
            'policy':limits,'imports':[],'exports':[]}
    controls={'schema_version':'wiki.folder-controls/v2','controls':{'.':{'policy':limits,'imports':[],'exports':[]}}}
    put(tmp_path,'context.yaml',yaml.safe_dump(legacy)); put(tmp_path,'wiki-context-controls.yaml',yaml.safe_dump(controls))
    commit(tmp_path)
    return tmp_path


def receipt(repo):
    packet=build_packet(repo,load_policy(repo,'HEAD'),'root','HEAD',
        [{'ref':'source.md','producer':'root','reason':'synthetic','use':'interpret','classification':'synthetic','field':'status'}],
        30000,task_id='x',goal='x',output='report.md',integrator='independent')
    result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':'x','context_id':'root',
            'packet_digest':packet['packet_digest'],'changes':[{'path':'report.md','action':'created'}],
            'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':[]},'blockers':[]}
    return packet,result


def test_one_manifest_root_rebuilds_v1_packet_and_context_exactly(root_only):
    packet,result=receipt(root_only); p=load_folder_policy_v2(root_only,'HEAD')
    out=replay_root_only_v1(root_only,p,index_path='memories/index.md',packet=packet,result=result)
    assert out['state']=='reproduced' and out['packet_digest']==packet['packet_digest']
    assert out['historical_policy_revision']==packet['policy_revision']
    assert out['projection']=='single_root_manifest_only' and out['normative_equivalence']=='not_assessed'
    assert out['read_verification']=='reported_not_independently_verified' and out['review']=='not_performed'


def test_other_owner_manifest_is_not_opened_even_if_historically_present(root_only,monkeypatch):
    child={'schema_version':'wiki.context/v1','id':'other','parent':'root','root':'other','purpose':'synthetic',
           'owner':'fixture','instructions':[],'skills':[],'templates':[],
           'policy':{'read':['self'],'write':['self']},'imports':[],'exports':[]}
    put(root_only,'other/context.yaml',yaml.safe_dump(child)); commit(root_only)
    packet,result=receipt(root_only); p=load_folder_policy_v2(root_only,'HEAD')
    import wiki_core.context_policy as legacy
    original=legacy.git_file
    def spy(root,revision,path):
        if path=='other/context.yaml': raise AssertionError('other owner manifest body was read')
        return original(root,revision,path)
    monkeypatch.setattr(legacy,'git_file',spy)
    with pytest.raises(ScopedReplayError,match='multi-context projection unavailable'):
        replay_root_only_v1(root_only,p,index_path='memories/index.md',packet=packet,result=result)


def test_revoked_input_blocks_before_any_legacy_manifest_body(root_only,monkeypatch):
    packet,result=receipt(root_only)
    path=root_only/'wiki-context-controls.yaml'; data=yaml.safe_load(path.read_text())
    data['controls']['.']['policy']['deny']={'read':['source.md']}
    path.write_text(yaml.safe_dump(data)); commit(root_only)
    p=load_folder_policy_v2(root_only,'HEAD')
    import wiki_core.context_policy as legacy
    monkeypatch.setattr(legacy,'git_file',lambda *a,**k: pytest.fail('historical manifest body was read'))
    with pytest.raises(ScopedReplayError,match='current input authority unavailable'):
        replay_root_only_v1(root_only,p,index_path='memories/index.md',packet=packet,result=result)


def test_unpermitted_root_policy_blocks_before_historical_body(root_only,monkeypatch):
    packet,result=receipt(root_only)
    path=root_only/'wiki-context-controls.yaml'; data=yaml.safe_load(path.read_text())
    data['controls']['.']['policy']['deny']={'read':['context.yaml']}
    path.write_text(yaml.safe_dump(data)); commit(root_only)
    p=load_folder_policy_v2(root_only,'HEAD')
    import wiki_core.context_policy as legacy
    monkeypatch.setattr(legacy,'git_file',lambda *a,**k: pytest.fail('historical manifest body was read'))
    with pytest.raises(ScopedReplayError,match='root policy read is not authorized'):
        replay_root_only_v1(root_only,p,index_path='memories/index.md',packet=packet,result=result)


def test_rejects_dynamic_query_receipts_without_legacy_read(root_only,monkeypatch):
    packet,result=receipt(root_only); packet={**packet,'query_fingerprint':'f'*64}
    import wiki_core.context_policy as legacy
    monkeypatch.setattr(legacy,'git_file',lambda *a,**k: pytest.fail('historical manifest body was read'))
    with pytest.raises(ScopedReplayError,match='dynamic v1 query'):
        replay_root_only_v1(root_only,load_folder_policy_v2(root_only,'HEAD'),index_path='memories/index.md',packet=packet,result=result)
