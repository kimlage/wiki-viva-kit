"""Synthetic reproduction of cross-domain freshness amplification."""
import datetime as dt
from wiki_core.information_impact import evaluate_information_impact
from wiki_core.freshness_impact import evaluate_impact

TODAY = dt.date(2026, 10, 30)

def graph():
    nodes = {p: {'updated_at': '2026-01-01', 'stale_after_days': 10}
             for p in ['action', 'queue', 'panel', 'review', *[f'source{i}' for i in range(12)]]}
    nodes['action']['updated_at'] = '2026-10-30'
    edges = [dict(source='queue', target='action', type='projection_state'),
             dict(source='panel', target='queue', type='markdown_link'),
             dict(source='review', target='panel', type='review_record')]
    edges += [dict(source='action', target=f'source{i}', type='source_ref') for i in range(12)]
    return {'nodes': nodes, 'documents': {p: '---\naction_state: open\n---\nBody\n' for p in nodes},
            'edges': [dict(e, path=e['source'], field='body') for e in edges], 'errors': []}

def test_metadata_projection_does_not_import_unconsumed_sources():
    base=graph(); current=graph(); current['documents']['action']=base['documents']['action'].replace('open','done')
    new=evaluate_information_impact(current,base,{'action'},today=TODAY)
    old=evaluate_impact(current,base,{'action'},today=TODAY)
    assert len(old['blockers']) >= 12
    assert not new['integrity_blockers']
    assert {x['path'] for x in new['included']} == {'action','queue','panel'}
    assert all(not x['verification_performed'] for x in new['pending_reviews'])

def test_body_edit_does_not_change_projected_action_state():
    base=graph(); current=graph();current['documents']['action'] += 'Another fact.'
    new=evaluate_information_impact(current,base,{'action'},today=TODAY)
    assert [x['path'] for x in new['included']] == ['action']

def test_factual_source_change_reaches_its_consumers_but_not_siblings():
    base=graph();current=graph();current['documents']['source0'] += 'New observation.'
    result=evaluate_information_impact(current,base,{'source0'},today=TODAY)
    assert {x['path'] for x in result['included']} == {'source0','action','queue','panel'}
    assert 'review' not in {x['path'] for x in result['included']}

def test_missing_required_artifact_still_blocks_integrity():
    current=graph();current['missing_evidence']={'source0'}
    result=evaluate_information_impact(current,graph(),{'action'},today=TODAY)
    assert result['integrity_blockers'] == [{'path':'source0','reason':'missing_evidence'}]
    assert not result['ok']

def test_parallel_consumptions_are_preserved_and_cycles_terminate():
    base=graph();current=graph()
    # Two distinct meanings between the same endpoints must coexist. A
    # projection is narrow, while another factual occurrence consumes all.
    current['edges'] += [dict(source='queue', target='action', type='markdown_link', path='queue', field='body'),
                         dict(source='action', target='panel', type='markdown_link', path='action', field='body')]
    base['edges']=list(current['edges'])
    current['documents']['action']=current['documents']['action'].replace('open','done')
    result=evaluate_information_impact(current,base,{'action'},today=TODAY)
    reversed_graph={**current,'edges':list(reversed(current['edges']))}
    other=evaluate_information_impact(reversed_graph,base,{'action'},today=TODAY)
    fields=lambda report:{r['path']:r['fields'] for r in report['included']}
    assert fields(result)==fields(other)
    queue=next(r for r in result['included'] if r['path']=='queue')
    assert {r['type'] for r in queue['causes']} == {'projection_state','markdown_link'}
    assert fields(result)['queue']==['*']

def test_projected_output_is_not_an_action_state_of_the_collection():
    base=graph();current=graph()
    for g in (base,current):
        g['edges'].append(dict(source='review',target='queue',type='projection_state',path='review',field='body'))
    current['documents']['action']=current['documents']['action'].replace('open','done')
    result=evaluate_information_impact(current,base,{'action'},today=TODAY)
    assert 'review' not in {r['path'] for r in result['included']}

def test_editing_a_consumer_does_not_discharge_its_incoming_obligation():
    base=graph();current=graph();current['nodes']['action']['updated_at']='2026-10-30'
    current['documents']['action'] += 'Unrelated spelling edit.'
    current['documents']['source0'] += 'Changed fact.'
    result=evaluate_information_impact(current,base,{'action','source0'},today=TODAY)
    row=next(r for r in result['pending_reviews'] if r['path']=='action')
    assert row['reason']=='information_changed' and row['causes']

