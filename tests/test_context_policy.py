import copy
import json
from pathlib import Path
import pytest
import yaml
from jsonschema import validate, ValidationError
from wiki_core.context_policy import ContextPolicy, PolicyError, capability_status, safe_path

BASE = Path(__file__).resolve().parents[1]

def doc():
    contexts=[]
    for p in (BASE/'examples/context-hierarchy').rglob('context.yaml'):
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
    for p in (BASE/'examples/context-hierarchy').rglob('context.yaml'): validate(yaml.safe_load(p.read_text()),schema)
    bad=yaml.safe_load((BASE/'examples/context-hierarchy/context.yaml').read_text()); bad['policy']['magic']=[]
    with pytest.raises(ValidationError): validate(bad,schema)
    p=ContextPolicy(doc(),'sha'); assert capability_status(p,'root','edit',None)=='denied'
