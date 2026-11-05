"""Retire one obsolete historical v1 example without replaying its sources."""
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
    base = commit(root)
    git(root, 'checkout', '-qb', 'wiki/retire-old-query')
    path = root / TASK['output']
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
