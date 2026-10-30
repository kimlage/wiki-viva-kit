"""Editorial consolidation proves exact replacements, never factual freshness."""
import hashlib
import copy
import pytest
from tests.test_action_transition import _write_action
from wiki_core.action_transition import (integrate_action_body, _parse_document,
    _render_document, _receipt_id, _consolidated_body, ActionTransitionError,
    action_transition_diagnostics, transition_action_page)

PARAGRAPH = ('The synthetic review confirmed the old prerequisites. This dated statement '
             'does not prove execution, publication, or current external information. '
             'The original evidence and its limitations remain authoritative.')


def fixture(root):
    p = _write_action(root)
    p.write_text(p.read_text() + '\n' + PARAGRAPH + '\n')
    canonical = p.with_name('canonical.md')
    canonical.write_text(p.read_text().replace('page_id: action-synthetic-review', 'page_id: canonical'))
    records = [{'paragraph': PARAGRAPH, 'canonical_ref': canonical.relative_to(root).as_posix(),
                'canonical_sha256': hashlib.sha256(canonical.read_bytes()).hexdigest(), 'label': 'Canonical prerequisite evidence'}]
    return p, canonical, records


def apply(root, p, records, **extra):
    before = p.read_text(); _, body = _parse_document(before)
    return integrate_action_body(root, p, _consolidated_body(body, records),
        expected_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
        contribution={'effect_key': 'editorial-1', 'material_sha256': 'a'*64},
        recorded_at='2026-07-11T23:45:00-03:00', consolidations=records, **extra)


def test_editorial_at_utc_midnight_preserves_dates_fields_and_canonical(tmp_path):
    p, canonical, records = fixture(tmp_path)
    before = p.read_text(); source = canonical.read_bytes(); fm, body = _parse_document(before)
    apply(tmp_path, p, records)
    after = p.read_text(); current, new_body = _parse_document(after)
    assert {k:v for k,v in current.items() if k != 'action_state_history'} == fm
    assert canonical.read_bytes() == source
    assert new_body == body.replace(PARAGRAPH, '[Canonical prerequisite evidence](canonical.md).')
    assert current['action_state_history'][-1]['at'] == '2026-07-11T23:45:00-03:00'
    assert action_transition_diagnostics(before, after) == ()
    assert action_transition_diagnostics(before, after + '\nNew unreviewed fact.')[0].code == 'invalid_body_consolidation'
    current['updated_at'] = '2026-07-12'
    assert action_transition_diagnostics(before, _render_document(current, new_body))[0].code == 'action_transition_timestamp_mismatch'


@pytest.mark.parametrize('mutation', ['source_changed', 'not_present', 'self', 'path', 'label', 'symlink'])
def test_editorial_refuses_unverified_source_without_writes(tmp_path, mutation):
    p, canonical, records = fixture(tmp_path); before = p.read_bytes()
    if mutation == 'source_changed': canonical.write_text(canonical.read_text()+'\nChanged.\n')
    elif mutation == 'not_present':
        canonical.write_text(canonical.read_text().replace(PARAGRAPH, 'Another fact.'))
        records[0]['canonical_sha256'] = hashlib.sha256(canonical.read_bytes()).hexdigest()
    elif mutation == 'self': records[0]['canonical_ref'] = p.relative_to(tmp_path).as_posix()
    elif mutation == 'path': records[0]['canonical_ref'] = '../outside.md'
    elif mutation == 'label': records[0]['label'] = 'Misleading](https://example.invalid'
    elif mutation == 'symlink':
        canonical.unlink(); canonical.symlink_to(p)
    with pytest.raises(ActionTransitionError): apply(tmp_path, p, records)
    assert p.read_bytes() == before


def test_terminal_and_unrelated_changes_are_refused(tmp_path):
    p, canonical, records = fixture(tmp_path)
    before = p.read_text(); _, body = _parse_document(before)
    with pytest.raises(ActionTransitionError, match='unrelated_body'):
        integrate_action_body(tmp_path,p,_consolidated_body(body,records)+'\nNew fact.\n',
            expected_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
            contribution={'effect_key':'x','material_sha256':'b'*64},consolidations=records)
    assert p.read_text() == before
    transition_action_page(tmp_path,p,'in_progress',recorded_at='2026-07-11T01:00:00Z')
    transition_action_page(tmp_path,p,'done',completion_receipt='Reviewed synthetic result.',recorded_at='2026-07-11T02:00:00Z')
    before = p.read_bytes()
    with pytest.raises(ActionTransitionError,match='terminal_action_body_immutable'): apply(tmp_path,p,records)
    assert p.read_bytes() == before


def test_forged_editorial_receipt_cannot_hide_extra_body_changes(tmp_path):
    p, _, records = fixture(tmp_path); before = p.read_text(); apply(tmp_path,p,records)
    fm, body = _parse_document(p.read_text()); event = fm['action_state_history'][-1]
    body += '\nExtra statement.\n'
    from wiki_core.action_transition import _revision_sha256, _sha256_text
    import json
    event['contribution']['after_body_sha256'] = _sha256_text(body)
    event['contribution']['after_body_revision'] = _revision_sha256(body)
    event['payload_sha256'] = _sha256_text(json.dumps(event['contribution'],sort_keys=True,ensure_ascii=False,separators=(',',':')))
    event['receipt_id'] = _receipt_id(event)
    assert action_transition_diagnostics(before,_render_document(fm,body))[0].code == 'invalid_body_consolidation'
