import json
import subprocess
import sys
from pathlib import Path
import pytest
import yaml
from jsonschema import validate
from wiki_core.context_policy import ContextPolicy, PolicyError, load_policy
from wiki_core.context_packet import build_packet, blocker, connection_proposal, validate_result

BASE=Path(__file__).resolve().parents[1]
TASK={'task_id':'test-1','goal':'review evidence','output':'report','integrator':'operator'}
EVIDENCE=[{'ref':'ctx/evidence.md','producer':'root','reason':'direct evidence','use':'interpret','classification':'synthetic'}]
def git(root,*args): return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()
def approve(root): git(root,'update-ref','refs/remotes/origin/main',git(root,'rev-parse','HEAD'))
@pytest.fixture
def repo(tmp_path):
    git(tmp_path,'init','-q'); git(tmp_path,'config','user.email','synthetic@example.invalid'); git(tmp_path,'config','user.name','Synthetic')
    (tmp_path/'ctx').mkdir(); (tmp_path/'ctx/rules.md').write_text('# Mandatory\nRule body\n'); (tmp_path/'ctx/evidence.md').write_text('# Evidence\nFirst body\n')
    d={'schema_version':'wiki.context/v1','id':'root','parent':None,'root':'ctx','purpose':'Synthetic','owner':'operator','instructions':['ctx/rules.md'],'skills':[],'templates':[],'policy':{'read':['self'],'write':[],'capabilities':[],'publication':[],'deny':{}},'imports':[],'exports':[]}
    (tmp_path/'ctx/context.yaml').write_text(yaml.safe_dump(d)); git(tmp_path,'add','.'); git(tmp_path,'commit','-qm','initial'); approve(tmp_path)
    return tmp_path

def load(repo,rev='HEAD'): return load_policy(repo,rev,'ctx/context.yaml')
def pack(repo,p,rev,evidence=EVIDENCE,budget=10000,**kwargs): return build_packet(repo,p,'root',rev,evidence,budget,**TASK,**kwargs)

def test_packet_bodies_digest_budget_revocation_and_proposed_branch(repo):
    old=git(repo,'rev-parse','HEAD'); p=load(repo,old); packet=pack(repo,p,old)
    validate(packet,json.loads((BASE/'docs/references/schemas/wiki-task-context-v1.schema.json').read_text()))
    assert packet['inputs'][0]['text']=='# Mandatory\nRule body\n'
    assert packet['inputs'][1]['text']=='# Evidence\nFirst body\n'
    assert packet['enforcement_claim'].startswith('none') and packet['coverage']['complete'] is False
    with pytest.raises(PolicyError,match='mandatory content exceeds'): pack(repo,p,old,budget=1)
    with pytest.raises(PolicyError,match='dynamic query'): pack(repo,p,old,query_fingerprint='fake')
    (repo/'ctx/evidence.md').write_text('# Evidence\nChanged body\n'); git(repo,'add','.'); git(repo,'commit','-qm','change evidence'); newer=git(repo,'rev-parse','HEAD')
    packet2=pack(repo,p,newer); assert packet2['inputs'][1]['sha256']!=packet['inputs'][1]['sha256'] and packet2['packet_digest']!=packet['packet_digest']
    d=yaml.safe_load((repo/'ctx/context.yaml').read_text()); d['policy']['deny']={'read':['self/evidence.md']}; (repo/'ctx/context.yaml').write_text(yaml.safe_dump(d)); git(repo,'add','.'); git(repo,'commit','-qm','revoke')
    with pytest.raises(PolicyError,match='not current trusted'): load(repo)
    approve(repo)
    with pytest.raises(PolicyError,match='not current trusted'): pack(repo,p,old)
    with pytest.raises(PolicyError,match='denied'): pack(repo,load(repo),old)

def test_unbound_duplicate_yaml_symlink_and_changed_rule(repo):
    p=load(repo); old=git(repo,'rev-parse','HEAD'); first=pack(repo,p,old)
    (repo/'ctx/rules.md').write_text('# Mandatory\nChanged rule\n'); git(repo,'add','.'); git(repo,'commit','-qm','change rule'); approve(repo)
    with pytest.raises(PolicyError): pack(repo,p,old)
    second=pack(repo,load(repo),old); assert first['inputs'][0]['sha256']!=second['inputs'][0]['sha256']
    d=yaml.safe_load((repo/'ctx/context.yaml').read_text()); d.pop('schema_version')
    with pytest.raises(PolicyError,match='unbound'): pack(repo,ContextPolicy({'schema_version':'wiki.context/v1','contexts':[d]},'x'),old)
    (repo/'ctx/context.yaml').write_text('schema_version: wiki.context/v1\nschema_version: wiki.context/v1\n'); git(repo,'add','.'); git(repo,'commit','-qm','duplicate'); approve(repo)
    with pytest.raises(PolicyError,match='duplicate'): load(repo)
    (repo/'ctx/context.yaml').unlink(); (repo/'ctx/context.yaml').symlink_to('rules.md'); git(repo,'add','.'); git(repo,'commit','-qm','symlink'); approve(repo)
    with pytest.raises(PolicyError,match='unsafe'): load(repo)

