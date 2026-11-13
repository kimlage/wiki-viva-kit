"""Public synthetic regressions for reference identity and newly merged history."""
import datetime as dt

import pytest

from tests.test_navigation_migration import repo, move, sha, audit_action
from tests.test_freshness_impact import page, commit, git
from tests.test_action_transition import _write_action
from wiki_core.action_transition import (
    _parse_document, reconcile_action_navigation, transition_action_page,
    validate_action_transition_diffs,
)
from wiki_core.config import load_config
from wiki_core.freshness_impact import repository_report
from wiki_core.graph.page_graph import build_page_graph
from wiki_core.information_relations import authored_graph
from wiki_core.navigation import NavigationHistory
from wiki_core.web.snapshot import build_snapshot


@pytest.mark.parametrize('temporal', ['current', 'historical'])
@pytest.mark.parametrize('relocated', [False, True])
def test_requirement_pin_never_binds_a_different_occupant(repo, temporal, relocated):
    guide = page(repo, 'guide')
    pin = commit(repo)
    record = page(repo, 'record', stale=True, information_requirements=[dict(
        target='memories/guide.md', fields=['body'], temporal=temporal,
        max_age_days=30, consumed_revision=pin)])
    original = record.read_bytes()
    commit(repo)
    if relocated:
        move(repo, 'memories/guide.md', 'memories/navigation/guide.md')
    guide.write_text('---\npage_id: replacement\n---\nA different identity.\n')
    commit(repo)
    cfg = load_config(repo)
    assert authored_graph(repo, cfg)['errors']
    # A new blob cannot lend an old pin to the replacement either.
    record.write_bytes(original + b'\nNewly authored note.\n')
    commit(repo)
    assert authored_graph(repo, cfg)['errors']
    if relocated:
        git(repo, 'checkout', '-qb', 'future')
        target = repo / 'memories/navigation/guide.md'
        target.write_bytes(target.read_bytes() + b'\nChanged original fact.\n')
        assert not repository_report(repo, cfg, 'main', today=dt.date(2026, 11, 12))['ok']


def test_explicit_current_reconciliation_keeps_original_pin(repo):
    page(repo, 'guide')
    pin = commit(repo)
    record = page(repo, 'record', stale=True, information_requirements=[dict(
        target='memories/guide.md', fields=['body'], temporal='current',
        max_age_days=30, consumed_revision=pin)])
    commit(repo)
    move(repo, 'memories/guide.md', 'memories/navigation/guide.md'); commit(repo)
    record.write_bytes(record.read_bytes().replace(b'target: memories/guide.md',
                                                  b'target: memories/navigation/guide.md'))
    commit(repo)
    graph = authored_graph(repo, load_config(repo))
    assert not graph['errors']
    edge = next(e for e in graph['edges'] if e['field'] == 'information_requirements')
    assert edge['target'] == 'memories/navigation/guide.md'
    assert edge['requirement']['consumed_revision'] == pin
    git(repo, 'checkout', '-qb', 'future')
    target = repo / edge['target']; target.write_bytes(target.read_bytes() + b'\nNew fact.\n')
    impact = repository_report(repo, load_config(repo), 'main', today=dt.date(2026, 11, 12))
    assert any(b['path'] == 'memories/record.md' for b in impact['blockers'])


def test_historical_requirement_projects_its_actual_origin_without_rewriting_pin(repo):
    page(repo, 'guide'); pin = commit(repo)
    record = page(repo, 'record', information_requirements=[dict(target='memories/guide.md',
        fields=['body'], temporal='historical', max_age_days=30, consumed_revision=pin)])
    original = record.read_bytes(); origin = commit(repo)
    move(repo, 'memories/guide.md', 'memories/navigation/guide.md'); commit(repo)
    graph = authored_graph(repo, load_config(repo))
    assert not graph['errors']
    edge = next(e for e in graph['edges'] if e['field'] == 'information_requirements')
    requirement = edge['requirement']
    assert requirement['consumed_revision'] == pin
    assert requirement['historical_target'] == 'memories/guide.md'
    assert requirement['relocation_provenance']['source_revision'] == origin
    assert requirement['relocation_provenance']['source_path'] == 'memories/record.md'
    assert record.read_bytes() == original


@pytest.mark.parametrize('href', ['../docs/reference.md', 'never-existed.md'])
def test_ineligible_target_does_not_trigger_page_lineage_work(repo, monkeypatch, href):
    record = page(repo, 'record', body=f'[Artifact]({href})\n')
    commit(repo)
    history = NavigationHistory(repo)
    def forbidden(*args, **kwargs):
        pytest.fail('an origin without a coexisting memory target cannot prove an alias')
    monkeypatch.setattr(history, 'continuous', forbidden)
    assert history.resolve('memories/record.md', record.read_bytes().decode(),
                           href, href=True) is None
    assert 'parents' not in history.__dict__


