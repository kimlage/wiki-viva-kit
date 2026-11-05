"""Retire one obsolete historical v1 example without replaying its sources."""
import pytest
import yaml

from tests.test_context_flow import repo
from tests.test_context_dynamic_selection import (collection, configure_audit, packet, requirement, declare, git, commit, TASK)
from wiki_core.config import load_config
from wiki_core.freshness_impact import repository_report


def test_superseded_legacy_query_remains_in_git_and_does_not_claim_revalidation(collection, monkeypatch):
    root = collection
    configure_audit(root)
    req = requirement(packet(root))
    req['temporal'] = 'historical'
    declare(root, req)
    path = root / TASK['output']
    parts = path.read_text().split('---\n', 2)
    values = yaml.safe_load(parts[1]); values['status'] = 'active'
    path.write_text('---\n' + yaml.safe_dump(values) + '---\n' + parts[2])
    base = commit(root)
    git(root, 'checkout', '-qb', 'wiki/retire-old-query')
    parts = path.read_text().split('---\n', 2)
    values = yaml.safe_load(parts[1])
    values['status'] = 'superseded'
    values.pop('information_requirements')
    path.write_text('---\n' + yaml.safe_dump(values) + '---\nHistorical reference.\n')
    (root / 'AGENTS.md').write_text('# Updated instruction\n')
    git(root, 'add', TASK['output'], 'AGENTS.md')
    git(root, 'commit', '-qm', 'retire old example')
    from wiki_core.repository_reader import RepositoryReader
    monkeypatch.setattr(RepositoryReader, 'read', lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError('retirement must not read historical members')))
    report = repository_report(root, load_config(root), base)
    assert report['ok'] and not report['blockers']
    assert any(row['path'] == TASK['output'] and row['reason'] == 'legacy_query_retired'
               and not row['verification_performed'] for row in report['pending_reviews'])
    original = yaml.safe_load(git(root, 'show', f'{base}:{TASK["output"]}').split('---', 2)[1])
    assert original['information_requirements'][0] == req
    action = {'page_id':'consumer-action', 'page_type':'action', 'action_state':'open',
              'information_requirements':[{'target':TASK['output'], 'fields':['body'],
                                           'temporal':'current', 'max_age_days':30}]}
    (root / 'finance/costs/action.md').write_text('---\n' + yaml.safe_dump(action) + '---\nUse.\n')
    git(root, 'add', 'finance/costs/action.md'); git(root, 'commit', '-qm', 'attempt current use')
    report = repository_report(root, load_config(root), base)
    assert not report['ok']
    assert any(row['path'] == 'finance/costs/action.md' and row['reason'] == 'superseded_information_in_active_use'
               for row in report['blockers'])


def test_proposal_commit_cannot_be_used_as_approved_retirement_base(collection):
    root = collection
    configure_audit(root)
    req = requirement(packet(root)); req['temporal'] = 'historical'
    declare(root, req)
    path = root / TASK['output']
    parts = path.read_text().split('---\n', 2)
    values = yaml.safe_load(parts[1]); values['status'] = 'active'
    path.write_text('---\n' + yaml.safe_dump(values) + '---\n' + parts[2])
    git(root, 'checkout', '-qb', 'wiki/unapproved-base')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'unapproved requirement')
    base = git(root, 'rev-parse', 'HEAD')
    assert base != git(root, 'rev-parse', 'refs/remotes/origin/main')
    values['status'] = 'superseded'; values.pop('information_requirements')
    path.write_text('---\n' + yaml.safe_dump(values) + '---\nHistorical reference.\n')
    git(root, 'add', TASK['output']); git(root, 'commit', '-qm', 'retire')
    report = repository_report(root, load_config(root), base)
    assert not report['ok']
    assert any(row['path'] == TASK['output'] and 'revalidation' in row['reason'] for row in report['blockers'])


