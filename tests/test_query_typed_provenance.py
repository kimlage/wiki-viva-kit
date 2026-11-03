"""Synthetic selective provenance; generic caller-trust reach remains visible."""
import pytest
import yaml
from tests.test_context_dynamic_selection import collection, packet, requirement, commit, ANCHOR
from tests.test_context_flow import repo, git
from wiki_core.config import load_config
from wiki_core.freshness_impact import repository_report


def make_case(root, mode):
    (root/'wiki.config.yaml').write_text('paths:\n  memory_root: finance\naudit:\n  freshness_scope: impact\n  information_impact: use_scoped\n')
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
    return repository_report(root,load_config(root),base,query_context='costs',query_policy_revision=base,query_head=head)


@pytest.mark.parametrize('mode',['legacy_lock','legacy_external','legacy_source_ref','historical','navigation'])
def test_legacy_and_historical_reach_does_not_become_query_authority_blocker(collection,mode):
    report=make_case(collection,mode)
    assert not any(r['reason']=='dynamic_impact_authority_boundary' for r in report['blockers'])
    if mode!='navigation':
        assert any(r['path']==ANCHOR and r['reason']=='information_changed' and not r['verification_performed'] for r in report['pending_reviews'])


def test_explicit_current_consumption_still_blocks_unreadable_source(collection):
    report=make_case(collection,'typed_external')
    assert any(r['path']==ANCHOR and r['reason']=='dynamic_impact_authority_boundary' for r in report['blockers'])


def test_authorized_current_path_survives_unrelated_legacy_cause(collection):
    report=make_case(collection,'typed_plus_legacy')
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


def test_direct_anchor_edit_still_revalidates_the_collection(collection):
    root=collection
    (root/'wiki.config.yaml').write_text('paths:\n  memory_root: finance\naudit:\n  freshness_scope: impact\n  information_impact: use_scoped\n')
    commit(root);p=packet(root)
    (root/'finance/costs/result.md').write_text('---\n'+yaml.safe_dump({'page_id':'consumer','page_type':'claim','information_requirements':[requirement(p)]})+'---\nInterpretation.\n')
    base=commit(root);git(root,'checkout','-qb','wiki/anchor-change');anchor=root/ANCHOR;anchor.write_text(anchor.read_text()+'Updated collection contract.\n');git(root,'add','.');git(root,'commit','-qm','anchor change');head=git(root,'rev-parse','HEAD')
    report=repository_report(root,load_config(root),base,query_context='costs',query_policy_revision=base,query_head=head)
    assert any(r['path']=='finance/costs/result.md' and r['reason']=='dynamic_query_changed' and not r['verification_performed'] for r in report['pending_reviews'])
