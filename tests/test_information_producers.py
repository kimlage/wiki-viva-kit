"""Producer declarations track actual output consumption, without age waivers."""
import datetime as dt

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