@pytest.mark.parametrize('old_flag', ['no', 'eligible'])
def test_retirement_marks_excluded_query_candidate_for_review(repo, monkeypatch, old_flag):
    from tests import test_context_dynamic_selection as legacy
    from tests import test_dynamic_impact_closure as scoped
    root = legacy.collection.__wrapped__(repo)
    old = legacy.requirement(legacy.packet(root)); old['temporal'] = 'historical'
    legacy.declare(root, old)
    path = root / TASK['output']
    parts = path.read_text().split('---\n', 2)
    values = yaml.safe_load(parts[1]); values.update(status='active', flag=old_flag, amount=5)
    path.write_text('---\n' + yaml.safe_dump(values) + '---\n' + parts[2])
    scoped.collection.__wrapped__(root)
    query = {'target':scoped.ANCHOR, 'reason':'synthetic filter', 'use':'interpret', 'classification':'synthetic',
             'query':{'scope':scoped.CONTEXT, 'filters':{'flag':'eligible'}, 'field':'amount',
                      'max_enumerated':30, 'max_matches':10, 'max_scan_bytes':100000}}
    pkt = scoped.build_packet(root, scoped.policy(root), scoped.CONTEXT, git(root,'rev-parse','HEAD'), [], 50000,
                              queries=[query], task_id='query-task', goal='review',
                              output='finance/costs/derived/query.md', integrator='reviewer')
    qpath = root / 'finance/costs/derived/query.md'
    qpath.parent.mkdir()
    qpath.write_text('---\n' + yaml.safe_dump({'page_id':'query', 'page_type':'claim',
                     'amount':7, 'information_requirements':[scoped.requirement(pkt)]}) + '---\nQuery.\n')
    commit(root)
    downstream_query = {'target':scoped.ANCHOR, 'reason':'synthetic downstream filter', 'use':'interpret', 'classification':'synthetic',
                        'query':{'scope':'finance/costs/derived', 'filters':{'page_id':'query'}, 'field':'amount',
                                 'max_enumerated':30, 'max_matches':10, 'max_scan_bytes':100000}}
    downstream = scoped.build_packet(root, scoped.policy(root), scoped.CONTEXT, git(root,'rev-parse','HEAD'), [], 50000,
                                     queries=[downstream_query], task_id='downstream-query', goal='review',
                                     output='finance/costs/consumer.md', integrator='reviewer')
    (root / 'finance/costs/consumer.md').write_text('---\n' + yaml.safe_dump({'page_id':'consumer', 'page_type':'claim',
        'information_requirements':[scoped.requirement(downstream)]}) + '---\nConsumer.\n')
    (root / 'finance/tax/private-query.md').write_text('---\n' + yaml.safe_dump({'page_id':'other-owner', 'page_type':'claim',
        'information_requirements':[scoped.requirement(downstream)]}) + '---\nOther owner.\n')
    (root / 'finance/costs/action.md').write_text('---\n' + yaml.safe_dump({'page_id':'action', 'page_type':'action',
        'action_state':'blocked', 'next_action':'Review', 'blocker_reason':'Needs review',
        'information_requirements':[{'target':'finance/costs/consumer.md', 'fields':['*'],
                                     'temporal':'current', 'max_age_days':30}]}) + '---\nAction.\n')
    base = commit(root)
    git(root, 'checkout', '-qb', 'wiki/retire-filter-candidate')
    parts = path.read_text().split('---\n', 2)
    values = yaml.safe_load(parts[1]); values.update(status='superseded', flag='no'); values.pop('information_requirements')
    path.write_text('---\n' + yaml.safe_dump(values) + '---\n' + parts[2])
    git(root, 'add', TASK['output']); git(root, 'commit', '-qm', 'retire old query')
    head = git(root, 'rev-parse', 'HEAD')
    from wiki_core.repository_reader import RepositoryReader
    document = RepositoryReader._document
    def owner_only(reader, ref, *args, **kwargs):
        assert not ref.startswith('finance/tax/'), 'query closure must not read another owner'
        return document(reader, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, '_document', owner_only)
    report = repository_report(root, load_config(root), base, query_context=scoped.CONTEXT,
                               query_policy_revision=base, query_head=head)
    assert any(row['path']=='finance/costs/derived/query.md' and row['reason'] in {'dynamic_query_upstream_pending', 'dynamic_query_changed'}
               and not row['verification_performed'] for row in report['pending_reviews'])
    assert any(row['path']=='finance/costs/consumer.md' and row['reason']=='dynamic_query_upstream_pending'
               for row in report['pending_reviews'])
    assert any(row['path']=='finance/costs/action.md' and row['reason']=='legacy_query_current_consumer_requires_review'
               for row in report['blockers'])
    assert any(row['path']=='finance/tax/private-query.md' and row['reason']=='dynamic_query_requires_authorized_revalidation'
               for row in report['blockers'])
