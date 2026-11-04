"""Folder boundaries must never be admitted under unchanged v1 authority."""
import datetime as dt

import pytest
import yaml

from tests.test_context_flow import repo, git, approve, policy, make_proposal
from tests.test_context_dynamic_selection import collection
from tests.test_dynamic_impact_closure import setup_chain, TASK
from wiki_core.context_integration import IntegrationError, preflight
from wiki_core.config import load_config
from wiki_core.freshness_impact import repository_report
from wiki_core.information_relations import authored_graph
from wiki_core.information_use import assess_information_use, bind_normative_coverage


@pytest.mark.parametrize('name', ['AGENTS.md', 'AGENTS.override.md'])
@pytest.mark.parametrize('action', ['added', 'modified', 'deleted'])
def test_preflight_rejects_folder_boundary_changes(repo, name, action):
    path = 'finance/costs/nested/' + name
    target = repo / path
    if action != 'added':
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('Existing context instruction\n')
        git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'existing instruction'); approve(repo)
    p, base, _, packet, result = make_proposal(repo)
    if action == 'deleted':
        target.unlink()
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('New context instruction\n')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'boundary change')
    head = git(repo, 'rev-parse', 'HEAD')
    result['changes'].append({'path': path, 'action': {'added': 'created', 'modified': 'modified', 'deleted': 'deleted'}[action]})
    with pytest.raises(IntegrationError, match='folder instruction change'):
        preflight(repo, p, context_id='costs', base=base, head=head,
                  branch='wiki/costs-task-1', packet=packet, result=result)


@pytest.mark.parametrize('name', ['AGENTS.md', 'AGENTS.override.md'])
def test_new_folder_boundary_requires_query_requalification(collection, name):
    base = setup_chain(collection)
    git(collection, 'checkout', '-qb', 'wiki/folder-boundary')
    child = collection / 'finance/costs/items/nested'
    child.mkdir(parents=True, exist_ok=True)
    (child / name).write_text('New context boundary\n')
    git(collection, 'add', '.'); git(collection, 'commit', '-qm', 'new boundary')
    head = git(collection, 'rev-parse', 'HEAD')
    report = repository_report(collection, load_config(collection), base,
                               query_context='costs', query_policy_revision=base, query_head=head)
    assert any(r['path'] == TASK['output'] and r['reason'] == 'dynamic_query_requalification_required'
               and not r['verification_performed'] for r in report['pending_reviews'])


def test_new_boundary_does_not_certify_old_normative_coverage(repo):
    rev = git(repo, 'rev-parse', 'HEAD')
    req = {'target': 'rules.md', 'fields': ['*'], 'temporal': 'current', 'max_age_days': 30,
           'consumed_revision': rev, 'use': 'normative', 'source_kind': 'mandatory', 'classification': 'internal'}
    target = repo / 'finance/costs/result.md'
    target.write_text('---\n' + yaml.safe_dump({'page_id': 'task', 'page_type': 'action', 'action_state': 'open',
                                                 'information_requirements': [req]}) + '---\nTask\n')
    (repo / 'wiki.config.yaml').write_text('paths:\n  memory_root: finance\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'approved task'); approve(repo)
    base = git(repo, 'rev-parse', 'HEAD')
    before = authored_graph(repo, load_config(repo))
    bound = bind_normative_coverage(repo, before, policy(repo), 'costs', head=base)
    assert assess_information_use(bound, 'finance/costs/result.md', now=dt.datetime.now(dt.timezone.utc))['requirements'][0]['ready']
    git(repo, 'checkout', '-qb', 'wiki/add-boundary')
    (repo / 'finance/costs/AGENTS.md').write_text('New context boundary\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'new boundary')
    head = git(repo, 'rev-parse', 'HEAD')
    graph = authored_graph(repo, load_config(repo))
    bound = bind_normative_coverage(repo, graph, policy(repo), 'costs', head=head)
    assert not assess_information_use(bound, 'finance/costs/result.md', now=dt.datetime.now(dt.timezone.utc))['requirements'][0]['ready']
