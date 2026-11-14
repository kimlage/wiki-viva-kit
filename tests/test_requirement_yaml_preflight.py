import pytest

from tests.test_context_dynamic_selection import (audit_collection, collection, repo, git,
    folder_policy, folder_build_packet, AUDIT_CONTEXT)  # noqa: F401
from wiki_core.context_integration import preflight, IntegrationError


@pytest.mark.parametrize('action', ['created', 'modified'])
@pytest.mark.parametrize('duplicate', [False, True])
def test_preflight_rejects_hidden_requirement(audit_collection, action, duplicate):
    root = audit_collection
    target = ('finance/costs/new-synthetic.md' if action == 'created'
              else 'finance/costs/result.md')
    base = git(root, 'rev-parse', 'HEAD')
    policy = folder_policy(root)
    packet = folder_build_packet(root, policy, AUDIT_CONTEXT, base, [], 50000,
        task_id='yaml-synthetic', goal='review', output=target, integrator='reviewer')
    requirement = ('information_requirements:\n'
                   '  - target: finance/costs/other.md\n'
                   '    fields: [body]\n'
                   '    temporal: current\n'
                   '    max_age_days: 30\n'
                   f'    consumed_revision: {base}\n')
    text = ('---\npage_type: claim\n' + requirement
            + ('information_requirements: []\n' if duplicate else '')
            + '---\nSynthetic claim.\n')
    git(root, 'checkout', '-qb', 'wiki/yaml-synthetic')
    (root / target).write_text(text)
    git(root, 'add', target); git(root, 'commit', '-qm', 'synthetic proposal')
    head = git(root, 'rev-parse', 'HEAD')
    result = {'schema_version': 'wiki.task-result/v1', 'task_id': packet['task_id'],
              'context_id': packet['context_id'], 'packet_digest': packet['packet_digest'],
              'status': 'completed', 'blockers': [],
              'changes': [{'path': target, 'action': action}],
              'read_coverage': {'observed_refs': packet['declared_read_set'],
                                'observed_queries': [], 'missing': packet['coverage']['missing']}}
    with pytest.raises(IntegrationError) as error:
        preflight(root, policy, context_id=AUDIT_CONTEXT, base=base, head=head,
                  branch='wiki/yaml-synthetic', packet=packet, result=result)
    if duplicate:
        assert str(error.value) == 'ambiguous information requirements'
    else:
        assert 'requirement does not match task evidence' in str(error.value)