def test_blocker_and_proposal_schema():
    b=blocker('read','ctx/a','missing approval','owner','approve exact connection','approval recorded')
    result={'schema_version':'wiki.task-result/v1','status':'pending','blockers':[b], 'task_id':'test-1', 'context_id':'root', 'packet_digest':'a'*64, 'changes':[], 'read_coverage':{'observed_refs':[], 'missing':[]}}
    validate(result,json.loads((BASE/'docs/references/schemas/wiki-task-result-v1.schema.json').read_text()))
    assert connection_proposal('a','b','ctx/a','interpret','synthetic','2099-01-01')['grants_access'] is False
    with pytest.raises(PolicyError): connection_proposal('a','b','ctx/a','interpret','synthetic','2099-01-01',section='x',field='y')

def test_root_dot_mandatory_ancestor_and_narrow_metadata(repo):
    old=git(repo,'rev-parse','HEAD')
    # Promote the hierarchy root to repository root and add a child with no
    # read grant on the mandatory root instruction.
    d=yaml.safe_load((repo/'ctx/context.yaml').read_text()); d['root']='.'; d['instructions']=['rules.md']; d['policy']['read']=['self']; (repo/'rules.md').write_text('root rule\n')
    (repo/'ctx/context.yaml').unlink(); (repo/'context.yaml').write_text(yaml.safe_dump(d))
    child={'schema_version':'wiki.context/v1','id':'child','parent':'root','root':'ctx','purpose':'child','owner':'operator','instructions':[],'skills':[],'templates':[],'policy':{'read':['self']},'imports':[],'exports':[]}
    (repo/'ctx/context.yaml').write_text(yaml.safe_dump(child)); (repo/'ctx/evidence.md').write_text('---\npage_id: evidence\nsecret: hidden metadata\n---\n<!-- wiki:section id=summary version=1 -->\n# Summary\nVisible content\n')
    git(repo,'add','.'); git(repo,'commit','-qm','root and child'); approve(repo)
    policy=load_policy(repo,'HEAD'); ref=git(repo,'rev-parse','HEAD')
    e=[{'ref':'ctx/evidence.md','producer':'child','reason':'selected','use':'interpret','classification':'synthetic','section':'summary'}]
    result=build_packet(repo,policy,'child',ref,e,10000,**TASK)
    assert result['inputs'][0]['text']=='root rule\n'
    assert 'hidden metadata' not in json.dumps(result)
    e[0]['field']='secret'
    with pytest.raises(PolicyError,match='selector'): build_packet(repo,policy,'child',ref,e,10000,**TASK)

def test_cli_refuses_new_packets_from_legacy_manifest(repo, tmp_path):
    script=BASE/'scripts/wiki_context.py'; sha=git(repo,'rev-parse','HEAD')
    prefix=[sys.executable,str(script),'--repo',str(repo),'--approved-revision',sha,'--manifest','ctx/context.yaml']
    request=tmp_path/'request.json'; request.write_text(json.dumps({**TASK,'evidence':EVIDENCE,'max_bytes':10000}))
    result=subprocess.run(prefix+['pack','root','--content-revision',sha,'--request',str(request)], capture_output=True)
    assert result.returncode != 0


def test_result_binding_and_report_validation(repo):
    p=load(repo); sha=git(repo,'rev-parse','HEAD'); packet=pack(repo,p,sha)
    result={'schema_version':'wiki.task-result/v1','status':'completed','blockers':[], 'task_id':packet['task_id'], 'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'], 'changes':[], 'read_coverage':{'observed_refs':packet['declared_read_set'], 'missing':[]}}
    assert validate_result(result,packet)
    with pytest.raises(PolicyError,match='bound'): validate_result({**result,'task_id':'other'},packet)
    with pytest.raises(PolicyError,match='invalid task result'): validate_result({'schema_version':'wiki.task-result/v1','status':'completed','blockers':[]},packet)
    with pytest.raises(PolicyError,match='bound'): validate_result(result,{**packet,'goal':'changed'})
    bad_coverage={**result, 'read_coverage':{'observed_refs':[{'ref':'ctx/other','section':None,'field':None,'revision':sha}], 'missing':[]}}
    with pytest.raises(PolicyError,match='undeclared reads'): validate_result(bad_coverage,packet)
    invalid={'verification':'verified','capabilities':'edit','scope':['ctx/a'],'limitation':'none'}
    with pytest.raises(PolicyError,match='invalid adapter report'): pack(repo,p,sha,adapter_report=invalid)


