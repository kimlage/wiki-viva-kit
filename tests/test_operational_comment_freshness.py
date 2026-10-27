"""Communication capture is not documentary incorporation or factual renewal."""
import copy
import datetime as dt

import pytest

from wiki_core.action_transition import (
    _parse_document, _render_document, _receipt_id, action_transition_diagnostics,
    operational_comment_receipt, transition_action_page,
)
from wiki_core.config import load_config
from wiki_core.document_records import project_records
from wiki_core.freshness_impact import authored_graph, evaluate_impact, repository_report
from tests.test_action_transition import _write_action
from tests.test_freshness_impact import repo, page, commit, paths

TODAY = dt.date(2026, 10, 27)
AT = '2026-10-27T01:00:00Z'


def comment(root, path, *, at=AT, eid='received-run-0001', **kwargs):
    return transition_action_page(root, path, 'open', recorded_at=at,
        dialogue_event=dict(event_id=eid, kind='comment', coordinator='research',
            text='Retained result received. Documentary integration remains pending.'), **kwargs)


def setup(root):
    (root / '.gitignore').write_text('data/derived/\n')
    page(root, 'index')
    page(root, 'policy', stale=True)
    action = _write_action(root, extra={'source_refs': ['policy']})
    page(root, 'consumer', stale=True, source_refs=['action-synthetic-review'])
    return action


def report(root, base):
    return repository_report(root, load_config(root), base, today=TODAY)


def test_native_comment_records_real_time_without_renewing_facts(repo):
    action = setup(repo)
    base = commit(repo)
    before = action.read_text()
    comment(repo, action)
    after = action.read_text()
    old, body = _parse_document(before)
    new, new_body = _parse_document(after)
    assert new_body == body
    assert new['updated_at'] == old['updated_at'] == '2026-07-10'
    assert new['action_dialogue'][-1]['at'] == AT
    assert new['action_state_history'][-1]['at'] == AT
    assert action_transition_diagnostics(before, after) == ()
    result = report(repo, base)
    ref = action.relative_to(repo).as_posix()
    assert result['ok'] and not result['seeds']
    assert result['changed_paths'] == [ref]
    assert result['operational_comments'][0]['path'] == ref
    assert {ref, 'memories/policy.md', 'memories/consumer.md'} <= paths(result['unrelated_debt'])


@pytest.mark.parametrize('new_base', [False, True])
def test_another_factual_seed_reaches_whole_action_and_its_old_debt(repo, new_base):
    action = setup(repo)
    base = commit(repo)
    comment(repo, action)
    if new_base:
        base = commit(repo)  # No temporary freshness overlay lost after merge.
    consumer = repo / 'memories/consumer.md'
    consumer.write_text(consumer.read_text() + '\nA new conclusion based on the action.\n')
    result = report(repo, base)
    assert not result['ok']
    assert {action.relative_to(repo).as_posix(), 'memories/policy.md'} <= paths(result['blockers'])


@pytest.mark.parametrize('field,value', [
    ('body', 'Changed asserted conclusion.'), ('owner_ref', 'person-other'),
    ('priority', 'urgent'), ('next_action', 'Execute instead of review'),
    ('source_refs', []), ('blocker_reason', 'New blocker'),
    ('updated_at', '2026-10-27'), ('action_state', 'in_progress'),
])
def test_mixed_delta_is_not_communication_only(repo, field, value):
    action = setup(repo)
    before = action.read_text()
    comment(repo, action)
    fm, body = _parse_document(action.read_text())
    if field == 'body':
        body += value
    else:
        fm[field] = value
    assert operational_comment_receipt(before, _render_document(fm, body)) is None


@pytest.mark.parametrize('tamper', ['event', 'receipt', 'before', 'payload', 'padding', 'two'])
def test_wrong_history_preimage_or_bytes_cannot_qualify(repo, tamper):
    action = setup(repo)
    before = action.read_text()
    comment(repo, action)
    fm, body = _parse_document(action.read_text())
    if tamper == 'two':
        comment(repo, action, at='2026-10-28T01:00:00Z', eid='received-run-0002')
        # A multi-comment batch is still valid history but conservatively
        # unqualified until each individual revision has been reviewed.
        assert action_transition_diagnostics(before, action.read_text()) == ()
    elif tamper == 'padding':
        action.write_text(action.read_text() + '\n')
    else:
        entry = fm['action_state_history'][-1]
        if tamper == 'event':
            fm['action_dialogue'][-1]['text'] = 'Different unbound result'
        elif tamper == 'receipt':
            entry['receipt_id'] = 'sha256:' + 'a' * 64
        elif tamper == 'before':
            entry['before_sha256'] = fm['action_dialogue'][-1]['before_sha256'] = 'a' * 64
            entry['receipt_id'] = _receipt_id(entry)
        else:
            entry['payload_sha256'] = 'a' * 64
            entry['receipt_id'] = _receipt_id(entry)
        action.write_text(_render_document(fm, body))
    assert operational_comment_receipt(before, action.read_text()) is None


