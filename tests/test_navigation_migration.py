"""Public, entirely synthetic Git histories for physical navigation migration."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import wiki_audit as audit
from tests.test_action_transition import _write_action
from tests.test_freshness_impact import git, commit, page
from tests.test_operational_pass import _hub
from wiki_core.action_transition import (
    ActionTransitionError, _parse_document, _render_document, _receipt_id,
    integrate_action_body, reconcile_action_navigation, transition_action_page,
)
from wiki_core.navigation import NavigationHistory, structural_navigation
from wiki_core.config import load_config
from wiki_core.information_relations import authored_graph
from wiki_core.markdown_link_roles import declare_link_role
from wiki_core.operational_pass import build_operational_pass_page
from wiki_core.freshness_impact import repository_report
from wiki_core.graph.page_graph import build_page_graph
from wiki_core.semantic_inventory import build_semantic_inventory
import datetime as dt


@pytest.fixture
def repo(tmp_path):
    caches = ('_audit_base_ref', '_text_at_audit_base', '_base_action_candidate_texts_by_path',
              '_base_action_texts_by_page_id', '_malformed_base_actions', '_audit_git_inventory',
              'tracked_files', 'parse_frontmatter')
    for name in caches:
        getattr(audit, name).cache_clear()
    git(tmp_path, 'init', '-q', '-b', 'main')
    git(tmp_path, 'config', 'user.email', 'fixture@example.invalid')
    git(tmp_path, 'config', 'user.name', 'Synthetic Fixture')
    (tmp_path / 'wiki.config.yaml').write_text('contexts: example\naudit:\n  freshness_scope: impact\n  freshness_base: main\n')
    yield tmp_path
    for name in caches:
        getattr(audit, name).cache_clear()


def move(root, old, new):
    dest = root / new
    dest.parent.mkdir(parents=True, exist_ok=True)
    git(root, 'mv', old, new)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_action(root, monkeypatch):
    monkeypatch.setattr(audit, 'ROOT', root)
    for name in ('_audit_base_ref', '_base_action_candidate_texts_by_path', '_base_action_texts_by_page_id', '_malformed_base_actions'):
        getattr(audit, name).cache_clear()
    errors = []
    audit.audit_action_state_transitions(errors)
    return errors


def test_unchanged_historical_references_survive_move_merge_and_future_proposal(repo, monkeypatch):
    page(repo, 'source-synthetic')
    target = page(repo, 'guide', source_refs=['source-synthetic'])
    record = page(repo, 'record', body=declare_link_role('[Observed](guide.md)', 'review_record'),
                  evidence_refs=['memories/guide.md'])
    event = repo / 'memories/system/ingestion/events/event.md'
    event.parent.mkdir(parents=True)
    event.write_text('---\npage_id: event-synthetic\npage_type: ingestion_event\nsource_id: synthetic\n'
                     'source_refs:\n  - source-synthetic\nconsolidated_into:\n  - memories/guide.md\n---\n')
    originals = {p: p.read_bytes() for p in (record, event)}
    base = commit(repo)
    git(repo, 'checkout', '-qb', 'migration')
    move(repo, 'memories/guide.md', 'memories/navigation/guide.md')
    commit(repo)
    monkeypatch.setattr(audit, 'ROOT', repo)
    monkeypatch.setattr(audit, 'link_audit_files', lambda cfg: ['memories/record.md'])
    monkeypatch.setattr(audit, 'ontology_dir_for', lambda rel, cfg: 'memories/projects' if rel == 'memories/record.md' else None)
    for phase in ('proposal', 'merged', 'future'):
        errors = []
        audit.audit_clickable_local_links(errors, load_config(repo))
        audit.audit_relations(errors, load_config(repo))
        audit.audit_consolidation(errors, [], load_config(repo))
        assert errors == [], (phase, errors)
        edges = authored_graph(repo, load_config(repo))['edges']
        assert any(e['type'] == 'review_record' and e['target'] == 'memories/navigation/guide.md' for e in edges)
        reviewed_edge = next(e for e in edges if e['type'] == 'review_record')
        assert reviewed_edge['relocation_provenance']['historical_target'] == 'memories/guide.md'
        assert git(repo, 'cat-file', '-t', reviewed_edge['relocation_provenance']['source_revision']) == 'commit'
        graph = build_page_graph(repo, load_config(repo))
        assert 'memories/navigation/guide.md' in graph.nodes['memories/record.md'].outbound_body_links
        inventory = build_semantic_inventory(repo, load_config(repo))
        assert inventory['relations']['status'] == 'pass'
        impact = repository_report(repo, load_config(repo), 'main', today=dt.date(2026, 10, 18))
        assert impact['relation_errors'] == impact['base_relation_diagnostics'] == []
        assert all(p.read_bytes() == raw for p, raw in originals.items())
        if phase == 'proposal':
            git(repo, 'checkout', '-q', 'main')
            git(repo, 'merge', '--no-ff', '-qm', 'Synthetic reviewed merge', 'migration')
        elif phase == 'merged':
            git(repo, 'checkout', '-qb', 'future')
            page(repo, 'unrelated')
            commit(repo)
    assert git(repo, 'merge-base', '--is-ancestor', base, 'HEAD') == ''
    assert target.exists() is False


@pytest.mark.parametrize('state', ['done', 'cancelled'])
@pytest.mark.parametrize('writer', ['page_edit', 'integrate'])
def test_terminal_writer_allows_only_same_page_link_reconciliation(repo, state, writer):
    page(repo, 'guide')
    action = _write_action(repo)
    action.write_text(action.read_text() + '\n[Evidence](../guide.md)\n')
    transition_action_page(repo, action, 'in_progress', recorded_at='2026-07-11T01:00:00Z')
    kwargs = {'completion_receipt': 'Synthetic result.'} if state == 'done' else {'cancellation_receipt': 'Synthetic reason.'}
    transition_action_page(repo, action, state, recorded_at='2026-07-11T02:00:00Z', **kwargs)
    commit(repo)
    move(repo, 'memories/guide.md', 'memories/navigation/guide.md')
    commit(repo)
    before = action.read_text()
    fm, body = _parse_document(before)
    edited = body.replace('../guide.md', '../navigation/guide.md')
    if writer == 'page_edit':
        transition_action_page(repo, action, state, page_edit={'body': edited}, expected_sha256=sha(action))
    else:
        integrate_action_body(repo, action, edited, expected_sha256=sha(action), contribution={'effect_key': 'synthetic', 'material_sha256': 'a'*64})
    after_fm, after_body = _parse_document(action.read_text())
    assert fm == after_fm  # including immutable dates, facts and historical receipts
    assert after_body == edited
    assert before.split('---\n', 2)[1] == action.read_text().split('---\n', 2)[1]


def test_git_structural_stage_then_incremental_writer_remains_base_auditable(repo, monkeypatch):
    page(repo, 'guide')
    action = _write_action(repo)
    action.write_text(action.read_text() + '\n[Evidence](../guide.md)\n')
    base = commit(repo)
    git(repo, 'update-ref', 'refs/remotes/origin/main', base)
    git(repo, 'checkout', '-qb', 'migration')
    move(repo, 'memories/guide.md', 'memories/navigation/guide.md')
    commit(repo)
    _, body = _parse_document(action.read_text())
    reconcile_action_navigation(repo, action, body.replace('../guide.md', '../navigation/guide.md'), expected_sha256=sha(action))
    intermediate = action.read_text()
    commit(repo)
    transition_action_page(repo, action, 'open', page_edit={'title': 'Reviewed synthetic task'},
                           expected_sha256=sha(action), recorded_at='2026-07-12T12:00:00Z')
    _, body = _parse_document(action.read_text())
    transition_action_page(repo, action, 'open', page_edit={'body': body + '\nA separately reviewed addition.\n'},
                           expected_sha256=sha(action), recorded_at='2026-07-12T12:01:00Z')
    fm, _ = _parse_document(action.read_text())
    assert fm['action_state_history'][0]['before_sha256'] == hashlib.sha256(intermediate.encode()).hexdigest()
    assert git(repo, 'rev-parse', 'main') == base
    assert audit_action(repo, monkeypatch) == []
    receipt_bytes = action.read_bytes()
    commit(repo)
    git(repo, 'checkout', '-q', 'main')
    git(repo, 'merge', '--no-ff', '-qm', 'Synthetic CI merge result', 'migration')
    assert action.read_bytes() == receipt_bytes
    assert git(repo, 'rev-parse', 'origin/main') == base
    assert audit_action(repo, monkeypatch) == []


def test_context_table_labels_link_the_declared_hub(repo, monkeypatch):
    hub = repo / 'memories/example/index.md'
    hub.parent.mkdir(parents=True)
    hub.write_text(_hub('example').replace('page_type: context_hub', 'page_type: project\ntitle: example'))
    commit(repo)
    rendered = build_operational_pass_page(repo, load_config(repo), updated_at='2026-07-12')
    context_cells = [line for line in rendered.splitlines() if line.startswith('| example |')]
    assert context_cells == []
    assert '| [example](../example/index.md)' in rendered
    output = repo / 'memories/system/operational-pass.md'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered)
    monkeypatch.setattr(audit, 'ROOT', repo)
    monkeypatch.setattr(audit, 'changed_paths_for_audit', lambda: {'memories/system/operational-pass.md'})
    warnings, errors = [], []
    cfg = load_config(repo)
    cfg.audit['mention_links_on_changed'] = 'error'
    audit.audit_entity_mention_links(warnings, cfg, errors)
    assert errors == warnings == []


def historical_fixture(root):
    target = page(root, 'guide')
    record = page(root, 'record', body='[Observed](guide.md#original)\n',
                  evidence_refs=['memories/guide.md'])
    commit(root)
    move(root, 'memories/guide.md', 'memories/navigation/guide.md')
    commit(root)
    return target, record, root / 'memories/navigation/guide.md'


@pytest.mark.parametrize('mutation', ['unproven', 'changed_record', 'absent', 'deleted', 'duplicate',
    'different_id', 'move_and_rewrite', 'resurrect', 'symlink', 'nested_repo', 'unsafe', 'unmentioned', 'no_id'])
def test_historical_resolution_refuses_unproved_or_unsafe_identity(repo, mutation):
    old, record, canonical = historical_fixture(repo)
    ref = 'guide.md#original'
    if mutation == 'unproven':
        record = page(repo, 'new-record', body='A new [Observed](guide.md#original)\n')
        commit(repo)
    elif mutation == 'changed_record':
        record.write_text(record.read_text() + '\nChanged conclusion.\n')
    elif mutation == 'absent':
        canonical.unlink()
    elif mutation == 'deleted':
        canonical.unlink(); commit(repo)
    elif mutation == 'duplicate':
        canonical.with_name('copy.md').write_bytes(canonical.read_bytes())
    elif mutation == 'different_id':
        canonical.write_text(canonical.read_text().replace('page_id: guide', 'page_id: another'))
    elif mutation == 'move_and_rewrite':
        git(repo, 'reset', '--hard', 'HEAD~1')
        move(repo, 'memories/guide.md', 'memories/navigation/guide.md')
        canonical.write_text(canonical.read_text() + '\nChanged factual content during move.\n')
        commit(repo)
    elif mutation == 'resurrect':
        raw = canonical.read_bytes(); canonical.unlink(); commit(repo)
        canonical.write_bytes(raw); commit(repo)
    elif mutation == 'symlink':
        raw = canonical.read_bytes(); canonical.unlink()
        other = repo / 'other.md'; other.write_bytes(raw); canonical.symlink_to(other)
    elif mutation == 'nested_repo':
        (canonical.parent / '.git').mkdir()
    elif mutation == 'unsafe':
        ref = '../../../escape.md'
    elif mutation == 'unmentioned':
        ref = 'guide.md#never-authored'
    elif mutation == 'no_id':
        canonical.write_text(canonical.read_text().replace('page_id: guide\n', ''))
    assert NavigationHistory(repo).resolve(record.relative_to(repo).as_posix(), record.read_text(), ref, href=True) is None


def test_moved_record_and_multiple_moves_preserve_role_hashes_and_git_provenance(repo):
    _, record, canonical = historical_fixture(repo)
    raw = record.read_bytes()
    move(repo, 'memories/record.md', 'memories/archive/record.md')
    commit(repo)
    move(repo, 'memories/navigation/guide.md', 'memories/final/guide.md')
    commit(repo)
    final = repo / 'memories/final/guide.md'
    final.write_text(final.read_text() + '\nA later separately committed fact.\n')
    commit(repo)
    moved_record = repo / 'memories/archive/record.md'
    assert moved_record.read_bytes() == raw
    assert NavigationHistory(repo).resolve('memories/archive/record.md', raw.decode(), 'guide.md#original', href=True) == 'memories/final/guide.md'


@pytest.mark.parametrize('mutation', ['fact', 'label', 'fragment', 'destination', 'code', 'image', 'owner', 'date', 'history', 'missing_cas', 'stale_cas'])
def test_terminal_reconciliation_rejects_every_unrelated_delta_without_writes(repo, mutation):
    page(repo, 'guide')
    page(repo, 'other')
    action = _write_action(repo)
    action.write_text(action.read_text() + '\n[Evidence](../guide.md#original)\n\n`[Code](../guide.md)`\n\n![Image](../guide.md)\n')
    transition_action_page(repo, action, 'in_progress', recorded_at='2026-07-11T01:00:00Z')
    transition_action_page(repo, action, 'done', completion_receipt='Synthetic result.', recorded_at='2026-07-11T02:00:00Z')
    commit(repo)
    move(repo, 'memories/guide.md', 'memories/navigation/guide.md'); commit(repo)
    before = action.read_text(); fm, body = _parse_document(before)
    edited = body.replace('[Evidence](../guide.md#original)', '[Evidence](../navigation/guide.md#original)')
    edit = {'body': edited}
    expected = sha(action)
    if mutation == 'fact': edit['body'] += '\nA new factual assertion.\n'
    elif mutation == 'label': edit['body'] = edited.replace('[Evidence]', '[New conclusion]')
    elif mutation == 'fragment': edit['body'] = edited.replace('#original', '#different')
    elif mutation == 'destination': edit['body'] = edited.replace('../navigation/guide.md', '../other.md')
    elif mutation == 'code': edit['body'] = edited.replace('[Code](../guide.md)', '[Code](../navigation/guide.md)')
    elif mutation == 'image': edit['body'] = edited.replace('![Image](../guide.md)', '![Image](../navigation/guide.md)')
    elif mutation == 'owner': edit['owner_kind'] = 'human'; edit['owner_ref'] = 'another-owner'
    elif mutation == 'date': edit['updated_at'] = '2026-07-12'
    elif mutation == 'history': edit['action_state_history'] = []
    elif mutation == 'missing_cas': expected = None
    elif mutation == 'stale_cas': expected = '0'*64
    with pytest.raises(ActionTransitionError):
        transition_action_page(repo, action, 'done', page_edit=edit, expected_sha256=expected)
    assert action.read_text() == before
    assert _parse_document(before)[0] == fm


@pytest.mark.parametrize('mutation', ['body_fact', 'frontmatter_fact', 'owner', 'date', 'invented_blob',
    'off_branch', 'detour_revert', 'cas', 'revision', 'post_writer_fact', 'post_writer_body'])
def test_bridge_cannot_launder_intermediates_or_writer_differences(repo, monkeypatch, mutation):
    page(repo, 'guide')
    action = _write_action(repo)
    action.write_text(action.read_text() + '\n[Evidence](../guide.md)\n')
    base = commit(repo); git(repo, 'checkout', '-qb', 'migration')
    move(repo, 'memories/guide.md', 'memories/navigation/guide.md'); commit(repo)
    original = action.read_text()
    intermediate = original.replace('../guide.md', '../navigation/guide.md')
    fm, body = _parse_document(intermediate)
    if mutation == 'body_fact': body += '\nUnapproved new fact.\n'
    elif mutation == 'frontmatter_fact': fm['attention_basis'] = 'Different fact.'
    elif mutation == 'owner': fm['owner_kind'] = 'human'; fm['owner_ref'] = 'different-owner'
    elif mutation == 'date': fm['updated_at'] = '2026-07-11'
    elif mutation == 'detour_revert':
        action.write_text(intermediate + '\nA factual detour.\n'); commit(repo)
    intermediate = _render_document(fm, body)
    action.write_text(intermediate)
    if mutation == 'invented_blob':
        git(repo, 'hash-object', '-w', action.relative_to(repo).as_posix())
    elif mutation == 'off_branch':
        git(repo, 'checkout', '-qb', 'unrelated'); commit(repo)
        git(repo, 'checkout', '-q', 'migration'); action.write_text(intermediate)
    else:
        commit(repo)
    transition_action_page(repo, action, 'open', page_edit={'title': 'Reviewed synthetic title'},
                           expected_sha256=sha(action), recorded_at='2026-07-12T12:00:00Z')
    current, body = _parse_document(action.read_text())
    if mutation in {'cas', 'revision'}:
        entry = current['action_state_history'][0]
        entry['before_sha256' if mutation == 'cas' else 'before_revision'] = '0'*64
        entry['receipt_id'] = _receipt_id(entry)
    elif mutation == 'post_writer_fact': current['context'] = 'different-context'
    elif mutation == 'post_writer_body': body += '\n'
    action.write_text(_render_document(current, body))
    assert audit_action(repo, monkeypatch), mutation
    assert git(repo, 'rev-parse', 'main') == base


def test_historical_requirements_keep_the_original_pin_and_current_requirements_still_refuse(repo):
    page(repo, 'guide')
    observed = commit(repo)
    requirement = dict(target='memories/guide.md', fields=['body'], temporal='historical',
                       max_age_days=30, consumed_revision=observed)
    record = page(repo, 'record', information_requirements=[requirement])
    commit(repo)
    move(repo, 'memories/guide.md', 'memories/navigation/guide.md'); commit(repo)
    raw = record.read_bytes()
    graph = authored_graph(repo, load_config(repo))
    assert graph['errors'] == []
    edge = next(e for e in graph['edges'] if e['field'] == 'information_requirements')
    assert edge['target'] == 'memories/navigation/guide.md'
    assert edge['requirement']['consumed_revision'] == observed
    assert edge['requirement']['historical_target'] == 'memories/guide.md'
    assert record.read_bytes() == raw
    record.write_text(record.read_text().replace('temporal: historical', 'temporal: current'))
    assert any('target is missing or ambiguous' in err for err in authored_graph(repo, load_config(repo))['errors'])


def test_structural_frontmatter_keeps_historical_bytes_and_cannot_reformat_them(repo):
    page(repo, 'guide')
    action = _write_action(repo, extra={'evidence_refs': ['memories/guide.md']})
    commit(repo)
    move(repo, 'memories/guide.md', 'memories/navigation/guide.md'); commit(repo)
    before = action.read_text()
    after = before.replace('  - memories/guide.md', '  - memories/navigation/guide.md')
    if after == before:  # fixture uses PyYAML's legacy indentless sequence
        after = before.replace('- memories/guide.md', '- memories/navigation/guide.md')
    h = NavigationHistory(repo)
    assert before != after and structural_navigation(h, action.relative_to(repo).as_posix(), before, after)
    assert not structural_navigation(h, action.relative_to(repo).as_posix(), before,
                                     after.replace('visibility: private_self', 'visibility: "private_self"'))


def test_localized_memory_root_and_uncommitted_exact_move(repo):
    (repo / 'wiki.config.yaml').write_text('paths:\n  memory_root: notes\n')
    folder = repo / 'notes'; folder.mkdir()
    (folder / 'guide.md').write_text('---\npage_id: synthetic-guide\n---\nSynthetic evidence.\n')
    record = folder / 'record.md'
    record.write_text('---\npage_id: synthetic-record\n---\n[Guide](guide.md)\n')
    commit(repo)
    move(repo, 'notes/guide.md', 'notes/navigation/guide.md')
    assert NavigationHistory(repo).resolve('notes/record.md', record.read_text(), 'guide.md', href=True) == 'notes/navigation/guide.md'


def test_existing_symlink_is_not_a_historical_alias(repo, monkeypatch):
    old, record, canonical = historical_fixture(repo)
    old.symlink_to(canonical)
    monkeypatch.setattr(audit, 'ROOT', repo)
    monkeypatch.setattr(audit, 'link_audit_files', lambda cfg: ['memories/record.md'])
    errors = []
    audit.audit_clickable_local_links(errors, load_config(repo))
    assert any('link target does not exist' in err for err in errors)


def test_reoccupied_old_path_cannot_steal_the_historical_identity(repo, monkeypatch):
    old, record, canonical = historical_fixture(repo)
    old.write_text('---\npage_id: different-occupant\n---\nDifferent evidence.\n')
    commit(repo)
    monkeypatch.setattr(audit, 'ROOT', repo)
    monkeypatch.setattr(audit, 'link_audit_files', lambda cfg: ['memories/record.md'])
    errors = []
    audit.audit_clickable_local_links(errors, load_config(repo))
    assert errors
    assert authored_graph(repo, load_config(repo))['errors']
    # A newly reviewed document can explicitly refer to the new occupant.
    new_record = page(repo, 'new-record', body='[New occupant](guide.md#original)\n')
    commit(repo)
    assert NavigationHistory(repo).existing_reference_safe('memories/new-record.md', new_record.read_text(), 'guide.md#original', href=True)


def test_link_discovery_does_not_open_or_authorize_a_restricted_target(repo, monkeypatch):
    from wiki_core.repository_reader import canonical_path, RepositoryReadError
    target = repo / '.env.example'
    target.write_text('SYNTHETIC_VALUE=placeholder\n')
    record = page(repo, 'record', body='[Example](../.env.example)\n')
    commit(repo)
    original_read = Path.read_bytes
    def guarded_read(path):
        assert path != target
        return original_read(path)
    monkeypatch.setattr(Path, 'read_bytes', guarded_read)
    assert NavigationHistory(repo).existing_reference_safe('memories/record.md', record.read_text(), '../.env.example', href=True)
    with pytest.raises(RepositoryReadError):
        canonical_path('.env.example')


def test_consolidation_compares_source_identity_after_both_pages_move(repo, monkeypatch):
    source = page(repo, 'source-synthetic')
    target = page(repo, 'guide', source_refs=['memories/source-synthetic.md'])
    event = repo / 'memories/system/ingestion/events/event.md'
    event.parent.mkdir(parents=True)
    event.write_text('---\npage_id: synthetic-event\nsource_id: synthetic\nsource_refs:\n'
                     '  - memories/source-synthetic.md\nconsolidated_into:\n  - memories/guide.md\n---\n')
    commit(repo)
    original = event.read_bytes()
    move(repo, source.relative_to(repo).as_posix(), 'memories/navigation/source-synthetic.md')
    move(repo, target.relative_to(repo).as_posix(), 'memories/navigation/guide.md')
    commit(repo)
    moved_target = repo / 'memories/navigation/guide.md'
    moved_target.write_text(moved_target.read_text().replace('memories/source-synthetic.md', 'memories/navigation/source-synthetic.md'))
    commit(repo)
    monkeypatch.setattr(audit, 'ROOT', repo)
    errors = []
    audit.audit_consolidation(errors, [], load_config(repo))
    assert errors == []
    assert event.read_bytes() == original


@pytest.mark.parametrize('mutation', ['target_changed', 'duplicate_added', 'head_changed'])
def test_navigation_writer_rechecks_the_selected_identity_before_writing(repo, monkeypatch, mutation):
    page(repo, 'guide')
    action = _write_action(repo)
    action.write_text(action.read_text() + '\n[Evidence](../guide.md)\n')
    commit(repo)
    move(repo, 'memories/guide.md', 'memories/navigation/guide.md'); commit(repo)
    before = action.read_text()
    _, body = _parse_document(before)
    original_confirm = NavigationHistory.confirm
    def concurrent_change(history):
        target = repo / 'memories/navigation/guide.md'
        if mutation == 'target_changed': target.write_text(target.read_text() + '\nConcurrent change.\n')
        elif mutation == 'duplicate_added': target.with_name('duplicate.md').write_bytes(target.read_bytes())
        elif mutation == 'head_changed':
            page(repo, 'unrelated'); commit(repo)
        return original_confirm(history)
    monkeypatch.setattr(NavigationHistory, 'confirm', concurrent_change)
    with pytest.raises(ActionTransitionError, match='stale_navigation_revision'):
        reconcile_action_navigation(repo, action, body.replace('../guide.md', '../navigation/guide.md'), expected_sha256=sha(action))
    assert action.read_text() == before
