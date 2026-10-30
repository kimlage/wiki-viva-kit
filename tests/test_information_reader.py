"""The human reader explains the same scopes without acquiring source access."""
import datetime as dt

from tests.test_freshness_impact import commit
from tests.test_source_review_jobs import fixture
from wiki_core.web.content import build_page_content
from wiki_core.web.snapshot import _pages_payload


def snapshot(root,config):
    return {'pages.json':_pages_payload(root,config,today=dt.date(2026,10,30)),
        'manifest.json':{'snapshot_id':'synthetic','generated_at':'2026-10-30T12:00:00Z'},'graph.json':{}}


def test_reader_reports_actual_requirement_date_scope_and_reason_without_refresh(tmp_path):
    config,_,_=fixture(tmp_path);before={p:p.read_bytes() for p in tmp_path.rglob('*.md')}
    result=build_page_content(tmp_path,config,'action',snapshot(tmp_path,config),include_information=True)
    assessment=result['information_use'];row=assessment['requirements'][0]
    assert not assessment['ready'] and assessment['permission_granted'] is False
    assert row['target']=='memories/index.md' and row['fields']==['body']
    assert row['verified_at']=='2026-01-01' and row['temporal']=='current'
    assert row['blockers']==['information_verification_expired']
    assert assessment['assessed_at']=='2026-10-30T12:00:00+00:00'
    assert before=={p:p.read_bytes() for p in tmp_path.rglob('*.md')}
    assert not (tmp_path/'data').exists()


def test_agent_content_port_does_not_read_requirements_before_authorizing_them(tmp_path,monkeypatch):
    import wiki_core.web.content as content
    config,_,_=fixture(tmp_path);current=snapshot(tmp_path,config)
    def premature(*args,**kwargs):raise AssertionError('Reader assessment must be opt-in')
    monkeypatch.setattr(content,'_reader_information',premature)
    assert 'information_use' not in build_page_content(tmp_path,config,'action',current)


def test_current_requirement_can_be_ready_but_never_grants_permission(tmp_path):
    config,_,_=fixture(tmp_path);claim=tmp_path/'memories/index.md'
    claim.write_text(claim.read_text().replace('verified_at: 2026-01-01','verified_at: 2026-10-30'))
    commit(tmp_path)
    result=build_page_content(tmp_path,config,'action',snapshot(tmp_path,config),include_information=True)['information_use']
    assert result['ready'] and result['permission_granted'] is False


def test_historical_read_preserves_the_observation_without_requesting_current_verification(tmp_path):
    config,_,_=fixture(tmp_path);action=tmp_path/'memories/action.md'
    action.write_text(action.read_text().replace('temporal: current','temporal: historical'))
    commit(tmp_path)
    result=build_page_content(tmp_path,config,'action',snapshot(tmp_path,config),include_information=True)['information_use']
    assert result['ready'] and result['requirements'][0]['verified_at']=='2026-01-01'


def test_changed_evidence_does_not_mix_revisions_in_reader_assessment(tmp_path):
    config,_,_=fixture(tmp_path);current=snapshot(tmp_path,config)
    with (tmp_path/'memories/evidence.md').open('a') as stream:stream.write('Changed after snapshot.\n')
    result=build_page_content(tmp_path,config,'action',current,include_information=True)['information_use']
    assert not result['ready'] and 'snapshot_revision_mismatch' in result['relation_errors']
    assert 'information_evidence_missing' in result['requirements'][0]['blockers']


def test_malformed_requirement_has_a_visible_impediment(tmp_path):
    config,_,_=fixture(tmp_path);action=tmp_path/'memories/action.md'
    action.write_text(action.read_text().replace('target: claim','target: nonexistent'))
    result=build_page_content(tmp_path,config,'action',snapshot(tmp_path,config),include_information=True)['information_use']
    assert not result['ready'] and result['relation_errors']==['information_requirement_invalid']


def test_literal_mention_without_consumption_does_not_claim_readiness(tmp_path):
    config,_,_=fixture(tmp_path);page=tmp_path/'memories/evidence.md'
    page.write_text(page.read_text()+'The operational_prerequisite vocabulary is described elsewhere.\n')
    result=build_page_content(tmp_path,config,'evidence',snapshot(tmp_path,config),include_information=True)
    assert 'information_use' not in result
