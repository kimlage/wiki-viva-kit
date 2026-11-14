from copy import deepcopy

import pytest

from tests.test_context_dynamic_selection import (AUDIT_CONTEXT, audit_collection, collection,
    repo, page, commit, git, query, folder_packet, folder_requirement, folder_result,
    declare, folder_policy, folder_build_packet, TASK)  # noqa: F401
from wiki_core.context_integration import IntegrationError, preflight


def test_new_query_requirement_must_match_scalar_types(audit_collection):
    root = audit_collection
    page(root, 'first.md', amount=1)
    commit(root)
    base = git(root, 'rev-parse', 'HEAD')
    selected = folder_packet(root, [query(filters={'amount': True})])
    alternate = folder_packet(root, [query(filters={'amount': 1})])
    assert len(selected['query_selections'][0]['members']) == 0
    assert len(alternate['query_selections'][0]['members']) == 1
    assert selected['query_selections'][0]['query_id'] != alternate['query_selections'][0]['query_id']
    original = folder_requirement(selected)
    done = folder_result(selected, [{'path': 'finance/costs/result.md', 'action': 'modified'}])
    git(root, 'checkout', '-qb', 'wiki/query-types')
    for value, accepted in ((True, True), (1, False), (2, False)):
        proposed = deepcopy(original)
        proposed['query']['filters'] = {'amount': value}
        declare(root, proposed)
        git(root, 'add', '.'); git(root, 'commit', '-qm', 'synthetic query type')
        args = dict(context_id=AUDIT_CONTEXT, base=base, head=git(root, 'rev-parse', 'HEAD'),
                    branch='wiki/query-types', packet=selected, result=done)
        if accepted:
            assert preflight(root, folder_policy(root), **args)['state'] == 'independent_review_required'
        else:
            with pytest.raises(IntegrationError, match='query requirement'):
                preflight(root, folder_policy(root), **args)


def test_existing_query_filter_type_change_requires_new_selection(audit_collection):
    root = audit_collection
    original_packet = folder_packet(root, [query(filters={'amount': True})])
    alternate_packet = folder_packet(root, [query(filters={'amount': 1})])
    original = original_packet['query_selections'][0]
    alternate = alternate_packet['query_selections'][0]
    assert original['members'] == alternate['members'] == []
    for key in ('query_id', 'members_digest', 'selected_digest'):
        assert original[key] != alternate[key]
    requirement = folder_requirement(original_packet)
    declare(root, requirement)
    commit(root)
    base = git(root, 'rev-parse', 'HEAD')
    selected = folder_build_packet(root, folder_policy(root), AUDIT_CONTEXT, base, [], 50000, **TASK)
    assert not selected.get('query_selections')
    result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed',
              'task_id': selected['task_id'], 'context_id': selected['context_id'],
              'packet_digest': selected['packet_digest'],
              'changes': [{'path': 'finance/costs/result.md', 'action': 'modified'}],
              'read_coverage': {'observed_refs': selected['declared_read_set'],
                                'missing': selected['coverage']['missing']}, 'blockers': []}
    git(root, 'checkout', '-qb', 'wiki/existing-query-type')
    for changed, must_pass in ((False, True), (True, False)):
        proposed = deepcopy(requirement)
        if changed:
            proposed['query']['filters'] = {'amount': 1}
        declare(root, proposed)
        with (root / 'finance/costs/result.md').open('a') as output:
            output.write('Synthetic body change\n')
        git(root, 'add', '.'); git(root, 'commit', '-qm', 'synthetic query update')
        args = dict(context_id=AUDIT_CONTEXT, base=base, head=git(root, 'rev-parse', 'HEAD'),
                    branch='wiki/existing-query-type', packet=selected, result=result)
        if must_pass:
            assert preflight(root, folder_policy(root), **args)['state'] == 'independent_review_required'
        else:
            with pytest.raises(IntegrationError, match='query requirement does not match task selection'):
                preflight(root, folder_policy(root), **args)
