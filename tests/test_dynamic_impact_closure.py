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
    assert fields=={a:{'amount'},b:{'status'}} and reached[b][0]['prerequisite']==a and not denied
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


def test_ordinary_change_reaches_query_with_unchanged_member(collection):
    root=collection
    (root/'wiki.config.yaml').write_text('paths:\n  memory_root: finance\naudit:\n  freshness_scope: impact\n  information_impact: use_scoped\n')
    source='finance/costs/source.md'; (root/source).write_text('---\npage_id: source\npage_type: claim\n---\nBefore.\n')
    b=root/TASK['output']; b.write_text('---\n'+yaml.safe_dump({'page_id':'ordinary-b','page_type':'claim','amount':5,'information_requirements':[{'target':source,'fields':['*'],'temporal':'current','max_age_days':30}]})+'---\nInterpretation.\n')
    commit(root)
    q={'target':ANCHOR,'reason':'interpret upstream','use':'interpret','classification':'synthetic','query':{'scope':'finance/costs','filters':{'page_id':'ordinary-b'},'field':'amount','max_enumerated':30,'max_matches':10,'max_scan_bytes':100000}}
    qp=build_packet(root,policy(root),'costs',git(root,'rev-parse','HEAD'),[],50000,queries=[q],task_id='q-task',goal='review',output='finance/costs/q.md',integrator='reviewer')
    (root/'finance/costs/q.md').write_text('---\n'+yaml.safe_dump({'page_id':'q','page_type':'claim','information_requirements':[requirement(qp)]})+'---\nQuery dependent.\n')
    base=commit(root);git(root,'checkout','-qb','wiki/ordinary-query');(root/source).write_text('---\npage_id: source\npage_type: claim\n---\nAfter.\n');git(root,'add','.');git(root,'commit','-qm','source update');head=git(root,'rev-parse','HEAD')
    report=repository_report(root,load_config(root),base,query_context='costs',query_policy_revision=base,query_head=head)
    reasons={(r['path'],r['reason']) for r in report['pending_reviews']}
    assert (TASK['output'],'information_changed') in reasons
    assert ('finance/costs/q.md','dynamic_query_upstream_pending') in reasons


def test_selection_proof_reused_without_blob_reads_and_failures_not_cached(collection,monkeypatch):
    from wiki_core.dynamic_query_audit import revalidate_affected
    from wiki_core.information_relations import authored_graph, information_requirements
    from wiki_core.repository_reader import RepositoryReader
    base=setup_chain(collection); graph=authored_graph(collection,load_config(collection));path='finance/costs/query-downstream.md'
    req=information_requirements(graph['nodes'][path],lambda ref:[ref])[0]
    rows=[{'path':path,'requirement':req,'origin':'current'}]
    params={'base':base,'head':base,'context_id':'costs','affected':rows,'changed':set(),'current':graph}
    cache={}; budget=[100000]
    import wiki_core.dynamic_query_audit as qa
    calls=[]; select=qa.select_query
    def counted(*args,**kwargs): calls.append(args[2].revision); return select(*args,**kwargs)
    monkeypatch.setattr(qa,'select_query',counted)
    assert revalidate_affected(collection,**params,read_budget=budget,_selection_cache=cache)==[]
    assert calls==[base]  # Approved base and head are the same SHA.
    before=budget[0]
    monkeypatch.setattr(RepositoryReader,'read',lambda *a,**kw: pytest.fail('successful query proof reread a blob'))
    result=revalidate_affected(collection,**params,pending_sources={TASK['output']:{'amount'}},read_budget=budget,_selection_cache=cache)
    assert result[0]['reason']=='dynamic_query_upstream_pending' and budget[0]==before
    empty={}; monkeypatch.undo()
    assert revalidate_affected(collection,**params,read_budget=[0],_selection_cache=empty)[0]['state']=='unknown'
    assert empty=={}
    old=git(collection,'rev-parse','HEAD^'); git(collection,'update-ref','refs/remotes/origin/main',old)
    with pytest.raises(ValueError): revalidate_affected(collection,**params,read_budget=budget,_selection_cache=cache)


