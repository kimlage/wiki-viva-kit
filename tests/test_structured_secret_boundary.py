"""Synthetic secrets in structured query and packet boundaries."""
import json
import subprocess
import sys
from pathlib import Path
import pytest
from tests.test_context_flow import repo, git, policy
from tests.test_context_dynamic_selection import collection, query, TASK, commit
from tests.test_coordination_protected import bound_server
from wiki_core.context_packet import build_packet
from wiki_core.context_policy import PolicyError
from wiki_core.detectors import scan_text
from wiki_core.web.admin.sessions import ADMIN_SESSION_HEADER

VALUE='aB3dE9fG2hJ7kL4mN8pQ5rS6tU1vW0xY'  # Synthetic high-entropy value.
ASSIGNMENT='api_key = "'+VALUE+'"'
BEARER='Bearer\n'+VALUE


def request_for(root, kind):
    q=query(); args={'queries':[q], 'omissions':[], 'adapter_report':None}
    if kind=='reason': q['reason']=ASSIGNMENT
    elif kind=='filter': q['query']['filters']={'status':BEARER}
    elif kind=='quoted_filter': q['query']['filters']={'api_key':'"'+VALUE+'"'}
    elif kind=='omission': args['omissions']=[BEARER]
    else: args['adapter_report']={'verification':'verified','capabilities':['network'],'scope':['synthetic'],'limitation':ASSIGNMENT}
    return args


@pytest.mark.parametrize('kind',['reason','filter','quoted_filter','omission','adapter'])
def test_builder_refuses_secret_in_raw_structured_fields(collection,kind):
    assert any(f.category=='secret' for f in scan_text(ASSIGNMENT))
    assert any(f.category=='secret' for f in scan_text(BEARER))
    args=request_for(collection,kind)
    with pytest.raises(PolicyError) as error:
        build_packet(collection,policy(collection),'costs',git(collection,'rev-parse','HEAD'),[],50000,**TASK,**args)
    assert VALUE not in str(error.value)


@pytest.mark.parametrize('kind',['reason','filter','quoted_filter','omission'])
def test_protected_http_refuses_secret_without_echo(collection,bound_server,kind):
    srv,token=bound_server; sha=git(collection,'rev-parse','HEAD'); args=request_for(collection,kind)
    task={**TASK,'max_bytes':50000,'evidence':[], 'queries':args['queries'],'omissions':args['omissions']}
    status,body=srv.post('/api/coordination/protected/packet',{'context_id':'costs','approved_revision':sha,'content_revision':sha,'task':task},headers={ADMIN_SESSION_HEADER:token})
    assert status==409
    assert VALUE not in json.dumps(body) and 'packet' not in body


def test_safe_private_text_remains_available(collection):
    private='Synthetic CPF 529.982.247-25'
    assert any(f.category=='pii' for f in scan_text(private))
    p=build_packet(collection,policy(collection),'costs',git(collection,'rev-parse','HEAD'),[],50000,**TASK,queries=[query()],omissions=[private])
    assert p['coverage']['missing']==[private]


def test_reader_keeps_safe_synthetic_private_field(collection):
    private='Synthetic CPF 529.982.247-25'
    (collection/'finance/costs/private.md').write_text('---\npage_id: synthetic-private\nnote: "'+private+'"\n---\nSafe.\n')
    commit(collection)
    script=Path(__file__).resolve().parents[1]/'scripts/wiki_read.py'
    out=subprocess.run([sys.executable,str(script),'--root',str(collection),'--revision','HEAD','--mode','read','--allow-path','finance/costs/private.md','--ref','finance/costs/private.md','--field','note'],capture_output=True,text=True)
    assert out.returncode==0 and json.loads(out.stdout)['value']==private


def test_cyclic_structured_data_fails_without_echo():
    from wiki_core.detectors import contains_secret_structure
    value=[];value.append(value)
    with pytest.raises(ValueError) as error: contains_secret_structure(value)
    assert str(error.value)=='invalid structured data'
