"""The human reader explains the same scopes without acquiring source access."""
import datetime as dt

import pytest

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


def test_requirement_loaded_first_as_an_aliased_evidence_still_expands_its_own_evidence(tmp_path):
    config,_,_=fixture(tmp_path)
    original=(tmp_path/'memories/index.md').read_text().replace('verified_at: 2026-01-01','verified_at: 2026-10-30')
    (tmp_path/'memories/b.md').write_text(original.replace('page_id: claim','page_id: b'))
    (tmp_path/'memories/index.md').write_text(original.replace('memories/evidence.md','b'))
    action=tmp_path/'memories/action.md'
    action.write_text(action.read_text().replace('information_requirements:\n',
        'information_requirements:\n- target: memories/b.md\n  fields: [body]\n  temporal: current\n  max_age_days: 1\n'))
    commit(tmp_path)
    result=build_page_content(tmp_path,config,'action',snapshot(tmp_path,config),include_information=True)['information_use']
    assert result['ready'],result
    assert [row['target'] for row in result['requirements']]==['memories/b.md','memories/index.md']


def test_new_verification_during_coverage_cannot_certify_older_snapshot_metadata(tmp_path,monkeypatch):
    import wiki_core.information_use as information
    config,_,_=fixture(tmp_path);claim=tmp_path/'memories/index.md'
    claim.write_text(claim.read_text().replace('verified_at: 2026-01-01','verified_at: 2026-10-30'))
    commit(tmp_path)
    claim.write_text(claim.read_text().replace('An observed fact.','A changed fact without new verification.'))
    commit(tmp_path);current=snapshot(tmp_path,config)
    before=build_page_content(tmp_path,config,'action',current,include_information=True)['information_use']
    assert not before['ready']
    native=information.bind_verification_coverage
    def concurrent_verification(root,graph):
        claim.write_text(claim.read_text().replace('verified_at: 2026-10-30','verified_at: 2026-10-30T11:00:00Z'))
        commit(root)
        return native(root,graph)
    monkeypatch.setattr(information,'bind_verification_coverage',concurrent_verification)
    result=build_page_content(tmp_path,config,'action',current,include_information=True)['information_use']
    assert not result['ready'] and 'snapshot_revision_mismatch' in result['relation_errors']
    assert result['requirements'][0]['verified_at']=='2026-10-30'


def test_changed_transitive_observation_does_not_inherit_claim_verification(tmp_path):
    config,_,_=fixture(tmp_path)
    original=(tmp_path/'memories/index.md').read_text().replace('verified_at: 2026-01-01','verified_at: 2026-10-30')
    (tmp_path/'memories/b.md').write_text(original.replace('page_id: claim','page_id: b'))
    (tmp_path/'memories/index.md').write_text(original.replace('memories/evidence.md','b'))
    commit(tmp_path)
    assert build_page_content(tmp_path,config,'action',snapshot(tmp_path,config),include_information=True)['information_use']['ready']
    with (tmp_path/'memories/evidence.md').open('a') as stream:stream.write('A changed observation.\n')
    commit(tmp_path)
    result=build_page_content(tmp_path,config,'action',snapshot(tmp_path,config),include_information=True)['information_use']
    assert not result['ready']
    assert 'information_changed_since_verification' in result['requirements'][0]['blockers']


def test_reader_loads_custom_transitive_units_and_rejects_changed_raw_leaf(tmp_path):
    config,_,_=fixture(tmp_path)
    original=(tmp_path/'memories/index.md').read_text().replace('verified_at: 2026-01-01','verified_at: 2026-10-30')
    custom=original.replace('page_type: claim','page_type: synthetic_cost\ninformation_role: factual_unit')
    (tmp_path/'memories/b.md').write_text(custom.replace('page_id: claim','page_id: b'))
    (tmp_path/'memories/index.md').write_text(custom.replace('memories/evidence.md','b'))
    commit(tmp_path)
    def assessment():
        return build_page_content(tmp_path,config,'action',snapshot(tmp_path,config),include_information=True)['information_use']
    assert assessment()['ready']
    raw=tmp_path/'memories/evidence.md';raw.write_text(raw.read_text()+'Changed RAW leaf.\n');commit(tmp_path)
    result=assessment()
    assert not result['ready'] and result['permission_granted'] is False
    assert 'information_changed_since_verification' in result['requirements'][0]['blockers']


def test_reader_custom_cycle_remains_a_cycle(tmp_path):
    config,_,_=fixture(tmp_path)
    original=(tmp_path/'memories/index.md').read_text().replace('verified_at: 2026-01-01','verified_at: 2026-10-30')
    custom=original.replace('page_type: claim','page_type: synthetic_cost\ninformation_role: factual_unit')
    (tmp_path/'memories/b.md').write_text(custom.replace('page_id: claim','page_id: b').replace('memories/evidence.md','claim'))
    (tmp_path/'memories/index.md').write_text(custom.replace('memories/evidence.md','b'))
    commit(tmp_path)
    result=build_page_content(tmp_path,config,'action',snapshot(tmp_path,config),include_information=True)['information_use']
    assert not result['ready']
    assert 'information_evidence_closed_claim_cycle' in result['requirements'][0]['blockers']


