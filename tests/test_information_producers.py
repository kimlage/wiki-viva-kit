"""Producer declarations track actual output consumption, without age waivers."""
import datetime as dt
import re
import pytest

from wiki_core.config import WikiConfig
from wiki_core.information_relations import authored_graph,dependency_edges
from wiki_core.information_impact import evaluate_information_impact
from wiki_core.input_stage import compile_input_stage,render_input_stage_markdown
from wiki_core.operational_pass import build_operational_pass_page


TODAY=dt.date(2026,10,30)


def test_input_stage_metadata_does_not_consume_source_body_or_unrelated_facts(tmp_path):
    from tests.test_source_review_jobs import fixture
    config,_,_=fixture(tmp_path)
    catalog=compile_input_stage(tmp_path,config,generated_at=TODAY)
    target=tmp_path/'memories/system/input-stage.md';target.parent.mkdir(parents=True)
    target.write_text(render_input_stage_markdown(catalog,config))
    base=authored_graph(tmp_path,config)
    source=tmp_path/'memories/sources/source-a.md'
    source.write_text(source.read_text().replace('# Source A','# Source A\n\nAn unrelated factual detail.'))
    current=authored_graph(tmp_path,config)
    assert render_input_stage_markdown(compile_input_stage(tmp_path,config,generated_at=TODAY),config)==target.read_text()
    report=evaluate_information_impact(current,base,{'memories/sources/source-a.md'},today=TODAY)
    assert 'memories/system/input-stage.md' not in {row['path'] for row in report['included']}
    source.write_text(source.read_text().replace('title: Source A','title: Changed source label'))
    report=evaluate_information_impact(authored_graph(tmp_path,config),base,{'memories/sources/source-a.md'},today=TODAY)
    assert 'memories/system/input-stage.md' in {row['path'] for row in report['included']}


def test_operational_pass_uses_hub_metadata_and_keeps_navigation_separate(tmp_path):
    config=WikiConfig()
    root=tmp_path/'memories/index.md';root.parent.mkdir()
    root.write_text('---\npage_id: root\npage_type: context_note\ntitle: Specific notes\ncontext: system\n'
        'updated_at: 2026-10-30\nstale_after_days: 30\n---\n# Notes\nA preserved observation.\n')
    target=tmp_path/'memories/system/operational-pass.md';target.parent.mkdir()
    rendered=build_operational_pass_page(tmp_path,config,updated_at='2026-10-30')
    target.write_text(rendered);base=authored_graph(tmp_path,config)
    root.write_text(root.read_text().replace('A preserved observation.','A changed observation.'))
    assert build_operational_pass_page(tmp_path,config,updated_at='2026-10-30')==rendered
    report=evaluate_information_impact(authored_graph(tmp_path,config),base,{'memories/index.md'},today=TODAY)
    assert 'memories/system/operational-pass.md' not in {row['path'] for row in report['included']}
    dependencies,navigation=dependency_edges(base)
    assert any(edge['type']=='navigation_link' and edge['path'].endswith('operational-pass.md') for edge in navigation)
    assert any(edge['type']=='projection' and 'updated_at' in edge['consumed_fields'] for edge in dependencies)
    assert all('body' not in edge['consumed_fields'] for edge in dependencies
        if edge['prerequisite']=='memories/index.md' and edge['dependent'].endswith('operational-pass.md'))


@pytest.mark.parametrize('kind',['source','channel','root'])
def test_input_stage_title_fallback_is_an_input_even_without_frontmatter_title(tmp_path,kind):
    from tests.test_input_stage import _fixture_repo
    from wiki_core.paths import WikiPaths
    config=_fixture_repo(tmp_path)
    catalog=compile_input_stage(tmp_path,config,generated_at=TODAY)
    path=(catalog['sources'][0]['source_path'] if kind=='source' else
        catalog['channels'][0]['path'] if kind=='channel' else catalog['root_entity']['path'])
    source=tmp_path/path
    source.write_text(re.sub(r'(?m)^title:.*\n','',source.read_text()))
    target=WikiPaths(tmp_path,config).input_stage_page;target.parent.mkdir(parents=True,exist_ok=True)
    rendered=render_input_stage_markdown(compile_input_stage(tmp_path,config,generated_at=TODAY),config)
    target.write_text(rendered);base=authored_graph(tmp_path,config)
    source.write_text(re.sub(r'(?m)^# .+$','# Renamed synthetic title',source.read_text(),count=1))
    assert render_input_stage_markdown(compile_input_stage(tmp_path,config,generated_at=TODAY),config)!=rendered
    report=evaluate_information_impact(authored_graph(tmp_path,config),base,{path},today=TODAY)
    assert target.relative_to(tmp_path).as_posix() in {row['path'] for row in report['included']}


