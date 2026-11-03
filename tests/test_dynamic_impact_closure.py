"""Synthetic dynamic-to-ordinary impact closure through the real audit entrypoint."""
import json
import subprocess
import sys
from pathlib import Path
import yaml
import pytest
from tests.test_context_dynamic_selection import collection, commit, packet, requirement, page, declare, TASK, SCOPE, ANCHOR
from tests.test_context_flow import repo, git, policy
from wiki_core.config import load_config
from wiki_core.context_packet import build_packet
from wiki_core.freshness_impact import repository_report

KIT=Path(__file__).resolve().parents[1]

def setup_chain(root):
    (root/'wiki.config.yaml').write_text('paths:\n  memory_root: finance\naudit:\n  freshness_scope: impact\n  information_impact: use_scoped\n')
    commit(root)
    p=packet(root); declare(root,requirement(p))
    b=root/TASK['output']; text=b.read_text(); text=text.replace('page_type: claim\n','page_type: claim\nstatus: active\namount: 5\n'); b.write_text(text)
    c=root/'finance/costs/downstream.md'
    values={'page_id':'downstream','page_type':'claim','information_requirements':[{'target':TASK['output'],'fields':['*'],'temporal':'current','max_age_days':30}]}
    c.write_text('---\n'+yaml.safe_dump(values)+'---\nDownstream.\n')
    commit(root)
    q={'target':ANCHOR,'reason':'interpret upstream','use':'interpret','classification':'synthetic','query':{'scope':'finance/costs','filters':{'page_id':'cost-result'},'field':'amount','max_enumerated':30,'max_matches':10,'max_scan_bytes':100000}}
    qp=build_packet(root,policy(root),'costs',git(root,'rev-parse','HEAD'),[],50000,queries=[q],task_id='downstream-query',goal='review',output='finance/costs/query-downstream.md',integrator='reviewer')
    d=root/'finance/costs/query-downstream.md'; d.write_text('---\n'+yaml.safe_dump({'page_id':'query-downstream','page_type':'claim','information_requirements':[requirement(qp)]})+'---\nQuery downstream.\n')
    e=root/'finance/costs/after-query.md'; e.write_text('---\n'+yaml.safe_dump({'page_id':'after-query','page_type':'claim','information_requirements':[{'target':'finance/costs/query-downstream.md','fields':['*'],'temporal':'current','max_age_days':30}]})+'---\nFurther dependent.\n')
    return commit(root)

@pytest.mark.parametrize('change',['addition','removal'])
def test_changed_dynamic_member_reaches_downstream_ordinary_and_query(collection,tmp_path,change):
    base=setup_chain(collection);git(collection,'checkout','-qb','wiki/closure')
    if change=='addition': page(collection,'added.md')
    else: (collection/SCOPE/'first.md').unlink()
    git(collection,'add','.');git(collection,'commit','-qm','change input');head=git(collection,'rev-parse','HEAD')
    report=repository_report(collection,load_config(collection),base,query_context='costs',query_policy_revision=base,query_head=head)
    reasons={r['path']:r['reason'] for r in report['pending_reviews']}
    assert TASK['output'] in reasons
    assert reasons['finance/costs/downstream.md']=='upstream_interpretation_pending'
    assert reasons['finance/costs/query-downstream.md']=='dynamic_query_upstream_pending'
    assert reasons['finance/costs/after-query.md']=='upstream_interpretation_pending'
    assert all(r.get('verification_performed') is False for r in report['pending_reviews'] if r['path'] in (TASK['output'],'finance/costs/downstream.md','finance/costs/query-downstream.md'))
    if change=='removal': return
    out=tmp_path/'cli-report.json'
    script="import sys; from pathlib import Path; import scripts.wiki_audit as a; a.ROOT=Path(sys.argv.pop(1)); sys.argv[0]='wiki_audit.py'; raise SystemExit(a.main())"
    proc=subprocess.run([sys.executable,'-c',script,str(collection),'--check','--only','freshness_budget','--freshness-base',base,'--query-context','costs','--query-policy-revision',base,'--query-head',head,'--freshness-report',str(out)],cwd=KIT,text=True,capture_output=True)
    assert proc.returncode==0,proc.stdout+proc.stderr
    cli=json.loads(out.read_text()); assert 'finance/costs/downstream.md' in {r['path'] for r in cli['pending_reviews']}