def test_requirement_contract_rejects_ambiguity_and_unknown_keys():
    import pytest
    from wiki_core.information_relations import information_requirements
    entry={'target':'claim','fields':['body'],'temporal':'current','max_age_days':1}
    resolve=lambda ref:['memories/claim.md']
    assert information_requirements({'information_requirements':[entry]},resolve)[0]['target']=='memories/claim.md'
    for value in [{**entry,'surprise':True},{**entry,'max_age_days':True},{**entry,'fields':['body','body']}, {**entry,'temporal':'whatever'}]:
        with pytest.raises(ValueError):information_requirements({'information_requirements':[value]},resolve)
    with pytest.raises(ValueError):information_requirements({'information_requirements':[entry]},lambda ref:[])
    with pytest.raises(ValueError):information_requirements({'information_requirements':[entry]},lambda ref:['a','b'])

def test_authored_inventory_keeps_navigation_and_factual_occurrences(tmp_path):
    from wiki_core.config import load_config
    from wiki_core.information_relations import authored_graph, dependency_edges
    from wiki_core.markdown_link_roles import declare_link_role
    import yaml
    (tmp_path/'wiki.config.yaml').write_text('paths:\n  memory_root: memories\n')
    (tmp_path/'memories').mkdir()
    values={'page_id':'consumer','page_type':'project','updated_at':'2026-10-30','stale_after_days':30}
    body=declare_link_role('[Browse](target.md)','navigation')+'\n\nSupported by [Fact](target.md).\n'
    (tmp_path/'memories/consumer.md').write_text('---\n'+yaml.safe_dump(values)+'---\n'+body)
    (tmp_path/'memories/target.md').write_text('---\n'+yaml.safe_dump({**values,'page_id':'target'})+'---\nA fact.\n')
    g=authored_graph(tmp_path,load_config(tmp_path));deps,context=dependency_edges(g)
    assert any(e['type']=='navigation_link' for e in context)
    assert any(e['type']=='markdown_link' and e['dependent']=='memories/consumer.md' for e in deps)


def test_dates_in_shadow_diagnostics_are_serializable():
    import json
    g=graph();g['nodes']['queue']['updated_at']=dt.date(2026,1,1)
    g['documents']['action']=g['documents']['action'].replace('open','done')
    result=evaluate_information_impact(g,graph(),{'action'},today=TODAY)
    assert json.loads(json.dumps(result))['schema_version']=='wiki_information_impact.v1'

def test_git_backed_scoped_audit_has_one_authority_and_no_age_waiver(tmp_path,monkeypatch):
    from tests.test_freshness_impact import page,commit,git
    from wiki_core.config import load_config
    from wiki_core.freshness_impact import repository_report
    from scripts import wiki_audit as audit
    import pytest
    (tmp_path/'wiki.config.yaml').write_text('audit:\n  freshness_scope: impact\n  information_impact: use_scoped\n')
    git(tmp_path,'init','-q');git(tmp_path,'config','user.name','Synthetic');git(tmp_path,'config','user.email','fixture@example.invalid')
    p=page(tmp_path,'action',stale=False,body='Technical state.',action_state='open')
    page(tmp_path,'old',stale=True,body='Preserved unrelated history.')
    base=commit(tmp_path);p.write_text(p.read_text().replace('action_state: open','action_state: done'))
    config=load_config(tmp_path)
    report=repository_report(tmp_path,config,base,today=TODAY)
    assert report['ok'] and report['blockers']==[]
    with pytest.raises(ValueError,match='does not accept'):
        repository_report(tmp_path,config,base,today=TODAY,documentary_only={'memories/action.md':'A waiver'})
    monkeypatch.setattr(audit,'ROOT',tmp_path)
    ctx=audit.AuditContext(config);ctx.freshness_base=base
    audit._run_impact_check(ctx);before=(list(ctx.errors),list(ctx.warnings))
    audit._run_freshness_check(ctx)
    assert (ctx.errors,ctx.warnings)==before and ctx.information_audited

def test_projection_declaration_preserves_exact_field_scope(tmp_path):
    from wiki_core.markdown_link_roles import declare_projection, parse_role_markdown, project_link_role
    link=declare_projection('[Queue item](task.md)',consumes=['action_state','next_action'],produces=['body','collection'])
    tokens,roles=parse_role_markdown(link)
    assert len(roles)==1
    role=next(iter(roles.values()));assert role['consumed_fields']==['action_state','next_action']
    edge=project_link_role({'source':'queue','target':'task','type':'markdown_link'},role)
    from wiki_core.information_relations import dependency_edges
    dependencies,_=dependency_edges({'edges':[edge]})
    assert dependencies[0]['consumed_fields']==['action_state','next_action']
    assert dependencies[0]['produced_fields']==['body','collection']
    assert not parse_role_markdown(link.replace('Queue item','Changed label'))[1]
