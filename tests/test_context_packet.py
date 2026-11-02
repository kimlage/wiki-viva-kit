import json
import subprocess
from pathlib import Path
import pytest
from jsonschema import validate
from wiki_core.context_policy import PolicyError, load_policy
from wiki_core.context_packet import build_packet, blocker, connection_proposal

BASE=Path(__file__).resolve().parents[1]

def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()

@pytest.fixture
def repo(tmp_path):
    git(tmp_path,'init','-q'); git(tmp_path,'config','user.email','synthetic@example.invalid'); git(tmp_path,'config','user.name','Synthetic')
    (tmp_path/'ctx').mkdir(); (tmp_path/'ctx/rules.md').write_text('# Mandatory\nRule body\n'); (tmp_path/'ctx/evidence.md').write_text('# Evidence\nFirst body\n')
    d={'schema_version':'wiki.context/v1','contexts':[{'id':'root','parent':None,'root':'ctx','purpose':'Synthetic','owner':'operator','instructions':['ctx/rules.md'],'skills':[],'templates':[],'policy':{'read':['self'],'write':[],'capabilities':[],'publication':[],'deny':[]},'imports':[],'exports':[]}]}
    (tmp_path/'ctx/policy.json').write_text(json.dumps(d)); git(tmp_path,'add','.'); git(tmp_path,'commit','-qm','initial'); git(tmp_path,'update-ref','refs/remotes/origin/main',git(tmp_path,'rev-parse','HEAD'))
    return tmp_path


def test_packet_mandatory_bytes_digest_budget_and_revoke(repo):
    old=git(repo,'rev-parse','HEAD'); p=load_policy(repo,old,'ctx/policy.json')
    evidence=[{'ref':'ctx/evidence.md','producer':'root','reason':'direct evidence','use':'interpret','classification':'synthetic'}]
    packet=build_packet(repo,p,'root',old,evidence,1000)
    validate(packet,json.loads((BASE/'docs/references/schemas/wiki-task-context-v1.schema.json').read_text()))
    assert packet['inputs'][0]['text']=='# Mandatory\nRule body\n'
    assert packet['inputs'][1]['text']=='# Evidence\nFirst body\n'
    assert packet['enforcement_claim'].startswith('none')
    with pytest.raises(PolicyError,match='mandatory content exceeds'): build_packet(repo,p,'root',old,evidence,1)
    (repo/'ctx/evidence.md').write_text('# Evidence\nChanged body\n'); git(repo,'add','.'); git(repo,'commit','-qm','change evidence'); newer=git(repo,'rev-parse','HEAD')
    packet2=build_packet(repo,p,'root',newer,evidence,1000)
    assert packet2['inputs'][1]['sha256'] != packet['inputs'][1]['sha256']
    d=json.loads((repo/'ctx/policy.json').read_text()); d['contexts'][0]['policy']['deny']=['self/evidence.md']; (repo/'ctx/policy.json').write_text(json.dumps(d)); git(repo,'add','.'); git(repo,'commit','-qm','revoke')
    with pytest.raises(PolicyError,match='not current trusted'): load_policy(repo,'HEAD','ctx/policy.json')
    git(repo,'update-ref','refs/remotes/origin/main',git(repo,'rev-parse','HEAD'))
    current=load_policy(repo,'HEAD','ctx/policy.json')
    with pytest.raises(PolicyError,match='denied'): build_packet(repo,current,'root',old,evidence,1000)


def test_blocker_and_proposal_schema():
    b=blocker('read','ctx/a','missing approval','owner','approve exact connection','approval recorded',status='pending')
    result={'schema_version':'wiki.task-result/v1','status':'pending','blockers':[b]}
    validate(result,json.loads((BASE/'docs/references/schemas/wiki-task-result-v1.schema.json').read_text()))
    assert connection_proposal('a','b','ctx/a','interpret','synthetic','2099-01-01')['grants_access'] is False