def test_mandatory_grant_empty_read_deny_and_proposal(repo):
    root=yaml.safe_load((repo/'ctx/context.yaml').read_text())
    child={'schema_version':'wiki.context/v1','id':'child','parent':'root','root':'ctx/child','purpose':'child','owner':'operator','instructions':[],'skills':[],'templates':[],'policy':{'read':[]},'imports':[],'exports':[]}
    (repo/'ctx/child').mkdir(); (repo/'ctx/child/context.yaml').write_text(yaml.safe_dump(child)); (repo/'ctx/child/data.md').write_text('data')
    git(repo,'add','.'); git(repo,'commit','-qm','child'); approve(repo); sha=git(repo,'rev-parse','HEAD'); p=load(repo)
    result=build_packet(repo,p,'child',sha,[],10000,**TASK)
    assert [x['ref'] for x in result['inputs']]==['ctx/rules.md']
    ev=[{'ref':'ctx/child/data.md','producer':'child','reason':'evidence','use':'interpret','classification':'synthetic'}]
    with pytest.raises(PolicyError,match='denied'): build_packet(repo,p,'child',sha,ev,10000,**TASK)
    # An unapproved change cannot replace the ancestor rule.
    (repo/'ctx/rules.md').write_text('unapproved replacement'); git(repo,'add','.'); git(repo,'commit','-qm','proposal')
    assert build_packet(repo,p,'child','HEAD',[],10000,**TASK)['inputs'][0]['text']=='# Mandatory\nRule body\n'
    with pytest.raises(PolicyError,match='not current trusted'): load(repo)
    child['policy']['deny']={'read':['ctx/rules.md']}; (repo/'ctx/child/context.yaml').write_text(yaml.safe_dump(child)); git(repo,'add','.'); git(repo,'commit','-qm','deny rule'); approve(repo)
    with pytest.raises(PolicyError,match='read denied'): build_packet(repo,load(repo),'child','HEAD',[],10000,**TASK)
    # A child cannot designate a sibling's content as a mandatory rule.
    sibling={'schema_version':'wiki.context/v1','id':'sibling','parent':'root','root':'ctx/sibling','purpose':'sibling','owner':'operator','instructions':[],'skills':[],'templates':[],'policy':{},'imports':[],'exports':[]}
    (repo/'ctx/sibling').mkdir(); (repo/'ctx/sibling/context.yaml').write_text(yaml.safe_dump(sibling)); (repo/'ctx/sibling/rule.md').write_text('sibling rule')
    child['policy']['deny']={}; child['instructions']=['ctx/sibling/rule.md']; (repo/'ctx/child/context.yaml').write_text(yaml.safe_dump(child)); git(repo,'add','.'); git(repo,'commit','-qm','foreign rule'); approve(repo)
    with pytest.raises(PolicyError,match='belongs to another context'): load(repo)

def test_secret_blocked_in_historical_evidence_and_rules_without_disclosure(repo):
    synthetic_secret='AKIA'+'IOSFODNN7EXAMPLE'
    (repo/'ctx/evidence.md').write_text('Historical content: '+synthetic_secret+'\n')
    git(repo,'add','.'); git(repo,'commit','-qm','historical evidence'); historic=git(repo,'rev-parse','HEAD')
    (repo/'ctx/evidence.md').write_text('clean current content\n'); git(repo,'add','.'); git(repo,'commit','-qm','clean evidence'); approve(repo)
    policy=load(repo)
    with pytest.raises(PolicyError,match='secret detected') as error: pack(repo,policy,historic)
    assert synthetic_secret not in str(error.value)
    (repo/'ctx/rules.md').write_text('Rule contains '+synthetic_secret+'\n'); git(repo,'add','.'); git(repo,'commit','-qm','sensitive rule'); approve(repo)
    with pytest.raises(PolicyError,match='secret detected') as error: pack(repo,load(repo),historic,evidence=[])
    assert synthetic_secret not in str(error.value)


def test_private_pii_allowed_and_adapter_credentials_blocked(repo):
    # A synthetic CPF-shaped value is not an access secret.
    (repo/'ctx/evidence.md').write_text('CPF 529.982.247-25\n'); git(repo,'add','.'); git(repo,'commit','-qm','private example'); approve(repo)
    packet=pack(repo,load(repo),'HEAD')
    assert '529.982.247-25' in packet['inputs'][1]['text']
    credential_url='postgres://example:'+'S3cr3tPass'+'@host/db'
    report={'verification':'verified','capabilities':['read'],'scope':[credential_url],'limitation':'read only'}
    with pytest.raises(PolicyError,match='secret detected') as error: pack(repo,load(repo),'HEAD',adapter_report=report)
    assert credential_url not in str(error.value)
    with pytest.raises(PolicyError,match='invalid adapter report'):
        pack(repo,load(repo),'HEAD',adapter_report={**report,'token':'private'})

def test_budget_counts_complete_canonical_utf8_envelope(repo):
    (repo/'ctx/evidence.md').write_text('# Evidência\nAção e informação: 🎯\n',encoding='utf-8')
    git(repo,'add','.'); git(repo,'commit','-qm','unicode evidence'); approve(repo)
    policy=load(repo); packet=pack(repo,policy,'HEAD',budget=10000)
    encoded=json.dumps(packet,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    assert packet['bytes_used']==len(encoded)
    assert packet['selected_text_bytes']==sum(len(x['text'].encode('utf-8')) for x in packet['inputs'])
    assert packet['selected_text_bytes'] > sum(len(x['text']) for x in packet['inputs'])
    limit=packet['selected_text_bytes']+50
    assert limit < packet['bytes_used']
    with pytest.raises(PolicyError,match='complete packet exceeds'): pack(repo,policy,'HEAD',budget=limit)