def test_dated_nonmemory_artifact_does_not_scan_page_ancestry(repo):
    entry = '## [2026-07-10] Old\n\n[Artifact](../docs/reference.md)\n'
    record = page(repo, 'record', body='# Log\n\n' + entry)
    commit(repo)
    record.write_bytes(record.read_bytes() + b'\n## [2026-07-11] New\n\nNew record.\n')
    commit(repo)
    history = NavigationHistory(repo)
    raw = record.read_bytes().decode()
    offset = _parse_document(raw)[1].index('[Artifact]')
    assert history.resolve('memories/record.md', raw, '../docs/reference.md',
                           href=True, body_offset=offset) is None
    assert 'parents' not in history.__dict__


@pytest.mark.parametrize('dated', [False, True])
def test_source_move_cannot_capture_a_page_from_an_artifact_occurrence(repo, dated):
    (repo / 'guide.md').write_text('# A distinct public synthetic artifact\n')
    page(repo, 'guide', body='A different memory page.\n')
    occurrence = '[Evidence](../guide.md)\n'
    entry = '## [2026-07-10] Old\n\n' + occurrence
    record = page(repo, 'record', body='# Log\n\n' + entry if dated else occurrence)
    commit(repo)
    move(repo, 'memories/record.md', 'memories/nested/record.md'); commit(repo)
    record = repo / 'memories/nested/record.md'
    if dated:
        record.write_bytes(record.read_bytes().replace(entry.encode(),
            ('## [2026-07-11] New\n\nA new record.\n\n' + entry).encode()))
        commit(repo)
    raw = record.read_bytes().decode(); offset = _parse_document(raw)[1].index('[Evidence]')
    assert not NavigationHistory(repo).existing_reference_safe('memories/nested/record.md',
        raw, '../guide.md', href=True, body_offset=offset)
    assert authored_graph(repo, load_config(repo))['errors']


@pytest.mark.parametrize('action_page', [False, True])
@pytest.mark.parametrize('collision', [False, True])
def test_source_move_cannot_change_an_unchanged_relative_occurrence(repo, action_page, collision):
    page(repo, 'index')
    page(repo, 'guide', body='Original evidence.\n')
    if collision:
        page(repo, 'nested/guide', body='Different evidence.\n')
    if action_page:
        source = _write_action(repo)
        source.write_bytes(source.read_bytes() + b'\n[Evidence](../guide.md)\n')
        href = '../guide.md'
        dest = 'memories/nested/actions/action-synthetic-review.md'
    else:
        source = page(repo, 'record', stale=True, body='[Evidence](guide.md)\n')
        href = 'guide.md'
        dest = 'memories/nested/record.md'
    before = source.read_bytes().decode(); original_ref = source.relative_to(repo).as_posix()
    base = commit(repo); git(repo, 'checkout', '-qb', 'proposal')
    move(repo, original_ref, dest); commit(repo)
    source = repo / dest
    nav = NavigationHistory(repo)
    assert nav.existing_reference_safe(dest, before, href, href=True) == (not collision)
    cfg = load_config(repo)
    graph = authored_graph(repo, cfg)
    assert bool(graph['errors']) == collision
    node = build_page_graph(repo, cfg).nodes[dest]
    assert 'memories/nested/guide.md' not in node.outbound_body_links
    snapshot = build_snapshot(repo, cfg, generated_at='2026-11-12T12:00:00Z')
    assert not any(e['provenance']['path'] == dest and e['target'] == 'nested/guide'
                   for e in snapshot['graph.json']['edges'])
    if action_page:
        assert bool(validate_action_transition_diffs(repo, dest, original_ref, before, before, base)) == collision
    git(repo, 'checkout', '-q', 'main'); git(repo, 'merge', '--ff-only', 'proposal')
    git(repo, 'checkout', '-qb', 'future')
    guide = repo / 'memories/guide.md'; guide.write_bytes(guide.read_bytes() + b'\nChanged fact.\n')
    assert not repository_report(repo, cfg, 'main', today=dt.date(2026, 11, 12))['ok']
    if collision:
        source.write_bytes(source.read_bytes() + b'\nExplicitly authored at this location.\n')
        commit(repo)
        assert not authored_graph(repo, cfg)['errors']
        assert 'memories/nested/guide.md' in build_page_graph(repo, cfg).nodes[dest].outbound_body_links


