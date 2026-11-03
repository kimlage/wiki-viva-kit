import copy
import json
import shutil
import subprocess
from pathlib import Path
import pytest
import yaml
from jsonschema import validate, ValidationError
from wiki_core.context_policy import ContextPolicy, PolicyError, capability_status, safe_path, load_policy

BASE = Path(__file__).resolve().parents[1]

def doc():
    contexts=[]
    for p in (BASE/'examples/context-hierarchy').rglob('context.example.yaml'):
        c=yaml.safe_load(p.read_text()); c.pop('schema_version'); contexts.append(c)
    contexts.sort(key=lambda c: (c['root'].count('/'),c['root']))
    return {'schema_version':'wiki.context/v1','contexts':contexts}

def find(d,id): return next(c for c in d['contexts'] if c['id']==id)

def test_nested_self_inheritance_and_no_sibling_access():
    p=ContextPolicy(doc(),'approved')
    assert p.permits('finance/tax','read','examples/context-hierarchy/finance/tax/a.md')
    assert not p.permits('finance/tax','read','examples/context-hierarchy/finance/costs/a.md')
    assert not p.permits('finance/companies/example','read','examples/context-hierarchy/company/a.md')
    assert p.effective['finance/tax']['capabilities']==[]
    assert p.owner_of('examples/context-hierarchy/finance/tax/a.md')=='finance/tax'

def test_widening_typed_denies_inheritance_and_bad_parent():
    d=doc(); find(d,'finance/tax')['policy']['read']=['examples/context-hierarchy/company']
    with pytest.raises(PolicyError,match='widens'): ContextPolicy(d,'sha')
    d=doc(); find(d,'root')['policy']['capabilities']=['production.deploy','repository.merge']; find(d,'root')['policy']['publication']=['public']; find(d,'finance')['policy']['deny']={'read':['self/tax/secret'],'capabilities':['production.deploy'],'publication':['public']}
    p=ContextPolicy(d,'sha')
    assert not p.permits('finance/tax','read','examples/context-hierarchy/finance/tax/secret/a')
    report={'verification':'verified','capabilities':['production.deploy','repository.merge'],'scope':['workspace'],'limitation':'no network'}
    assert capability_status(p,'finance/tax','production.deploy',report,target='workspace')=='denied'
    assert capability_status(p,'finance/tax','repository.merge',report,target='workspace')=='available'
    assert capability_status(p,'finance/tax','repository.merge',report) == 'pending'
    assert capability_status(p,'finance/tax','repository.merge',report,target='workspace/repo') == 'pending'
    assert capability_status(p,'finance/tax','repository.merge',{**report, 'capabilities':'repository.merge'},target='workspace') == 'pending'
    assert capability_status(p,'finance/tax','repository.merge',{**report, 'scope':'workspace'},target='workspace') == 'pending'
    assert capability_status(p,'finance/tax','repository.merge',{**report, 'limitation':[]},target='workspace') == 'pending'
    assert not p.permits_effect('finance/tax','publication','public')
    find(d,'finance/tax')['policy']['capabilities']=[]; assert ContextPolicy(d,'sha').effective['finance/tax']['capabilities']==[]
    find(d,'finance')['parent']='missing'
    with pytest.raises(PolicyError): ContextPolicy(d,'sha')
    d=doc(); find(d,'finance')['parent']='finance/tax'
    with pytest.raises(PolicyError): ContextPolicy(d,'sha')
    d=doc(); find(d,'finance')['policy']['superuser']=True
    with pytest.raises(PolicyError): ContextPolicy(d,'sha')
    d=doc(); find(d,'finance')['root']=find(d,'company')['root']
    with pytest.raises(PolicyError): ContextPolicy(d,'sha')
    for path in ['../escape','a/../b','a/\x01b','/absolute','a/*']:
        with pytest.raises(PolicyError): safe_path(path)

