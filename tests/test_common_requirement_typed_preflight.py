from copy import deepcopy

import pytest

from tests.test_context_dynamic_selection import (AUDIT_CONTEXT, TASK, audit_collection,
    collection, repo, commit, git, declare, folder_build_packet, folder_policy)  # noqa: F401
from wiki_core.context_integration import IntegrationError, preflight


def test_common_requirement_type_change_is_validated(audit_collection):
    root = audit_collection
    requirement = {'target': 'finance/costs/items/first.md', 'fields': ['*'],
                   'temporal': 'current', 'max_age_days': 1,
                   'use': 'interpret', 'classification': 'synthetic'}
    declare(root, requirement)
    commit(root)
    base = git(root, 'rev-parse', 'HEAD')
    packet = folder_build_packet(root, folder_policy(root), AUDIT_CONTEXT, base, [], 50000, **TASK)
    result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed',
              'task_id': packet['task_id'], 'context_id': packet['context_id'],
              'packet_digest': packet['packet_digest'],
              'changes': [{'path': 'finance/costs/result.md', 'action': 'modified'}],
              'read_coverage': {'observed_refs': packet['declared_read_set'],
                                'missing': packet['coverage']['missing']}, 'blockers': []}
    git(root, 'checkout', '-qb', 'wiki/common-type')
    for value, expected in ((1, None), (True, 'invalid proposed information requirement'),
                            (1.0, 'invalid proposed information requirement'),
                            (2, 'new requirement is unpinned')):
        proposed = deepcopy(requirement)
        proposed['max_age_days'] = value
        declare(root, proposed)
        with (root / 'finance/costs/result.md').open('a') as output:
            output.write('Synthetic body change\n')
        git(root, 'add', '.'); git(root, 'commit', '-qm', 'synthetic requirement type')
        args = dict(context_id=AUDIT_CONTEXT, base=base, head=git(root, 'rev-parse', 'HEAD'),
                    branch='wiki/common-type', packet=packet, result=result)
        if expected is None:
            assert preflight(root, folder_policy(root), **args)['state'] == 'independent_review_required'
        else:
            with pytest.raises(IntegrationError, match=expected):
                preflight(root, folder_policy(root), **args)