@pytest.mark.parametrize('detour', [False, True])
@pytest.mark.parametrize('fork_before_base', [False, True])
def test_bridge_proves_new_side_branch_edges_without_reauditing_approved_history(
        repo, monkeypatch, fork_before_base, detour):
    page(repo, 'guide')
    action = _write_action(repo)
    action.write_bytes(action.read_bytes() + b'\n[Evidence](../guide.md)\n')
    before = action.read_bytes().decode(); early = commit(repo)
    (repo / 'approved.txt').write_text('Already approved unrelated history.\n')
    base = commit(repo)
    git(repo, 'checkout', '-qb', 'side', early if fork_before_base else base)
    if detour:
        action.write_text(before.replace('attention_basis: Synthetic transition coverage.',
                                         'attention_basis: Unreceipted factual detour.'))
        commit(repo)
        action.write_bytes(before.encode()); commit(repo)
    else:
        (repo / 'side.txt').write_text('Clean independent change.\n'); commit(repo)
    git(repo, 'checkout', '-q', 'main'); git(repo, 'checkout', '-qb', 'proposal')
    move(repo, 'memories/guide.md', 'memories/navigation/guide.md'); commit(repo)
    _, body = _parse_document(before)
    reconcile_action_navigation(repo, action, body.replace('../guide.md', '../navigation/guide.md'),
                                expected_sha256=sha(action))
    stage = commit(repo)
    transition_action_page(repo, action, 'open', page_edit={'title': 'Reviewed title'},
                           expected_sha256=sha(action), recorded_at='2026-07-12T12:00:00Z')
    commit(repo); git(repo, 'merge', '--no-ff', '-qm', 'Real synthetic merge', 'side')
    ref = action.relative_to(repo).as_posix()
    diagnostics = validate_action_transition_diffs(repo, ref, ref, before, action.read_bytes().decode(), base)
    assert bool(diagnostics) == detour
    assert bool(audit_action(repo, monkeypatch)) == detour
    assert git(repo, 'rev-parse', 'main') == base
    assert git(repo, 'merge-base', '--is-ancestor', stage, 'HEAD') == ''


@pytest.mark.parametrize('case', ['original', 'prepend', 'new_occurrence', 'reorder', 'changed_record',
                                  'role', 'pin', 'revert', 'missing_tree', 'source_copy', 'reoccupied'])
def test_historical_directory_address_is_occurrence_evidence_not_page_alias(repo, monkeypatch, case):
    import scripts.wiki_audit as audit
    from wiki_core.markdown_link_roles import declare_link_role

    page(repo, 'old-domain/source/reconciliation/item')
    link = '[Directory](old-domain/source/reconciliation/)'
    if case == 'role':
        link = declare_link_role(link, 'review_record')
    entry = '## [2026-07-10] Old\n\n' + link + '\n\n'
    older = '## [2026-07-09] Earlier\n\nEarlier.\n'
    if case == 'missing_tree':
        (repo / 'memories/old-domain/source/reconciliation/item.md').unlink()
        (repo / 'memories/old-domain/source/reconciliation').rmdir()
    log = page(repo, 'record', body='# Log\n\n' + entry + older, consumed_revision='a' * 40)
    origin = commit(repo)
    if case != 'missing_tree':
        move(repo, 'memories/old-domain/source/reconciliation/item.md', 'memories/current/item.md')
        (repo / 'memories/old-domain/source/reconciliation').rmdir()
        commit(repo)
    if case in {'prepend', 'new_occurrence', 'reorder', 'changed_record', 'role', 'pin', 'revert'}:
        new = '## [2026-07-11] New\n\n' + ('[Directory](old-domain/source/reconciliation/)' if case == 'new_occurrence' else 'New.') + '\n\n'
        original = log.read_bytes()
        if case == 'reorder':
            log.write_bytes(original.replace((entry + older).encode(), (older + '\n' + entry).encode()))
        elif case == 'changed_record':
            log.write_bytes(original.replace(b'Old\n', b'Altered\n'))
        elif case == 'role':
            log.write_bytes(original.replace(b'review_record', b'factual_support'))
        elif case == 'pin':
            log.write_bytes(original.replace(b'a' * 40, b'b' * 40))
        elif case == 'revert':
            log.write_bytes(original.replace(b'Old\n', b'Detour\n')); commit(repo)
            log.write_bytes(original.replace(entry.encode(), (new + entry).encode()))
        else:
            log.write_bytes(original.replace(entry.encode(), (new + entry).encode()))
        commit(repo)
    elif case == 'source_copy':
        log.with_name('copy.md').write_bytes(log.read_bytes())
        commit(repo)
    elif case == 'reoccupied':
        page(repo, 'old-domain/source/reconciliation/other')
        commit(repo)
    raw = log.read_bytes().decode(); body = _parse_document(raw)[1]
    offset = body.index('[Directory]')
    nav = NavigationHistory(repo)
    ref = 'old-domain/source/reconciliation/'
    proof = nav.historical_directory('memories/record.md', raw, ref, body_offset=offset)
    if case in {'original', 'prepend'}:
        assert proof['historical_directory'] == 'memories/old-domain/source/reconciliation'
        assert proof['current_target'] is None
        assert proof['source_revision'] == origin
        assert nav.resolve('memories/record.md', raw, ref, href=True, body_offset=offset) is None
    else:
        assert proof is None
    monkeypatch.setattr(audit, 'ROOT', repo)
    monkeypatch.setattr(audit, 'link_audit_files', lambda config: ['memories/record.md'])
    errors = []
    audit.audit_clickable_local_links(errors, load_config(repo))
    assert bool(errors) == (case not in {'original', 'prepend'})