def test_connections_exact_double_approval_expiry_and_fake_producer():
    d=doc(); a=find(d,'finance'); b=find(d,'finance/tax'); path='examples/context-hierarchy/finance/tax/report.md'
    grant={'from_context':'finance/tax','to_context':'finance','selector':path,'section':'Summary','use':'interpret','classification':'synthetic','expires':'2099-01-01'}
    a['imports']=[copy.deepcopy(grant)]; p=ContextPolicy(d,'sha')
    assert p.connection('finance/tax','finance',path,'interpret','synthetic',section='Summary')=='pending'
    b['exports']=[copy.deepcopy(grant)]; p=ContextPolicy(d,'sha')
    assert p.connection('finance/tax','finance',path,'interpret','synthetic',section='Summary')=='approved'
    assert p.connection('finance/tax','finance',path,'interpret','synthetic')=='pending'
    assert p.connection('finance','finance',path,'interpret','synthetic')=='denied'
    assert p.connection('finance/tax','company',path,'interpret','synthetic')=='denied'
    a['imports'][0]['expires']=b['exports'][0]['expires']='2000-01-01'; p=ContextPolicy(d,'sha')
    assert p.connection('finance/tax','finance',path,'interpret','synthetic',section='Summary')=='pending'

def test_manifest_schema_and_no_false_capability_proof():
    schema=json.loads((BASE/'docs/references/schemas/wiki-context-v1.schema.json').read_text())
    for p in (BASE/'examples/context-hierarchy').rglob('context.example.yaml'): validate(yaml.safe_load(p.read_text()),schema)
    bad=yaml.safe_load((BASE/'examples/context-hierarchy/context.example.yaml').read_text()); bad['policy']['magic']=[]
    with pytest.raises(ValidationError): validate(bad,schema)
    p=ContextPolicy(doc(),'sha'); assert capability_status(p,'root','edit',None)=='denied'


def test_root_hierarchy_ignores_inert_models_but_rejects_second_active_root(tmp_path):
    def git(*args): return subprocess.check_output(['git','-C',str(tmp_path),*args],stderr=subprocess.PIPE).decode().strip()
    git('init','-q'); git('config','user.name','Synthetic'); git('config','user.email','synthetic@example.invalid')
    shutil.copytree(BASE/'examples/context-hierarchy',tmp_path/'examples/context-hierarchy')
    root={'schema_version':'wiki.context/v1','id':'root','parent':None,'root':'.','purpose':'synthetic','owner':'operator','instructions':[],'skills':[],'templates':[],'policy':{'read':['self'],'write':['self'],'capabilities':[],'deny':{},'publication':[]},'imports':[],'exports':[]}
    (tmp_path/'context.yaml').write_text(yaml.safe_dump(root)); git('add','.'); git('commit','-qm','root with inert examples'); git('update-ref','refs/remotes/origin/main','HEAD')
    assert list(load_policy(tmp_path,'HEAD').contexts)==['root']
    example=tmp_path/'examples/context-hierarchy/context.example.yaml'
    second=yaml.safe_load(example.read_text()); second['id']='other-root'; (example.parent/'context.yaml').write_text(yaml.safe_dump(second)); git('add','.'); git('commit','-qm','second active root'); git('update-ref','refs/remotes/origin/main','HEAD')
    with pytest.raises(PolicyError,match='exactly one root'): load_policy(tmp_path,'HEAD')


def test_models_materialize_in_isolated_synthetic_checkout(tmp_path):
    def git(*args): return subprocess.check_output(['git','-C',str(tmp_path),*args],stderr=subprocess.PIPE).decode().strip()
    git('init','-q'); git('config','user.name','Synthetic'); git('config','user.email','synthetic@example.invalid')
    target=tmp_path/'examples/context-hierarchy'; shutil.copytree(BASE/'examples/context-hierarchy',target)
    for p in target.rglob('context.example.yaml'): p.rename(p.with_name('context.yaml'))
    git('add','.'); git('commit','-qm','materialize synthetic hierarchy'); git('update-ref','refs/remotes/origin/main','HEAD')
    resolved=load_policy(tmp_path,'HEAD','examples/context-hierarchy/context.yaml')
    assert set(resolved.contexts)=={'root','finance','finance/tax','finance/costs','finance/companies','finance/companies/example','company'}
