"""Git-backed checks for retirement of historical legacy query declarations."""
from copy import deepcopy
import datetime as dt
import subprocess

import pytest
import yaml

from wiki_core.config import load_config
from wiki_core.context_packet import build_packet, qualify_folder_context
from wiki_core.context_policy import load_policy
from wiki_core.freshness_impact import repository_report
from wiki_core.information_relations import authored_graph
from wiki_core.information_use import assess_information_use, bind_verification_coverage

CONTEXT = 'alpha'
CONSUMER = 'alpha/interpretation.md'
DEPENDENT = 'alpha/dependent.md'
ACTION = 'alpha/action.md'
CHAINED_ACTION = 'alpha/chained-action.md'
HISTORICAL_ACTION = 'alpha/historical-action.md'
STATUS_ACTION = 'alpha/status-action.md'
TODAY = dt.date(2026, 11, 5)
NOW = dt.datetime(2026, 11, 5, 12, tzinfo=dt.timezone.utc)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE, text=True).strip()


def write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding='utf-8')


def page(root, path, values):
    write(root, path, '---\n' + yaml.safe_dump(values, sort_keys=True) + '---\nSynthetic content.\n')


def commit(root, *, approve=False):
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'synthetic fixture')
    head = git(root, 'rev-parse', 'HEAD')
    if approve:
        git(root, 'update-ref', 'refs/remotes/origin/main', head)
    return head


def manifest(context_id, parent, root, policy):
    return {'schema_version': 'wiki.context/v1', 'id': context_id, 'parent': parent,
            'root': root, 'purpose': 'synthetic', 'owner': 'operator', 'instructions': [],
            'skills': [], 'templates': [], 'policy': policy, 'imports': [], 'exports': []}


def query():
    return {'target': 'alpha/index.md', 'reason': 'synthetic historical interpretation',
            'use': 'interpret', 'classification': 'synthetic',
            'query': {'scope': 'alpha/items', 'filters': {'status': 'active'}, 'field': 'amount',
                      'max_enumerated': 20, 'max_matches': 10, 'max_scan_bytes': 100000}}


def receipt(packet, temporal='historical'):
    row = packet['query_selections'][0]
    req = row['request']
    return {'target': req['target'], 'fields': ['*'], 'temporal': temporal, 'max_age_days': 30,
            'consumed_revision': row['revision'], 'use': req['use'], 'classification': req['classification'],
            'query': req['query'], 'members_digest': row['members_digest'], 'selected_digest': row['selected_digest'],
            'query_policy_revision': row['policy_revision'], 'authority_digest': row['authority_digest'],
            **{key: row[key] for key in ('authority_format', 'entry_folder', 'entry_index') if key in row}}


def packet(root, policy, *, folder=False):
    return build_packet(root, policy, CONTEXT, git(root, 'rev-parse', 'HEAD'), [], 100000,
                        task_id='synthetic-task', goal='interpret', output=CONSUMER,
                        integrator='reviewer', queries=[query()],
                        **({'entry_folder': CONTEXT} if folder else {}))


