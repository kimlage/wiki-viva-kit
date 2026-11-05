"""Synthetic reproduction of cross-domain freshness amplification."""
import datetime as dt
from wiki_core.information_impact import evaluate_information_impact
from wiki_core.freshness_impact import evaluate_impact

TODAY = dt.date(2026, 10, 30)

def test_unchanged_historical_query_is_preserved_without_granting_current_use(monkeypatch):
    from copy import deepcopy
    from pathlib import Path
    from wiki_core.information_impact import affected_dynamic_queries
    from wiki_core.information_relations import operational_consumption_edges
    from wiki_core.information_use import assess_information_use
    from wiki_core.repository_reader import RepositoryReader

    monkeypatch.setattr(RepositoryReader, 'read', lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError('historical body must not be read')))

    requirement = {
        'target': 'archive/index.md', 'fields': ['*'], 'temporal': 'historical', 'max_age_days': 90,
        'consumed_revision': 'a' * 40, 'query_policy_revision': 'b' * 40,
        'use': 'interpretation', 'classification': 'synthetic',
        'authority_digest': 'c' * 64, 'members_digest': 'd' * 64, 'selected_digest': 'e' * 64,
        'query': {'scope': 'archive/items', 'filters': {'status': 'active'},
                  'max_enumerated': 20, 'max_matches': 10, 'max_scan_bytes': 100000},
    }
    edges = operational_consumption_edges(Path('.'), 'consumer.md', {'information_requirements': [requirement]},
                                          '', lambda ref: [ref])
    assert len(edges) == 1
    original = {'edges': edges, 'nodes': {'archive/index.md': {'page_type': 'source_catalog'},
                                           'consumer.md': {'page_type': 'concept'}},
                'documents': {'archive/index.md': 'Synthetic catalog', 'consumer.md': 'Historical note'}, 'errors': []}
    current = deepcopy(original)
    assert affected_dynamic_queries(current, original, {'AGENTS.md'}, set()) == []
    assert affected_dynamic_queries(current, original, {'AGENTS.md'}, set(), legacy_authority_unavailable=True) == []
    report = evaluate_information_impact(current, original, {'AGENTS.md'}, today=TODAY)
    assert not report['integrity_blockers']
    assert any(row['reason'] == 'historical_query_preserved_unverified' and not row['verification_performed']
               for row in report['pending_reviews'])
    for path in ('consumer.md', 'archive/index.md', 'archive/items/member.md'):
        assert affected_dynamic_queries(current, original, {'AGENTS.md', path}, set())
        assert affected_dynamic_queries(current, original, {'AGENTS.md'}, {path})
    altered = deepcopy(current)
    altered['edges'][0]['requirement']['selected_digest'] = 'f' * 64
    assert affected_dynamic_queries(altered, original, {'AGENTS.md'}, set())
    assert affected_dynamic_queries({'edges': []}, original, {'AGENTS.md'}, set())
    incomplete = deepcopy(original)
    del incomplete['edges'][0]['requirement']['authority_digest']
    assert affected_dynamic_queries(incomplete, incomplete, {'AGENTS.md'}, set())
    live = deepcopy(original)
    live['edges'][0]['requirement']['temporal'] = 'current'
    assert affected_dynamic_queries(live, live, {'AGENTS.md'}, set())
    folder = deepcopy(original)
    folder['edges'][0]['requirement'].update(authority_format='folder', entry_folder='archive', entry_index='archive/index.md')
    assert affected_dynamic_queries(folder, folder, {'archive/AGENTS.md'}, set())
    dependent = deepcopy(original)
    reader = {'target': 'consumer.md', 'fields': ['*'], 'temporal': 'current', 'max_age_days': 30}
    dependent['edges'] += operational_consumption_edges(Path('.'), 'reader.md', {'information_requirements': [reader]},
                                                       '', lambda ref: [ref])
    assert affected_dynamic_queries(dependent, dependent, {'AGENTS.md'}, set())
    assert affected_dynamic_queries(dependent, dependent, {'wiki.config.yaml'}, set())
    assert affected_dynamic_queries(dependent, dependent, {'reader.md'}, set())
    query_dependent = deepcopy(original)
    next_query = {**requirement, 'target': 'index.md', 'temporal': 'current',
                  'query': {**requirement['query'], 'scope': '.'}}
    query_dependent['edges'] += operational_consumption_edges(Path('.'), 'reader.md',
        {'information_requirements': [next_query]}, '', lambda ref: [ref])
    assert affected_dynamic_queries(query_dependent, query_dependent, {'AGENTS.md'}, set())
    historical_reader = deepcopy(dependent)
    historical_reader['edges'][-1]['requirement']['temporal'] = 'historical'
    assert not affected_dynamic_queries(historical_reader, historical_reader, set(), set())
    assert affected_dynamic_queries(historical_reader, historical_reader, {'AGENTS.md'}, set())
    assert affected_dynamic_queries(historical_reader, historical_reader, {'AGENTS.md', 'reader.md'}, set())
    historical_reader['nodes']['reader.md'] = {'page_type': 'action', 'action_state': 'open'}
    assert affected_dynamic_queries(historical_reader, historical_reader, {'AGENTS.md'}, set())
    active = deepcopy(original)
    active['nodes']['consumer.md']['action_state'] = 'open'
    assert affected_dynamic_queries(active, active, {'wiki.config.yaml'}, set())
    prior = deepcopy(original)
    prior['nodes']['other.md'] = {'page_type': 'claim'}
    prior['documents']['other.md'] = 'Historical source.'
    earlier = {'target': 'other.md', 'fields': ['*'], 'temporal': 'historical', 'max_age_days': 30}
    prior['edges'] += operational_consumption_edges(Path('.'), 'consumer.md', {'information_requirements': [earlier]},
                                                    '', lambda ref: [ref])
    revised = deepcopy(prior)
    revised['documents']['other.md'] += ' Changed.'
    reached = evaluate_information_impact(revised, prior, {'other.md', 'AGENTS.md'}, today=TODAY)
    assert any(row['path'] == 'consumer.md' and row['reason'] == 'dynamic_query_requires_authorized_revalidation'
               for row in reached['integrity_blockers'])
    outcome = assess_information_use(current, 'consumer.md', now=dt.datetime(2026, 11, 5, tzinfo=dt.timezone.utc))
    assert not outcome['ready']
    assert 'information_query_requires_authorized_revalidation' in outcome['requirements'][0]['blockers']


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