def test_duplicate_edges_do_not_consume_closure_budget_or_hide_distinct_fields(collection):
    from wiki_core.information_impact import propagate_pending_dependencies
    a='finance/costs/result.md';b='finance/costs/other.md'
    edge={'source':b,'target':a,'type':'operational_prerequisite','consumed_fields':['*'],'produced_fields':['amount'],'requirement':{'fields':['*'],'temporal':'current'}}
    fields,_,_=propagate_pending_dependencies({'edges':[edge,edge]},{'edges':[edge,edge]},{a:{'*'}},policy(collection),'costs',limit=2)
    assert fields[b]=={'amount'}
    second={**edge,'produced_fields':['status']}
    fields,_,_=propagate_pending_dependencies({'edges':[edge,second]},{'edges':[edge]},{a:{'*'}},policy(collection),'costs',limit=2)
    assert fields[b]=={'amount','status'}
    _, causes, _=propagate_pending_dependencies({'edges':[edge,second]},{'edges':[edge]},{a:{'*'}},policy(collection),'costs',limit=2)
    assert len(causes[b])==2


def test_equivalent_affected_query_does_not_repeat_or_seed_age_debt(collection,monkeypatch):
    import wiki_core.dynamic_query_audit as qa
    base=setup_chain(collection);git(collection,'checkout','-qb','wiki/irrelevant')
    path=collection/SCOPE/'inactive.md';path.write_text(path.read_text()+'Unselected synthetic text.\n')
    git(collection,'add','.');git(collection,'commit','-qm','irrelevant body');head=git(collection,'rev-parse','HEAD')
    calls=[]; original=qa.revalidate_affected
    def counted(*args,**kwargs): calls.append(1); return original(*args,**kwargs)
    monkeypatch.setattr(qa,'revalidate_affected',counted)
    report=repository_report(collection,load_config(collection),base,query_context='costs',query_policy_revision=base,query_head=head)
    assert len(calls)==1
    assert not any(r['reason'] in ('dynamic_query_changed','dynamic_query_upstream_pending','upstream_interpretation_pending') for r in report['pending_reviews'])


def test_existing_included_fields_expand_without_losing_prior_fields():
    from wiki_core.freshness_impact import _merge_pending_fields
    rows=[{'path':'a','fields':['body']},{'path':'b','fields':['status']}]
    _merge_pending_fields(rows,{'a':{'status'},'b':{'*'}})
    assert rows==[{'path':'a','fields':['body','status']},{'path':'b','fields':['*']}]


def test_shared_query_proof_is_reused_across_distinct_consumers(collection,monkeypatch):
    from wiki_core.dynamic_query_audit import revalidate_affected
    from wiki_core.information_relations import authored_graph, information_requirements
    from wiki_core.repository_reader import RepositoryReader
    setup_chain(collection)
    original='finance/costs/query-downstream.md'; other='finance/costs/shared-query.md'
    (collection/other).write_text((collection/original).read_text().replace('query-downstream','shared-query'))
    base=commit(collection); graph=authored_graph(collection,load_config(collection))
    req=information_requirements(graph['nodes'][original],lambda ref:[ref])[0]
    params={'base':base,'head':base,'context_id':'costs','changed':set(),'current':graph}
    cache={};budget=[100000]
    assert revalidate_affected(collection,**params,affected=[{'path':original,'requirement':req,'origin':'current'}],read_budget=budget,_selection_cache=cache)==[]
    before=budget[0]; reader=RepositoryReader.read
    def guarded(self,ref,*a,**kw):
        assert ref!=ANCHOR and not ref.startswith(SCOPE+'/') and ref!=TASK['output'], 'query blob reread'
        return reader(self,ref,*a,**kw)
    monkeypatch.setattr(RepositoryReader,'read',guarded)
    assert revalidate_affected(collection,**params,affected=[{'path':other,'requirement':req,'origin':'current'}],read_budget=budget,_selection_cache=cache)==[]
    assert budget[0]==before


