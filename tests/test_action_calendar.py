"""Synthetic calendar-bound receipts: local freshness and portable replay."""
from contextlib import contextmanager
from datetime import date
import hashlib
import os
import time
from pathlib import Path

import pytest

import wiki_core.action_transition as writer
from wiki_core.freshness import freshness_state
from test_action_transition import _write_action

AT = '2026-07-11T00:40:00Z'
LATER = '2026-07-11T00:41:00Z'


@contextmanager
def local_zone(zone):
    if not hasattr(time, 'tzset'):
        pytest.skip('Host timezone switching requires tzset')
    original = os.environ.get('TZ')
    os.environ['TZ'] = zone
    time.tzset()
    try:
        yield
    finally:
        if original is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = original
        time.tzset()


def write(root, path, kind, at=AT):
    if kind == 'body':
        writer.integrate_action_body(root, path, '# Synthetic reviewed content\n' + at,
            expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            contribution={'effect_key': 'synthetic-' + at, 'material_sha256': 'a' * 64},
            recorded_at=at)
    else:
        writer.transition_action_page(root, path, 'in_progress', recorded_at=at,
            priority='high' if at == LATER else 'normal')


def parse(path):
    return writer._parse_document(path.read_text())


@pytest.mark.parametrize('kind', ['transition', 'body'])
@pytest.mark.parametrize('zone,offset,day', [('Etc/GMT+3', -180, '2026-07-10'), ('UTC', 0, '2026-07-11')])
def test_midnight_writes_match_operator_freshness_and_replay_elsewhere(tmp_path, kind, zone, offset, day):
    path = _write_action(tmp_path)
    before = path.read_text()
    with local_zone(zone):
        write(tmp_path, path, kind)
    fm, _ = parse(path)
    assert fm['updated_at'] == day
    assert freshness_state(fm['updated_at'], 30, date.fromisoformat(day)) == 'fresh'
    entry = fm['action_state_history'][-1]
    assert entry['at'] == AT
    assert entry['schema_version'] == 'wiki_action_transition_receipt.v6'
    assert entry['calendar_utc_offset_minutes'] == offset
    from wiki_core.page_types import _action_history_shape_errors
    assert _action_history_shape_errors('synthetic', fm, fm['action_state']) == []
    with local_zone('Etc/GMT-12'):
        assert writer.action_transition_diagnostics(before, path.read_text()) == ()


def legacy_receipt(path, schema='wiki_action_transition_receipt.v4'):
    fm, body = parse(path)
    entry = fm['action_state_history'][-1]
    entry['schema_version'] = schema
    entry.pop('calendar_utc_offset_minutes', None)
    entry['receipt_id'] = writer._receipt_id(entry)
    fm['updated_at'] = '2026-07-11'
    path.write_text(writer._render_document(fm, body))
    return entry.copy()


@pytest.mark.parametrize('kind', ['transition', 'body'])
def test_new_factual_receipt_normalizes_only_proven_legacy_utc_future(tmp_path, kind):
    path = _write_action(tmp_path)
    original = path.read_text()
    with local_zone('UTC'):
        write(tmp_path, path, kind)
    old_entry = legacy_receipt(path)
    before = path.read_text()
    assert writer.action_transition_diagnostics(original, before) == ()
    with local_zone('Etc/GMT+3'):
        write(tmp_path, path, kind, LATER)
    fm, _ = parse(path)
    assert fm['updated_at'] == '2026-07-10'
    assert fm['action_state_history'][0] == old_entry
    assert fm['action_state_history'][-1]['at'] == LATER
    assert writer.action_transition_diagnostics(before, path.read_text()) == ()
    assert writer.action_transition_diagnostics(original, path.read_text()) == ()


@pytest.mark.parametrize('legacy', [False, True])
def test_calendar_does_not_rebase_a_proven_v6_or_unreceipted_date(tmp_path, legacy):
    path = _write_action(tmp_path, extra={'updated_at': '2026-07-11'} if legacy else {})
    if not legacy:
        with local_zone('UTC'):
            write(tmp_path, path, 'transition')
    before = path.read_bytes()
    with local_zone('Etc/GMT+3'), pytest.raises(writer.ActionTransitionError):
        write(tmp_path, path, 'transition', LATER)
    assert path.read_bytes() == before


@pytest.mark.parametrize('offset', [None, True, -841, 841, '-180'])
def test_v6_calendar_binding_is_required_typed_and_bounded(tmp_path, offset):
    path = _write_action(tmp_path)
    before = path.read_text()
    with local_zone('UTC'):
        write(tmp_path, path, 'body')
    fm, body = parse(path)
    entry = fm['action_state_history'][-1]
    if offset is None:
        entry.pop('calendar_utc_offset_minutes')
    else:
        entry['calendar_utc_offset_minutes'] = offset
    entry['receipt_id'] = writer._receipt_id(entry)
    assert writer.action_transition_diagnostics(before, writer._render_document(fm, body))
    assert writer._receipt_calendar_date(entry) is None
    from wiki_core.page_types import _action_history_shape_errors
    assert _action_history_shape_errors('synthetic', fm, fm['action_state'])


def test_offset_is_in_receipt_digest_and_legacy_cannot_inject_it(tmp_path):
    path = _write_action(tmp_path)
    before = path.read_text()
    with local_zone('UTC'):
        write(tmp_path, path, 'transition')
    fm, body = parse(path)
    fm['action_state_history'][-1]['calendar_utc_offset_minutes'] = -180
    assert writer.action_transition_diagnostics(before, writer._render_document(fm, body))
    legacy_receipt(path)
    fm, body = parse(path)
    entry = fm['action_state_history'][-1]
    entry['calendar_utc_offset_minutes'] = 0
    entry['receipt_id'] = writer._receipt_id(entry)
    assert writer.action_transition_diagnostics(before, writer._render_document(fm, body))


def test_comment_does_not_renew_date_or_acquire_factual_calendar(tmp_path):
    path = _write_action(tmp_path)
    before = path.read_text()
    with local_zone('Etc/GMT+3'):
        writer.transition_action_page(tmp_path, path, 'open', recorded_at=AT,
            dialogue_event={'event_id':'synthetic-question', 'kind':'comment',
                            'coordinator':'example', 'text':'Which source?'},
            dialogue_actor='coordinator:example')
    fm, _ = parse(path)
    assert fm['updated_at'] == '2026-07-10'
    entry = fm['action_state_history'][-1]
    assert entry['schema_version'] == 'wiki_action_transition_receipt.v4'
    assert 'calendar_utc_offset_minutes' not in entry
    assert writer.action_transition_diagnostics(before, path.read_text()) == ()


def test_normalization_does_not_allow_equal_or_earlier_instant(tmp_path):
    path = _write_action(tmp_path)
    with local_zone('UTC'):
        write(tmp_path, path, 'transition')
    legacy_receipt(path)
    before = path.read_bytes()
    with local_zone('Etc/GMT+3'), pytest.raises(writer.ActionTransitionError):
        write(tmp_path, path, 'body', AT)
    assert path.read_bytes() == before