def test_directory_href_moved_source_does_not_capture_new_occupant(repo, monkeypatch):
    import scripts.wiki_audit as audit
    page(repo, 'old-domain/old-child')
    page(repo, 'nested/old-domain/unrelated-child')
    record = page(repo, 'record', body='# Record\n\n[Directory](old-domain/)\n')
    commit(repo)
    move(repo, 'memories/record.md', 'memories/nested/record.md'); commit(repo)
    record = repo / 'memories/nested/record.md'
    raw = record.read_bytes().decode(); body = _parse_document(raw)[1]
    nav = NavigationHistory(repo)
    assert not nav.existing_reference_safe('memories/nested/record.md', raw, 'old-domain/',
                                           href=True, body_offset=body.index('[Directory]'))
    monkeypatch.setattr(audit, 'ROOT', repo)
    monkeypatch.setattr(audit, 'link_audit_files', lambda config: ['memories/nested/record.md'])
    errors = []
    audit.audit_clickable_local_links(errors, load_config(repo))
    assert errors
    record.write_bytes(record.read_bytes() + b'\nA deliberately new reference at this location.\n')
    commit(repo)
    raw = record.read_bytes().decode(); body = _parse_document(raw)[1]
    assert NavigationHistory(repo).existing_reference_safe('memories/nested/record.md', raw, 'old-domain/',
                                                           href=True, body_offset=body.index('[Directory]'))


@pytest.mark.parametrize('href', ['../old-domain/', '../old-domain/source/reconciliation/'])
def test_historical_directory_from_nested_record_survives_promotion_without_page_exemption(repo, monkeypatch, href):
    import scripts.wiki_audit as audit
    page(repo, 'old-domain/source/reconciliation/item')
    record = page(repo, 'nested/record', body='# Log\n\n## [2026-07-10] Old\n\n[Directory](' + href + ')\n')
    commit(repo)
    git(repo, 'checkout', '-qb', 'migration')
    move(repo, 'memories/old-domain/source/reconciliation/item.md', 'memories/current/item.md')
    for dirname in ['reconciliation', 'source', 'old-domain']:
        location = next(p for p in (repo / 'memories/old-domain', repo / 'memories/old-domain/source',
                                      repo / 'memories/old-domain/source/reconciliation') if p.name == dirname)
        location.rmdir()
    commit(repo)
    git(repo, 'checkout', '-q', 'main'); git(repo, 'merge', '--ff-only', 'migration')
    git(repo, 'checkout', '-qb', 'future')
    record.write_bytes(record.read_bytes() + b'\n## [2026-07-11] New\n\nNew entry.\n')
    commit(repo)
    raw = record.read_bytes().decode(); body = _parse_document(raw)[1]
    nav = NavigationHistory(repo)
    assert nav.historical_directory('memories/nested/record.md', raw, href,
                                    body_offset=body.index('[Directory]'))['current_target'] is None
    monkeypatch.setattr(audit, 'ROOT', repo)
    monkeypatch.setattr(audit, 'link_audit_files', lambda config: ['memories/nested/record.md'])
    errors = []; audit.audit_clickable_local_links(errors, load_config(repo)); assert not errors
    page(repo, 'requires-page', information_requirements=[dict(target='memories/old-domain',
         fields=['body'], temporal='historical', max_age_days=30, consumed_revision=git(repo, 'rev-parse', 'main'))])
    assert authored_graph(repo, load_config(repo))['errors']


def test_historical_directory_does_not_renew_occurrence_from_later_blob_count_events(repo):
    record = page(repo, 'record', body='# Log\n\n## [2026-07-10] Old\n\n[Directory](old-domain/)\n')
    commit(repo)  # The address did not exist when the occurrence was authored.
    page(repo, 'old-domain/item'); commit(repo)
    copy = repo / 'memories/copy.md'; copy.write_bytes(record.read_bytes()); commit(repo)
    copy.unlink(); commit(repo)  # A find-object event, not a new occurrence.
    (repo / 'memories/old-domain/item.md').unlink()
    (repo / 'memories/old-domain').rmdir(); commit(repo)
    raw = record.read_bytes().decode(); body = _parse_document(raw)[1]
    assert NavigationHistory(repo).historical_directory('memories/record.md', raw, 'old-domain/',
                                                        body_offset=body.index('[Directory]')) is None