def test_comment_and_lifecycle_receipts_keep_their_distinct_dates(repo):
    action = setup(repo)
    original = action.read_text()
    transition_action_page(repo, action, 'in_progress', recorded_at='2026-10-26T01:00:00Z')
    transition_action_page(repo, action, 'in_progress', recorded_at=AT,
        dialogue_event=dict(event_id='received-run-0001', kind='comment', coordinator='research', text='Received.'))
    fm, _ = _parse_document(action.read_text())
    assert fm['updated_at'] == '2026-10-26'
    assert action_transition_diagnostics(original, action.read_text()) == ()
    assert operational_comment_receipt(original, action.read_text()) is None


def test_records_still_require_exact_physical_snapshot_and_causal_pair(repo):
    from tests.test_causal_review import authored, run, contract
    action = setup(repo)
    cfg = load_config(repo)
    base = authored_graph(repo, cfg)
    # Reuse the existing independent declaration and review fixture.
    declaration = '# Declaration\n\n## Stable\n\nComplete unrelated unit.\n'
    base['documents']['declaration'] = declaration
    base['nodes']['declaration'] = dict(updated_at='2026-10-26', stale_after_days=30)
    comment(repo, action)
    current = authored_graph(repo, cfg)
    current['documents']['declaration'] = declaration
    current['nodes']['declaration'] = copy.deepcopy(base['nodes']['declaration'])
    changed = {action.relative_to(repo).as_posix()}
    spec = contract(base, current)
    wrong = copy.deepcopy(spec)
    wrong['current_documents_sha256'] = copy.deepcopy(wrong['base_documents_sha256'])
    with pytest.raises(ValueError, match='document snapshot'):
        project_records(current, base, changed, wrong)
    reviewed, inputs = authored(base, current, changed, spec=spec)
    result = run(base, current, changed, reviewed, inputs)
    assert result['ok'] and result['operational_comments']
    assert result['causal_review']['potential_obligations'] == 0
    pc, pb, seeds, _ = project_records(current, base, changed, reviewed, artifact_inputs=inputs)
    pc['documents'][next(iter(changed))] += 'Unreviewed assertion.\n'
    with pytest.raises(ValueError, match='causal inputs changed'):
        evaluate_impact(pc, pb, seeds, today=TODAY)


def test_legacy_date_renewing_comment_is_auditable_but_not_qualified(repo):
    action = setup(repo)
    before = action.read_text()
    comment(repo, action)
    fm, body = _parse_document(action.read_text())
    fm['updated_at'] = '2026-10-27'
    entry = fm['action_state_history'][-1]
    entry['kind'] = 'contract_update'
    entry['receipt_id'] = _receipt_id(entry)
    legacy = _render_document(fm, body)
    assert action_transition_diagnostics(before, legacy) == ()
    assert operational_comment_receipt(before, legacy) is None


def test_partitioned_action_and_generated_view_keep_independent_obligations(repo):
    from tests.test_document_records import declaration
    action = setup(repo)
    action.write_text(action.read_text() + '\n## Evidence\n\nUnchanged evidence.\n')
    cfg = load_config(repo)
    base = authored_graph(repo, cfg)
    comment(repo, action)
    current = authored_graph(repo, cfg)
    ref = action.relative_to(repo).as_posix()
    spec = declaration(base, current, path=ref, headings=('Evidence',))
    pc, pb, changed, _ = project_records(current, base, {ref}, spec)
    result = evaluate_impact(pc, pb, changed, today=TODAY)
    assert not result['ok'] and ref in result['seeds']
    assert 'operational_comments' not in result
    # A separate generated output is not qualified by a comment elsewhere.
    current['documents']['memories/consumer.md'] += '\nNew generated assertion.\n'
    result = evaluate_impact(current, base, {ref, 'memories/consumer.md'}, today=TODAY)
    assert not result['ok'] and result['operational_comments']
    assert 'memories/consumer.md' in result['seeds']
    assert 'memories/policy.md' in paths(result['blockers'])


