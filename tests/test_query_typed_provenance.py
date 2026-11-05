"""Synthetic selective provenance; generic caller-trust reach remains visible."""
import pytest
import yaml
from tests.test_context_dynamic_selection import collection, audit_collection, requirement, commit, query, ANCHOR
from tests.test_context_dynamic_selection import configure_audit, folder_packet as packet
from tests.test_context_flow import repo, git
from wiki_core.config import load_config
from wiki_core.freshness_impact import repository_report


def make_case(root, mode, binding='finance/costs', before_report=None):
    configure_audit(root)
    (root/'kit.lock').write_text('synthetic lock 1\n')
    (root/'finance/external.md').write_text('---\npage_id: external\npage_type: claim\n---\nExternal synthetic.\n')
    (root/'finance/costs/local.md').write_text('---\npage_id: local\npage_type: claim\n---\nLocal synthetic.\n')
    fields={'page_id':'cost-collection','page_type':'source_catalog'}
    outside='finance/external.md'; local='finance/costs/local.md'
    if mode == 'legacy_source_ref': fields['source_refs'] = [outside]
    if mode in ('typed_external','historical'):
        fields['information_requirements']=[{'target':outside,'fields':['*'],'temporal':'historical' if mode=='historical' else 'current','max_age_days':30}]
    if mode=='typed_plus_legacy':
        fields['information_requirements']=[{'target':local,'fields':['*'],'temporal':'current','max_age_days':30}]
    if mode=='legacy_lock': body='[Lock](../../kit.lock)\n'
    elif mode=='navigation': body='## Navigation\n\n- [Outside](../external.md)\n'
    elif mode=='legacy_source_ref': body='Legacy source reference.\n'
    else: body='[Outside](../external.md)\n'
    (root/ANCHOR).write_text('---\n'+yaml.safe_dump(fields)+'---\n'+body)
    commit(root); p=packet(root)
    consumer=root/'finance/costs/result.md'
    consumer.write_text('---\n'+yaml.safe_dump({'page_id':'consumer','page_type':'claim','information_requirements':[requirement(p)]})+'---\nQuery interpretation.\n')
    base=commit(root);git(root,'checkout','-qb','wiki/provenance-case')
    if mode=='legacy_lock': (root/'kit.lock').write_text('synthetic lock 2\n')
    else: (root/outside).write_text('---\npage_id: external\npage_type: claim\n---\nExternal changed.\n')
    if mode=='typed_plus_legacy': (root/local).write_text('---\npage_id: local\npage_type: claim\n---\nLocal changed.\n')
    git(root,'add','.');git(root,'commit','-qm','source update');head=git(root,'rev-parse','HEAD')
    if before_report is not None: before_report()
    options = {} if binding is None else {'query_context':binding,'query_policy_revision':base,'query_head':head}
    return repository_report(root,load_config(root),base,**options)


@pytest.mark.parametrize('mode',['legacy_lock','legacy_external','legacy_source_ref','historical','navigation'])
def test_legacy_and_historical_reach_does_not_become_query_authority_blocker(audit_collection,mode):
    report=make_case(audit_collection,mode)
    assert not any(r['reason']=='dynamic_impact_authority_boundary' for r in report['blockers'])
    if mode!='navigation':
        assert any(r['path']==ANCHOR and r['reason']=='information_changed' and not r['verification_performed'] for r in report['pending_reviews'])


def test_explicit_current_consumption_still_blocks_unreadable_source(audit_collection):
    report=make_case(audit_collection,'typed_external')
    assert any(r['path']==ANCHOR and r['reason']=='dynamic_impact_authority_boundary' for r in report['blockers'])


def test_authorized_current_path_survives_unrelated_legacy_cause(audit_collection):
    report=make_case(audit_collection,'typed_plus_legacy')
    assert not any(r['reason']=='dynamic_impact_authority_boundary' for r in report['blockers'])
    assert any(r['path']=='finance/costs/result.md' and r['reason']=='dynamic_query_upstream_pending' and not r['verification_performed'] for r in report['pending_reviews'])


@pytest.mark.parametrize('edge,expected',[
    ({'type':'markdown_link'},False),
    ({'type':'source_ref'},False),
    ({'type':'dependency'},False),
    ({'type':'navigation_link'},False),
    ({'type':'historical_support','authored_role':'historical_support'},False),
    ({'type':'operational_prerequisite','requirement':{'temporal':'historical'}},False),
    ({'type':'operational_prerequisite','requirement':{'temporal':'current'}},True),
    ({'type':'operational_prerequisite','authored_role':'operational_prerequisite'},True),
    ({'type':'projection','field':'projection_inputs'},True),
    ({'type':'projection','authored_role':'projection'},True),
    ({'type':'projection_state','authored_role':'projection_state'},True),
])
def test_only_explicit_current_consumption_seeds_scoped_closure(edge,expected):
    from wiki_core.information_impact import explicit_current_consumption
    assert explicit_current_consumption(edge) is expected


def test_direct_anchor_edit_still_revalidates_the_collection(audit_collection):
    root=audit_collection
    configure_audit(root)
    anchor=root/'finance/costs/catalog.md';anchor.write_text((root/ANCHOR).read_text())
    commit(root);q=query();q['target']='finance/costs/catalog.md';p=packet(root,queries=[q])
    (root/'finance/costs/result.md').write_text('---\n'+yaml.safe_dump({'page_id':'consumer','page_type':'claim','information_requirements':[requirement(p)]})+'---\nInterpretation.\n')
    base=commit(root);git(root,'checkout','-qb','wiki/anchor-change');anchor.write_text(anchor.read_text()+'Updated collection contract.\n');git(root,'add','.');git(root,'commit','-qm','anchor change');head=git(root,'rev-parse','HEAD')
    report=repository_report(root,load_config(root),base,query_context='finance/costs',query_policy_revision=base,query_head=head)
    assert any(r['path']=='finance/costs/result.md' and r['reason']=='dynamic_query_changed' and not r['verification_performed'] for r in report['pending_reviews'])