@pytest.mark.parametrize('kind', ['frontmatter_missing', 'body_missing', 'body_existing', 'body_reference', 'body_external', 'body_fragment', 'malformed', 'historical'])
def test_reader_marks_unassessed_transitive_requirements_without_opening_targets(tmp_path, monkeypatch, kind):
    import wiki_core.web.content as content
    from wiki_core.markdown_link_roles import declare_link_role

    config, _, _ = fixture(tmp_path)
    claim = tmp_path / 'memories/index.md'
    text = claim.read_text().replace('verified_at: 2026-01-01', 'verified_at: 2026-10-30')
    if kind in ('frontmatter_missing', 'historical'):
        text = text.replace('---\nAn observed fact.',
            'information_requirements:\n- target: missing-synthetic\n  fields: [body]\n  temporal: current\n  max_age_days: 1\n---\nAn observed fact.')
    elif kind == 'malformed':
        text = text.replace('---\nAn observed fact.', 'information_requirements: invalid\n---\nAn observed fact.')
    else:
        link = {'body_reference': '[Required][other]', 'body_external': '[Required](https://example.invalid/source)',
                'body_fragment': '[Required](#section)'}.get(kind, '[Required](other-synthetic.md)')
        text += '\n' + declare_link_role(link, 'operational_prerequisite') + '\n'
        if kind == 'body_reference':
            text += '\n[other]: other-synthetic.md\n'
        if kind == 'body_existing':
            (tmp_path / 'memories/other-synthetic.md').write_text('---\npage_id: other-synthetic\npage_type: note\n---\nSynthetic target.\n')
    claim.write_text(text)
    if kind == 'historical':
        action = tmp_path / 'memories/action.md'
        action.write_text(action.read_text().replace('temporal: current', 'temporal: historical'))
    commit(tmp_path)
    current = snapshot(tmp_path, config)
    original = content.build_page_content
    def bounded(root, cfg, ref, *args, **kwargs):
        assert ref not in ('missing-synthetic', 'memories/missing-synthetic.md', 'memories/other-synthetic.md'), 'transitive target opened'
        return original(root, cfg, ref, *args, **kwargs)
    monkeypatch.setattr(content, 'build_page_content', bounded)
    result = original(tmp_path, config, 'action', current, include_information=True)['information_use']
    assert result['permission_granted'] is False and not result['ready']
    assert result['relation_errors'] == []
    assert 'information_transitive_requirements_not_assessed' in result['requirements'][0]['blockers']


@pytest.mark.parametrize('kind', ['empty', 'citation', 'navigation', 'stale_role', 'conflicting_roles', 'fenced_role'])
def test_reader_does_not_treat_empty_or_nonoperational_links_as_transitive_requirements(tmp_path, kind):
    from wiki_core.markdown_link_roles import declare_link_role

    config, _, _ = fixture(tmp_path)
    claim = tmp_path / 'memories/index.md'
    text = claim.read_text().replace('verified_at: 2026-01-01', 'verified_at: 2026-10-30')
    if kind == 'empty':
        text = text.replace('---\nAn observed fact.', 'information_requirements: []\n---\nAn observed fact.')
    elif kind == 'citation':
        text += '\n[Context](other-synthetic.md)\n'
    elif kind == 'navigation':
        text += '\n' + declare_link_role('[Navigation](other-synthetic.md)', 'navigation') + '\n'
    else:
        link = '[Required](other-synthetic.md)'
        marked = declare_link_role(link, 'operational_prerequisite')
        if kind == 'stale_role':
            text += '\n' + marked.replace('[Required]', '[Changed]') + '\n'
        elif kind == 'conflicting_roles':
            text += '\n' + marked + declare_link_role(link, 'navigation')[len(link):] + '\n'
        else:
            text += '\n```markdown\n' + marked + '\n```\n'
    claim.write_text(text)
    commit(tmp_path)
    result = build_page_content(tmp_path, config, 'action', snapshot(tmp_path, config), include_information=True)['information_use']
    assert result['ready'] and result['permission_granted'] is False
    assert 'information_transitive_requirements_not_assessed' not in result['requirements'][0]['blockers']


def test_reader_detects_unassessed_requirements_in_loaded_evidence_chain(tmp_path):
    config, _, _ = fixture(tmp_path)
    claim = tmp_path / 'memories/index.md'
    original = claim.read_text().replace('verified_at: 2026-01-01', 'verified_at: 2026-10-30')
    intermediate = original.replace('page_id: claim', 'page_id: b').replace('---\nAn observed fact.',
        'information_requirements:\n- target: missing-synthetic\n  fields: [body]\n  temporal: current\n  max_age_days: 1\n---\nAn observed fact.')
    (tmp_path / 'memories/b.md').write_text(intermediate)
    claim.write_text(original.replace('memories/evidence.md', 'b'))
    commit(tmp_path)
    result = build_page_content(tmp_path, config, 'action', snapshot(tmp_path, config), include_information=True)['information_use']
    assert not result['ready'] and result['permission_granted'] is False
    assert 'information_transitive_requirements_not_assessed' in result['requirements'][0]['blockers']