def test_typed_cycle_field_scope_and_limit_are_bounded(collection):
    from wiki_core.information_impact import propagate_pending_dependencies
    p=policy(collection)
    def edge(source,target,consumed,produced,kind='operational_prerequisite',temporal='current'):
        return {'source':source,'target':target,'type':kind,'consumed_fields':consumed,'produced_fields':produced,'requirement':{'fields':consumed,'temporal':temporal}}
    a='finance/costs/result.md'; b='finance/costs/other.md'; c='finance/costs/third.md'
    graph={'edges':[edge(b,a,['amount'],['field:status']),edge(a,b,['status'],['field:amount']),edge(c,b,['unrelated'],['body']),edge(c,b,['status'],['body'],temporal='historical')]}
    fields,reached,denied=propagate_pending_dependencies(graph,{'edges':[]},{a:{'amount'}},p,'costs')
    assert fields=={a:{'amount'},b:{'status'}} and reached=={b:a} and not denied
    with pytest.raises(ValueError,match='closure limit'): propagate_pending_dependencies(graph,{'edges':[]},{a:{'amount'}},p,'costs',limit=1)
    with pytest.raises(ValueError,match='closure limit'): propagate_pending_dependencies({'edges':[]},{'edges':[]},{a:{'*'},b:{'*'}},p,'costs',limit=1)
    sections={'edges':[edge(b,a,['amount'],['section:summary']),edge(c,b,['section:summary'],['body'])]}
    fields,_,_=propagate_pending_dependencies(sections,{'edges':[]},{a:{'amount'}},p,'costs')
    assert fields[b]=={'body'} and fields[c]=={'body'}


def test_cross_context_or_denied_destination_is_visible_boundary(collection):
    from wiki_core.information_impact import propagate_pending_dependencies
    p=policy(collection); a='finance/costs/result.md'; protected='finance/tax/interpretation.md'
    graph={'edges':[{'source':protected,'target':a,'type':'operational_prerequisite','requirement':{'fields':['*'],'temporal':'current'}}]}
    fields,reached,denied=propagate_pending_dependencies(graph,{'edges':[]},{a:{'*'}},p,'costs')
    assert fields=={a:{'*'}} and not reached and denied=={a} and protected not in str(denied)


def test_policy_change_remains_requalification_not_fact_change(collection):
    base=setup_chain(collection);git(collection,'checkout','-qb','wiki/policy-closure')
    (collection/'rules.md').write_text('Updated synthetic rule\n');git(collection,'add','.');git(collection,'commit','-qm','policy change');head=git(collection,'rev-parse','HEAD')
    report=repository_report(collection,load_config(collection),base,query_context='costs',query_policy_revision=base,query_head=head)
    rows=[r for r in report['pending_reviews'] if r['path']==TASK['output']]
    assert any(r['reason']=='dynamic_query_requalification_required' and r['verification_performed'] is False for r in rows)
    assert not report['blockers']


def test_unrelated_pending_field_does_not_invalidate_query(collection):
    from wiki_core.dynamic_query_audit import revalidate_affected
    from wiki_core.information_relations import authored_graph, information_requirements
    base=setup_chain(collection); graph=authored_graph(collection,load_config(collection))
    path='finance/costs/query-downstream.md'
    req=information_requirements(graph['nodes'][path],lambda ref:[ref])[0]
    rows=[{'path':path,'requirement':req,'origin':'current'}]
    params={'base':base,'head':base,'context_id':'costs','affected':rows,'changed':set(),'current':graph}
    assert revalidate_affected(collection,**params,pending_sources={TASK['output']:{'unrelated'}})==[]
    result=revalidate_affected(collection,**params,pending_sources={TASK['output']:{'amount'}})
    assert result[0]['reason']=='dynamic_query_upstream_pending'
    limited=revalidate_affected(collection,**params,pending_sources={TASK['output']:{'amount'}},read_budget=[0])
    assert limited[0]['state']=='unknown'