def test_context_index_used_as_anchor_requires_requalification(audit_collection):
    root=audit_collection
    configure_audit(root);commit(root);p=packet(root)
    (root/'finance/costs/result.md').write_text('---\n'+yaml.safe_dump({'page_id':'consumer','page_type':'claim','information_requirements':[requirement(p)]})+'---\nInterpretation.\n')
    base=commit(root);git(root,'checkout','-qb','wiki/context-index-change')
    anchor=root/ANCHOR;anchor.write_text(anchor.read_text()+'Updated context index.\n')
    git(root,'add','.');git(root,'commit','-qm','context index change');head=git(root,'rev-parse','HEAD')
    report=repository_report(root,load_config(root),base,query_context='finance/costs',query_policy_revision=base,query_head=head)
    assert report['query_revalidation']['affected'] == 1
    assert any(r['path']=='finance/costs/result.md' and r['reason']=='dynamic_query_requalification_required' and not r['verification_performed'] for r in report['pending_reviews'])


@pytest.mark.parametrize('binding',[None,'finance/costs','finance/tax'])
def test_legacy_reach_never_makes_unrelated_context_query_affected(audit_collection,binding,monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    original=RepositoryReader._document
    def guard(reader,path, **kwargs):
        if binding=='finance/tax': assert not path.startswith('finance/costs/'), 'other owner query blob opened'
        return original(reader,path,**kwargs)
    report=make_case(audit_collection,'legacy_lock',binding=binding, before_report=lambda: monkeypatch.setattr(RepositoryReader,'_document',guard))
    assert any(r['path']==ANCHOR and r['reason']=='information_changed' for r in report['pending_reviews'])
    assert not any(r['reason']=='dynamic_query_requires_authorized_revalidation' for r in report['blockers'])


@pytest.mark.parametrize('binding',[None,'finance/tax'])
def test_typed_path_to_query_stays_blocked_without_own_context(audit_collection,binding,monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    original=RepositoryReader._document
    def guard(reader,path, **kwargs):
        if binding=='finance/tax': assert not path.startswith('finance/costs/'), 'other owner query blob opened'
        return original(reader,path,**kwargs)
    report=make_case(audit_collection,'typed_plus_legacy',binding=binding, before_report=lambda: monkeypatch.setattr(RepositoryReader,'_document',guard))
    if binding is None:
        assert any(r['reason']=='dynamic_query_requires_authorized_revalidation' for r in report['blockers'])
    else:
        assert report['query_revalidation']['coverage_limit']=='outside_selected_context_not_assessed'
        assert report['query_revalidation']['affected'] == 0


def test_converging_typed_paths_cannot_hide_unauthorized_upstream(audit_collection):
    root=audit_collection
    configure_audit(root)
    def write_page(path,page_id,reqs,body):
        values={'page_id':page_id,'page_type':'claim'}
        if reqs: values['information_requirements']=[{'target':p,'fields':['*'],'temporal':'current','max_age_days':30} for p in reqs]
        (root/path).write_text('---\n'+yaml.safe_dump(values)+'---\n'+body+'\n')
    local='finance/costs/a-local.md'; outside='finance/external.md'; middle='finance/costs/middle.md'
    write_page(local,'a-local',[],'Local before');write_page(outside,'external',[],'Outside before');write_page(middle,'middle',[outside],'Intermediate')
    anchor=root/ANCHOR;anchor.write_text('---\n'+yaml.safe_dump({'page_id':'cost-collection','page_type':'source_catalog','information_requirements':[{'target':x,'fields':['*'],'temporal':'current','max_age_days':30} for x in (local,middle)]})+'---\nCollection.\n')
    commit(root);p=packet(root);(root/'finance/costs/result.md').write_text('---\n'+yaml.safe_dump({'page_id':'consumer','page_type':'claim','information_requirements':[requirement(p)]})+'---\nInterpretation.\n')
    base=commit(root);git(root,'checkout','-qb','wiki/converging-paths');write_page(local,'a-local',[],'Local after');write_page(outside,'external',[],'Outside after');git(root,'add','.');git(root,'commit','-qm','two source changes');head=git(root,'rev-parse','HEAD')
    report=repository_report(root,load_config(root),base,query_context='finance/costs',query_policy_revision=base,query_head=head)
    assert any(r['path']==ANCHOR and r['reason']=='dynamic_impact_authority_boundary' for r in report['blockers'])


def test_typed_reach_computed_once_in_bound_audit(audit_collection,monkeypatch):
    import wiki_core.information_impact as impact
    calls=[]; original=impact.typed_information_reach
    def counted(*args,**kwargs): calls.append(1); return original(*args,**kwargs)
    monkeypatch.setattr(impact,'typed_information_reach',counted)
    report=make_case(audit_collection,'legacy_lock',binding='finance/costs')
    assert len(calls)==1 and not any(r['reason']=='dynamic_impact_authority_boundary' for r in report['blockers'])


def test_no_queries_skip_typed_reach(monkeypatch):
    import datetime as dt
    import wiki_core.information_impact as impact
    from tests.test_information_impact import graph
    monkeypatch.setattr(impact,'typed_information_reach',lambda *a,**kw: pytest.fail('unnecessary typed traversal'))
    result=impact.evaluate_information_impact(graph(),graph(),{'action'},today=dt.date(2026,11,3))
    assert result['included']