def test_removed_consumer_keeps_change_history_without_queueing_a_nonexistent_reader():
    base=graph();current=graph()
    for key in ['nodes','documents']:current[key].pop('review')
    current['edges']=[edge for edge in current['edges'] if edge['source']!='review']
    result=evaluate_information_impact(current,base,{'review'},today=TODAY)
    assert 'review' in result['seeds']
    assert all(row['path']!='review' for row in result['pending_reviews'])


def test_field_changes_preserve_type_and_absence_instead_of_coercing_them():
    from wiki_core.information_impact import changed_fields
    assert changed_fields('---\nobservation: {flag: false}\n---\n','---\nobservation: {flag: 0}\n---\n')=={'observation'}
    assert changed_fields('---\npage_type: note\nobservation: null\n---\n','---\npage_type: note\n---\n')=={'observation'}

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


def test_typed_section_and_field_requirements_are_conservative_in_legacy_impact():
    base=graph(); current=graph()
    edge={'source':'action','target':'source0','type':'operational_prerequisite','path':'action','field':'information_requirements','requirement':{'fields':['section:amount'],'temporal':'current','max_age_days':1}}
    base['edges']=[edge]; current['edges']=[edge]
    current['documents']['source0']+='Changed body.'
    assert 'action' in {r['path'] for r in evaluate_information_impact(current,base,{'source0'},today=TODAY)['included']}
    edge['requirement']['fields']=['field:action_state']; current['documents']['source0']=base['documents']['source0'].replace('open','done')
    assert 'action' in {r['path'] for r in evaluate_information_impact(current,base,{'source0'},today=TODAY)['included']}