@pytest.mark.parametrize('page_type',['claim','decision'])
def test_attention_selection_consumes_candidate_body_before_it_is_displayed(tmp_path,page_type):
    config=WikiConfig();memory=tmp_path/'memories';memory.mkdir()
    (memory/'index.md').write_text('---\npage_id: root\npage_type: root_index\ntitle: Root\ncontext: system\n'
        'updated_at: 2026-10-30\nstale_after_days: 30\n---\n# Root\n')
    source=memory/'candidate.md'
    source.write_text('---\npage_id: candidate\npage_type: '+page_type+'\ntitle: Specific observation\n'
        'context: system\nstatus: draft\nupdated_at: 2026-10-30\nstale_after_days: 30\n---\nA complete observation.\n')
    target=memory/'system/operational-pass.md';target.parent.mkdir()
    rendered=build_operational_pass_page(tmp_path,config,updated_at='2026-10-30');target.write_text(rendered)
    base=authored_graph(tmp_path,config)
    source.write_text(source.read_text().replace('A complete observation.','A pending observation.'))
    assert build_operational_pass_page(tmp_path,config,updated_at='2026-10-30')!=rendered
    report=evaluate_information_impact(authored_graph(tmp_path,config),base,{'memories/candidate.md'},today=TODAY)
    assert 'memories/system/operational-pass.md' in {row['path'] for row in report['included']}


def test_projection_selector_is_strict_and_cannot_escape_loaded_inputs():
    from wiki_core.information_relations import projection_input_edges
    spec={'page_types':['claim'],'fields':['title'],'title_fallback':True,'contexts':['system']}
    nodes={'claim.md':{'page_type':'claim'},'other.md':{'page_type':'note','context':'system'}}
    edges=projection_input_edges('projection.md',{'projection_inputs':[spec]},nodes,default_context='system')
    assert len(edges)==1 and edges[0]['target']=='claim.md' and 'body' in edges[0]['consumed_fields']
    for invalid in [{**spec,'unknown':True},{**spec,'path_prefix':'../outside'},
        {**spec,'title_fallback':'true'},{**spec,'fields':[]},{**spec,'fields':[{}]}]:
        with pytest.raises(ValueError):projection_input_edges('projection.md',{'projection_inputs':[invalid]},nodes)


@pytest.mark.parametrize('title_line',['','title: "   "\n'])
def test_blank_input_title_keeps_body_fallback_but_completed_metadata_avoids_unread_body(tmp_path,title_line):
    from tests.test_source_review_jobs import fixture
    config,_,_=fixture(tmp_path);source=tmp_path/'memories/sources/source-a.md'
    source.write_text(source.read_text().replace('title: Source A\n',title_line))
    target=tmp_path/'memories/system/input-stage.md';target.parent.mkdir()
    target.write_text(render_input_stage_markdown(compile_input_stage(tmp_path,config,generated_at=TODAY),config))
    base=authored_graph(tmp_path,config);source.write_text(source.read_text().replace('# Source A','# Changed title'))
    result=evaluate_information_impact(authored_graph(tmp_path,config),base,{'memories/sources/source-a.md'},today=TODAY)
    assert 'memories/system/input-stage.md' in {row['path'] for row in result['included']}


def test_closed_decision_with_explicit_title_does_not_invalidate_operational_pass_for_unread_body(tmp_path):
    config=WikiConfig();memory=tmp_path/'memories';memory.mkdir()
    (memory/'index.md').write_text('---\npage_id: root\npage_type: root_index\ntitle: Root\ncontext: system\n---\n# Root\n')
    source=memory/'closed.md';source.write_text('---\npage_id: closed\npage_type: decision\ntitle: Closed decision\n'
        'status: completed\ncontext: system\nupdated_at: 2026-10-30\n---\nA complete observation.\n')
    target=memory/'system/operational-pass.md';target.parent.mkdir()
    before=build_operational_pass_page(tmp_path,config,updated_at='2026-10-30');target.write_text(before)
    base=authored_graph(tmp_path,config)
    source.write_text(source.read_text().replace('A complete observation.','A pending observation.'))
    assert build_operational_pass_page(tmp_path,config,updated_at='2026-10-30')==before
    report=evaluate_information_impact(authored_graph(tmp_path,config),base,{'memories/closed.md'},today=TODAY)
    assert 'memories/system/operational-pass.md' not in {row['path'] for row in report['included']}