@pytest.fixture
def history(tmp_path):
    root = tmp_path
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Synthetic')
    git(root, 'config', 'user.email', 'synthetic@example.invalid')
    policy = {'read': ['self'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []}
    write(root, 'context.yaml', yaml.safe_dump(manifest('root', None, '.', policy)))
    write(root, 'alpha/context.yaml', yaml.safe_dump(manifest(CONTEXT, 'root', CONTEXT, policy)))
    page(root, 'alpha/index.md', {'page_id': 'collection', 'page_type': 'source_catalog'})
    page(root, 'alpha/items/one.md', {'page_id': 'one', 'page_type': 'claim', 'status': 'active', 'amount': 5})
    write(root, 'wiki.config.yaml', 'paths:\n  memory_root: alpha\n')
    commit(root, approve=True)
    legacy = receipt(packet(root, load_policy(root, 'refs/remotes/origin/main')))
    assert 'authority_format' not in legacy

    rule = {'from_context': '.', 'to_context': CONTEXT, 'selector': 'AGENTS.md',
            'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    access = {'.': {'owner': 'root operator', 'policy': {'read': ['self'], 'write': ['self']}, 'exports': [rule]},
              CONTEXT: {'owner': 'alpha operator', 'policy': {'read': ['self', 'AGENTS.md'], 'write': ['self']},
                        'imports': [rule]}}
    config = {'paths': {'memory_root': CONTEXT},
              'audit': {'freshness_scope': 'impact', 'information_impact': 'use_scoped'},
              'context_access': access}
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    write(root, 'AGENTS.md', '# Synthetic root instructions\n')
    write(root, 'alpha/AGENTS.md', '# Synthetic alpha instructions\n')
    page(root, 'alpha/evidence.md', {'page_id': 'evidence', 'page_type': 'source'})
    consumer = {'page_id': 'interpretation', 'page_type': 'claim', 'status': 'active',
                'confidence': 'confirmed', 'verified_at': TODAY.isoformat(),
                'evidence_refs': ['alpha/evidence.md'], 'information_requirements': [legacy]}
    page(root, CONSUMER, consumer)
    current = {'target': CONSUMER, 'fields': ['body'], 'temporal': 'current', 'max_age_days': 30}
    page(root, DEPENDENT, {'page_id': 'dependent', 'page_type': 'claim', 'confidence': 'confirmed',
                           'verified_at': TODAY.isoformat(), 'evidence_refs': ['alpha/evidence.md'],
                           'information_requirements': [current]})
    page(root, ACTION, {'page_id': 'action', 'page_type': 'action', 'action_state': 'open',
                        'information_requirements': [current]})
    page(root, CHAINED_ACTION, {'page_id': 'chained-action', 'page_type': 'action', 'action_state': 'open',
                               'information_requirements': [{**current, 'target': DEPENDENT}]})
    page(root, HISTORICAL_ACTION, {'page_id': 'historical-action', 'page_type': 'action', 'action_state': 'open',
                                  'information_requirements': [{**current, 'temporal': 'historical'}]})
    page(root, STATUS_ACTION, {'page_id': 'status-action', 'page_type': 'action', 'action_state': 'open',
                              'information_requirements': [{**current, 'fields': ['status']}]})
    base = commit(root, approve=True)
    folder_policy = load_policy(root, base, 'wiki.config.yaml')
    qualify_folder_context(root, folder_policy, CONTEXT, CONTEXT, 'alpha/index.md', 100000)
    folder = receipt(packet(root, folder_policy, folder=True))
    assert folder['authority_format'] == 'folder'
    git(root, 'checkout', '-qb', 'wiki/retire-query')
    return root, base, consumer, legacy, folder


def retire(consumer, requirement):
    values = deepcopy(consumer)
    values['status'] = 'superseded'
    values['information_requirements'] = []
    values['historical_query_receipts'] = [{'requirement': deepcopy(requirement), 'reason': 'Historical interpretation superseded.'}]
    return values


def report(root, base, head):
    return repository_report(root, load_config(root), base, today=TODAY, query_context=CONTEXT,
                             query_policy_revision=base, query_head=head)


def use(root, action=ACTION):
    graph = authored_graph(root, load_config(root))
    return assess_information_use(bind_verification_coverage(root, graph), action, now=NOW)


def test_retirement_records_unverified_history_and_blocks_current_action(history, monkeypatch):
    root, base, consumer, legacy, _ = history
    assert use(root)['ready'], 'The baseline current use must be qualified before the retirement.'
    assert use(root, CHAINED_ACTION)['ready']
    assert use(root, HISTORICAL_ACTION)['ready']
    assert use(root, STATUS_ACTION)['ready']
    archived = retire(consumer, legacy)
    page(root, CONSUMER, archived)
    head = commit(root)

    # Retirement preserves the old authority record; it must not open member
    # bodies or pretend to revalidate historical selections.
    from wiki_core.repository_reader import RepositoryReader
    original = RepositoryReader._document
    def reject_member_read(reader, path, **kwargs):
        assert path != 'alpha/items/one.md', 'retirement attempted to revalidate legacy members'
        return original(reader, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, '_document', reject_member_read)
    result = report(root, base, head)
    rows = [row for row in result['pending_reviews'] if row['path'] == CONSUMER and row['reason'] == 'historical_query_retired']
    assert rows and all(row['state'] == 'review_pending' and row['verification_performed'] is False for row in rows)
    assert result['query_revalidation']['fact_freshness'] == 'not_assessed'
    assert result['query_revalidation']['affected'] == 0
    assert any(row['path'] == DEPENDENT and not row['verification_performed'] for row in result['pending_reviews'])
    assert any(row['path'] == ACTION and not row['verification_performed'] for row in result['pending_reviews'])
    assert any(row['path'] == DEPENDENT and row['reason'] == 'retired_query_consumer_requires_review'
               for row in result['pending_reviews'])
    for action in (ACTION, CHAINED_ACTION):
        assert any(row['path'] == action and row['reason'] == 'retired_query_active_consumer_requires_review' for row in result['blockers'])
        assessment = use(root, action)
        assert not assessment['ready']
        assert any('information_archived_query_requires_review' in row['blockers'] for row in assessment['requirements'])
    assert use(root, HISTORICAL_ACTION)['ready']
    for action in (HISTORICAL_ACTION, STATUS_ACTION):
        assert not any(row['path'] == action and row['reason'] == 'retired_query_active_consumer_requires_review'
                       for row in result['blockers'])
        assert not any('information_archived_query_requires_review' in row['blockers']
                       for row in use(root, action)['requirements'])
    recorded = yaml.safe_load(git(root, 'show', f'{head}:{CONSUMER}').split('---', 2)[1])
    assert recorded['historical_query_receipts'][0]['requirement'] == legacy
    for path in (DEPENDENT, ACTION, CHAINED_ACTION):
        values = yaml.safe_load((root / path).read_text().split('---', 2)[1])
        values['information_requirements'][0]['temporal'] = 'historical'
        page(root, path, values)
    head = commit(root)
    completed = report(root, base, head)
    assert completed['ok'] and not completed['blockers']
    assert any(row['reason'] == 'historical_query_retired' and not row['verification_performed']
               for row in completed['pending_reviews'])


def test_current_query_cannot_use_archived_selection_or_filter(history):
    root, _base, consumer, legacy, _folder = history
    archived = retire(consumer, legacy)
    archived['amount'] = 5
    page(root, CONSUMER, archived)
    for path in (DEPENDENT, ACTION, CHAINED_ACTION):
        values = yaml.safe_load((root / path).read_text().split('---', 2)[1])
        values['information_requirements'][0]['temporal'] = 'historical'
        page(root, path, values)
    base = commit(root, approve=True)
    policy = load_policy(root, base, 'wiki.config.yaml')
    qualify_folder_context(root, policy, CONTEXT, CONTEXT, 'alpha/index.md', 100000)
    for field, filters, temporal, blocked in [('amount', {'status': 'superseded'}, 'current', True),
        ('status', {'amount': 99}, 'current', True), ('status', {'status': 'superseded'}, 'current', False),
        ('amount', {'status': 'superseded'}, 'historical', False)]:
        selection = {'target': 'alpha/index.md', 'reason': 'synthetic', 'use': 'interpret',
                     'classification': 'synthetic', 'query': {'scope': 'alpha', 'filters': filters,
                     'field': field, 'max_enumerated': 40, 'max_matches': 10, 'max_scan_bytes': 100000}}
        pkt = build_packet(root, policy, CONTEXT, base, [], 100000, task_id='query-task', goal='review',
                           output='alpha/new-query.md', integrator='reviewer', queries=[selection],
                           entry_folder=CONTEXT)
        page(root, 'alpha/new-query.md', {'page_id': 'new-query', 'page_type': 'claim',
                                         'information_requirements': [receipt(pkt, temporal=temporal)]})
        head = commit(root)
        result = report(root, base, head)
        assert any(row['path'] == 'alpha/new-query.md' and 'revalidation' in row['reason']
                   for row in result['blockers']) is blocked, (field, filters, temporal, result['blockers'])


@pytest.mark.parametrize('case', [
    'deleted', 'changed_digest', 'invented', 'also_live', 'receipt_edit',
    'current', 'folder', 'not_superseded', 'empty_reason', 'empty_archive',
])
def test_retirement_rejects_unpreserved_or_unauthorized_history(history, case):
    root, base, consumer, legacy, folder = history
    requirement = deepcopy(legacy)
    if case == 'current':
        requirement['temporal'] = 'current'
    if case == 'folder':
        requirement = deepcopy(folder)
    if case in {'current', 'folder', 'invented'}:
        consumer = deepcopy(consumer)
        consumer['information_requirements'] = [] if case == 'invented' else [requirement]
        page(root, CONSUMER, consumer)
        base = commit(root, approve=True)
    values = retire(consumer, requirement)
    if case == 'deleted':
        values.pop('historical_query_receipts')
    elif case == 'changed_digest':
        values['historical_query_receipts'][0]['requirement']['selected_digest'] = '0' * 64
    elif case == 'also_live':
        values['information_requirements'] = [requirement]
    elif case == 'not_superseded':
        values['status'] = 'active'
    elif case == 'empty_reason':
        values['historical_query_receipts'][0]['reason'] = '  '
    elif case == 'empty_archive':
        values['historical_query_receipts'] = []
    elif case == 'receipt_edit':
        page(root, CONSUMER, values)
        base = commit(root, approve=True)
        values['historical_query_receipts'][0]['reason'] = 'Edited later.'
    page(root, CONSUMER, values)
    head = commit(root)
    result = report(root, base, head)
    # An open action may block valid retirement; each invalid transition must
    # independently fail at the archived page.
    assert not result['ok'], result
    assert (any(row.get('path') == CONSUMER for row in result['blockers'])
            or any(CONSUMER in str(error) for error in result['relation_errors'])), result
    # An invented or edited archive must also fail when no query context is
    # supplied, not just in the authority-bound audit.
    if case in {'invented', 'receipt_edit'}:
        generic = repository_report(root, load_config(root), base, today=TODAY)
        assert not generic['ok'], generic
        assert (any(row.get('path') == CONSUMER for row in generic['blockers'])
                or any(CONSUMER in str(error) for error in generic['relation_errors'])), generic
