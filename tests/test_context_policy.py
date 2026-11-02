import copy
import json
from pathlib import Path
import pytest
from jsonschema import validate, ValidationError
from wiki_core.context_policy import ContextPolicy, PolicyError, capability_status, load_policy

BASE = Path(__file__).resolve().parents[1]


def doc(): return json.loads((BASE/'examples/context-hierarchy/hierarchy.json').read_text())


def test_nested_self_inheritance_and_no_sibling_access():
    p = ContextPolicy(doc(), 'approved')
    assert p.permits('finance/tax','read','examples/context-hierarchy/finance/tax/a.md')
    assert not p.permits('finance/tax','read','examples/context-hierarchy/finance/costs/a.md')
    assert not p.permits('finance/companies/example','read','examples/context-hierarchy/company/a.md')
    assert p.effective['finance/tax']['capabilities'] == []


def test_widening_deny_and_bad_parent():
    d=doc(); d['contexts'][2]['policy']['read']=['examples/context-hierarchy/company']
    with pytest.raises(PolicyError, match='widens'): ContextPolicy(d,'sha')
    d=doc(); d['contexts'][1]['policy']['deny']=['self/tax/secret']
    p=ContextPolicy(d,'sha')
    assert not p.permits('finance/tax','read','examples/context-hierarchy/finance/tax/secret/a')
    d=doc(); d['contexts'][1]['parent']='finance/tax'
    with pytest.raises(PolicyError): ContextPolicy(d,'sha')
    d=doc(); d['contexts'][1]['policy']['superuser']=True
    with pytest.raises(PolicyError): ContextPolicy(d,'sha')
    d=doc(); d['contexts'][1]['root']='../escape'
    with pytest.raises(PolicyError): ContextPolicy(d,'sha')


def test_connections_exact_double_approval_and_pending():
    d=doc(); a=d['contexts'][1]; b=d['contexts'][2]
    path='examples/context-hierarchy/finance/tax/report.md'
    # The parent finance already has read scope for tax.
    grant={'from_context':'finance/tax','to_context':'finance','selector':path,'section':'Summary','use':'interpret','classification':'synthetic','expires':'2099-01-01'}
    a['imports']=[copy.deepcopy(grant)]
    p=ContextPolicy(d,'sha')
    assert p.connection('finance/tax','finance',path,'interpret','synthetic',section='Summary') == 'pending'
    b['exports']=[copy.deepcopy(grant)]; p=ContextPolicy(d,'sha')
    assert p.connection('finance/tax','finance',path,'interpret','synthetic',section='Summary') == 'approved'
    assert p.connection('finance/tax','finance',path,'interpret','synthetic') == 'pending'
    assert p.connection('finance/tax','company',path,'interpret','synthetic') == 'denied'


def test_schemas_and_capability_no_enforcement_claim():
    schema=json.loads((BASE/'docs/references/schemas/wiki-context-v1.schema.json').read_text())
    validate(doc(),schema)
    bad=doc(); bad['contexts'][0]['policy']['magic']=[]
    with pytest.raises(ValidationError): validate(bad,schema)
    d=doc(); d['contexts'][0]['policy']['capabilities']=['edit']
    p=ContextPolicy(d,'sha')
    assert capability_status(p,'root','edit',None)=='pending'
    assert capability_status(p,'root','edit',{'verification':'verified','capabilities':['edit']})=='pending'
    assert capability_status(p,'root','edit',{'verification':'verified','capabilities':['edit'],'scope':'workspace','limitation':'no network'})=='available'