def test_registry_reads_source_metadata_and_config_recipe_but_not_source_body(tmp_path,monkeypatch):
    from scripts import wiki_source_registry as registry
    from tests.test_source_review_jobs import fixture
    from wiki_core.paths import WikiPaths
    config,_,_=fixture(tmp_path);paths=WikiPaths(tmp_path,config);monkeypatch.setattr(registry,'ROOT',tmp_path)
    target=paths.source_registry_page;target.parent.mkdir(parents=True,exist_ok=True)
    before=registry.build_registry(paths,config,'2026-10-30');target.write_text(before)
    base=authored_graph(tmp_path,config);source=tmp_path/'memories/sources/source-a.md'
    source.write_text(source.read_text()+'\nUnrelated source detail.\n')
    assert registry.build_registry(paths,config,'2026-10-30')==before
    report=evaluate_information_impact(authored_graph(tmp_path,config),base,{'memories/sources/source-a.md'},today=TODAY)
    assert paths.rel(target) not in {row['path'] for row in report['included']}
    recipe=tmp_path/'memories/sources/config/source-a.md'
    recipe.write_text(recipe.read_text().replace('cadence_days: 7','cadence_days: 14'))
    assert registry.build_registry(paths,config,'2026-10-30')!=before
    report=evaluate_information_impact(authored_graph(tmp_path,config),base,{'memories/sources/config/source-a.md'},today=TODAY)
    assert paths.rel(target) in {row['path'] for row in report['included']}


@pytest.mark.parametrize('kind',['legacy_decision','terminal_action'])
def test_operation_candidate_selection_and_terminal_body_precision(tmp_path,kind):
    from scripts.wiki_operation_compile import build_page
    from wiki_core.paths import WikiPaths
    config=WikiConfig();paths=WikiPaths(tmp_path,config)
    if kind=='legacy_decision':
        source=paths.decisions_dir/'candidate.md';content='page_type: decision\n'
        body='# Candidate\n\nEstado: completed\n'
    else:
        source=paths.actions_dir/'candidate.md';content='page_type: action\naction_state: done\n'
        body='# Candidate\n\nA complete observation.\n'
    source.parent.mkdir(parents=True);source.write_text('---\npage_id: candidate\ncontext: system\n'+content+'---\n'+body)
    target=paths.operation_page;target.parent.mkdir(parents=True,exist_ok=True)
    now=dt.datetime(2026,10,30)
    rendered=build_page(tmp_path,config,generated_at=now);target.write_text(rendered)
    base=authored_graph(tmp_path,config)
    source.write_text(source.read_text().replace('completed','pending').replace('A complete observation.','A pending observation.'))
    changed=build_page(tmp_path,config,generated_at=now)!=rendered
    report=evaluate_information_impact(authored_graph(tmp_path,config),base,{paths.rel(source)},today=TODAY)
    included=paths.rel(target) in {row['path'] for row in report['included']}
    assert changed==included==(kind=='legacy_decision')


def test_explicit_config_input_is_not_a_memory_page_or_permission(tmp_path):
    from tests.test_source_review_jobs import fixture
    from wiki_core.freshness_impact import repository_report
    from tests.test_freshness_impact import git
    config,_,_=fixture(tmp_path)
    target=tmp_path/'memories/system/input-stage.md';target.parent.mkdir()
    target.write_text(render_input_stage_markdown(compile_input_stage(tmp_path,config,generated_at=TODAY),config))
    git(tmp_path,'add','.');git(tmp_path,'commit','-m','Publish projection')
    base=git(tmp_path,'rev-parse','HEAD').strip()
    cfg=tmp_path/'wiki.config.yaml';cfg.write_text(cfg.read_text()+'\n# changed selected configuration\n')
    report=repository_report(tmp_path,config,base,today=TODAY)
    assert 'memories/system/input-stage.md' in {row['path'] for row in report['included']}
