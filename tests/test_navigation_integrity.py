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