def test_native_comment_passes_page_shape_and_keeps_temporal_receipt(repo):
    from pathlib import Path
    from wiki_core.page_types import validate_shape, load_page_type_registry
    from wiki_core.web.snapshot import build_snapshot
    action = setup(repo)
    comment(repo, action)
    fm, body = _parse_document(action.read_text())
    fm['stale_after_days'] = str(fm['stale_after_days'])
    shape = copy.deepcopy(load_page_type_registry(Path(__file__).resolve().parents[1]).page_types['action'])
    # The fixture owns its layout; a consumer may localize canonical paths.
    shape['allowed_dirs'] = ['memories/actions']
    assert validate_shape(repo, action.relative_to(repo).as_posix(), fm, body, shape) == []
    snapshot = build_snapshot(repo, load_config(repo), generated_at='2026-10-27T02:00:00Z')
    temporal = snapshot['temporal_graph.json']
    events, diagnostics = temporal['events'], temporal['diagnostics']
    matching = [e for e in events if 'page:action-synthetic-review' in e.get('subject_refs', [])]
    assert {'activity_recorded', 'receipt_recorded'} <= {e['kind'] for e in matching}
    assert not any('transition_receipt_state_preserving_kind_invalid' in d['error_codes'] for d in diagnostics)


@pytest.mark.parametrize("git_stage", ["worktree", "staged", "committed"])
@pytest.mark.parametrize("mutation", [None, "body", "next_action", "source_refs", "updated_at",
                                      "owner_ref", "blocker_reason", "receipt", "payload", "second_comment", "other_seed", "incoming_seed"])
def test_comment_impact_audit_retains_physical_delta_and_blocks_mixed_changes(repo, monkeypatch, mutation, git_stage):
    from tests.test_wiki_audit import _load_wiki_audit
    from tests.test_freshness_impact import git
    audit = _load_wiki_audit()
    action = setup(repo)
    premise = page(repo, 'premise', body='Original factual premise.')
    page(repo, 'consumer', stale=True, source_refs=['action-synthetic-review', 'premise'])
    base = commit(repo)
    git(repo, 'update-ref', 'refs/remotes/origin/main', base)
    git(repo, 'switch', '-c', 'wiki/comment-impact')
    comment(repo, action)
    if mutation == 'second_comment':
        comment(repo, action, eid='received-run-0002', at='2026-10-27T01:01:00Z')
    elif mutation == 'other_seed':
        premise.write_text(premise.read_text() + '\nA changed factual premise.\n')
    elif mutation == 'incoming_seed':
        policy = repo / 'memories/policy.md'
        policy.write_text(policy.read_text() + '\nChanged premise consumed by the commented action.\n')
    elif mutation:
        values, body = _parse_document(action.read_text())
        if mutation == "body":
            body += "\nA changed substantive conclusion.\n"
        elif mutation == "receipt":
            values['action_state_history'][-1]['receipt_id'] = 'sha256:' + '0' * 64
        elif mutation == "payload":
            values['action_dialogue'][-1]['text'] = 'Unbound altered payload.'
        else:
            values[mutation] = {'next_action': 'Perform a different effect.',
                                'source_refs': [], 'updated_at': '2026-10-27',
                                'owner_ref': 'person-other', 'blocker_reason': 'Different blocker.'}[mutation]
        action.write_text(_render_document(values, body))
    if git_stage == 'staged':
        git(repo, 'add', '.')
    elif git_stage == 'committed':
        commit(repo)
    monkeypatch.setattr(audit, 'ROOT', repo)
    assert git(repo, 'rev-parse', audit._audit_base_ref()) == base
    config = load_config(repo)
    config.audit['impact_check'] = True
    ref = action.relative_to(repo).as_posix()
    assert ref in audit.changed_paths_for_audit()  # Integrity/CAS still sees physical bytes.
    errors = []
    audit.audit_impact(errors, config)
    if mutation is None:
        assert errors == []
    elif mutation == 'incoming_seed':
        assert any(ref + ': impacted by changed page(s) memories/policy.md' in e for e in errors)
    else:
        assert any('memories/consumer.md: impacted by changed page' in e for e in errors)
