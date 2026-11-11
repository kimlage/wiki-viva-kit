"""Synthetic owner writes are not delegated by an integrator read role."""
from dataclasses import replace

import pytest

from tests.test_context_multi_owner_preflight import proposal, run
from tests.test_context_flow import git, repo
from wiki_core.context_integration import IntegrationError, preflight


def test_integrator_read_is_not_write_and_does_not_remove_owner_authority(proposal):
    binding = replace(proposal['binding'], integrator_read_context='.',
                      integrator_policy_revision=proposal['base'])
    root = next(part for part in proposal['participants'] if part['context_id'] == '.')
    # The integrator's read binding cannot approve this entire multi-owner
    # diff as a root-owned write, even though all contexts are in its binding.
    with pytest.raises(IntegrationError, match='write outside context'):
        preflight(proposal['root'], proposal['policy'], context_id='.', base=proposal['base'],
                  head=proposal['head'], branch=proposal['branch'], packet=root['packet'],
                  result=root['result'], trusted_binding=binding)

    # Independent owner packets and results retain their own write authority.
    # This is a review candidate, not evidence of host authentication or merge.
    result = run(proposal, trusted_binding=binding)
    assert {part['context_id'] for part in result['participants']} == set(proposal['paths'])
    assert result['state'] == 'independent_review_required'
    assert result['review'] == result['gates'] == result['merge'] == 'not_performed'

    # A separate proposal by the actual owner uses its own ordinary binding;
    # the read role is not required to preserve this authorized write.
    owner = next(part for part in proposal['participants'] if part['context_id'] == 'finance/costs')
    git(proposal['root'], 'checkout', '-qb', 'wiki/synthetic-owner-only', proposal['base'])
    (proposal['root'] / proposal['paths']['finance/costs']).write_text('Owner-authorized synthetic change.\n')
    git(proposal['root'], 'add', '.')
    git(proposal['root'], 'commit', '-qm', 'synthetic owner change')
    result = preflight(proposal['root'], proposal['policy'], context_id='finance/costs',
        base=proposal['base'], head=git(proposal['root'], 'rev-parse', 'HEAD'),
        branch='wiki/synthetic-owner-only', packet=owner['packet'], result=owner['result'],
        trusted_binding=proposal['binding'])
    assert result['state'] == 'independent_review_required'
    assert result['review'] == result['gates'] == result['merge'] == 'not_performed'