def test_distinct_query_requirements_retain_separate_pending_causes(collection):
    from wiki_core.frontmatter import parse_frontmatter
    setup_chain(collection); target=collection/'finance/costs/query-downstream.md'
    values,body=parse_frontmatter(target.read_text())
    from copy import deepcopy
    second=deepcopy(values['information_requirements'][0]); second['max_age_days']=31
    values['information_requirements'].append(second)
    target.write_text('---\n'+yaml.safe_dump(values)+'---\n'+body)
    base=commit(collection);git(collection,'checkout','-qb','wiki/distinct-query-reasons')
    page(collection,'added.md');git(collection,'add','.');git(collection,'commit','-qm','new member');head=git(collection,'rev-parse','HEAD')
    report=repository_report(collection,load_config(collection),base,query_context='costs',query_policy_revision=base,query_head=head)
    rows=[r for r in report['pending_reviews'] if r['path']=='finance/costs/query-downstream.md' and r['reason']=='dynamic_query_upstream_pending']
    assert len(rows)==2 and len({r['requirement_id'] for r in rows})==2, (report['pending_reviews'],report['blockers'])


def test_ordinary_seed_does_not_import_unauthorized_provenance(collection):
    root=collection
    (root/'wiki.config.yaml').write_text('paths:\n  memory_root: finance\naudit:\n  freshness_scope: impact\n  information_impact: use_scoped\n')
    source='finance/tax/source.md'; b=root/TASK['output']
    b.write_text('---\n'+yaml.safe_dump({'page_id':'ordinary-b','page_type':'claim','amount':5,'information_requirements':[{'target':source,'fields':['*'],'temporal':'current','max_age_days':30}]})+'---\nInterpretation.\n')
    commit(root)
    q={'target':ANCHOR,'reason':'interpret upstream','use':'interpret','classification':'synthetic','query':{'scope':'finance/costs','filters':{'page_id':'ordinary-b'},'field':'amount','max_enumerated':30,'max_matches':10,'max_scan_bytes':100000}}
    qp=build_packet(root,policy(root),'costs',git(root,'rev-parse','HEAD'),[],50000,queries=[q],task_id='q-task',goal='review',output='finance/costs/q.md',integrator='reviewer')
    (root/'finance/costs/q.md').write_text('---\n'+yaml.safe_dump({'page_id':'q','page_type':'claim','information_requirements':[requirement(qp)]})+'---\nQuery dependent.\n')
    base=commit(root);git(root,'checkout','-qb','wiki/unapproved-provenance');(root/source).write_text('Changed unrelated owner.\n');git(root,'add','.');git(root,'commit','-qm','outside source update');head=git(root,'rev-parse','HEAD')
    report=repository_report(root,load_config(root),base,query_context='costs',query_policy_revision=base,query_head=head)
    assert any(x['reason']=='dynamic_impact_authority_boundary' and x['path']==TASK['output'] for x in report['blockers'])
    assert not any(x['path']=='finance/costs/q.md' and x['reason']=='dynamic_query_upstream_pending' for x in report['pending_reviews'])


def test_existing_narrow_pending_row_widens_after_dynamic_dependency(collection):
    from wiki_core.frontmatter import parse_frontmatter
    setup_chain(collection); consumer=collection/'finance/costs/downstream.md'
    values,body=parse_frontmatter(consumer.read_text())
    values['projection_inputs']=[{'paths':[SCOPE+'/first.md'],'fields':['amount']}]
    consumer.write_text('---\n'+yaml.safe_dump(values)+'---\n'+body)
    base=commit(collection);git(collection,'checkout','-qb','wiki/widen-existing-pending')
    page(collection,'first.md',amount=33);git(collection,'add','.');git(collection,'commit','-qm','change selected field');head=git(collection,'rev-parse','HEAD')
    report=repository_report(collection,load_config(collection),base,query_context='costs',query_policy_revision=base,query_head=head)
    target='finance/costs/downstream.md'
    rows=[r for r in report['pending_reviews'] if r['path']==target and r['reason']=='information_changed']
    included=next(r for r in report['included'] if r['path']==target)
    assert len(rows)==1 and rows[0]['fields']==included['fields']==['*']
    assert {r['prerequisite'] for r in rows[0]['causes']} >= {SCOPE+'/first.md',TASK['output']}
    assert rows[0]['verification_performed'] is False
