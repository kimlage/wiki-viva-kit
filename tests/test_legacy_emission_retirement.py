"""Historical v1 reconstruction remains distinct from operational emission."""

import pytest

from tests.test_context_flow import make_proposal, repo
from wiki_core import coordination_context as coord
from wiki_core import context_requirements as requirements
from wiki_core.context_integration import preflight
from wiki_core.context_packet import validate_result


def test_v1_preflight_refused_before_policy_or_reconstruction(repo, monkeypatch):
    policy, base, head, packet, result = make_proposal(repo)
    # Existing low-level history helpers still validate/reconstruct old data.
    assert validate_result(result, packet)
    assert preflight(repo, policy, context_id='costs', base=base, head=head,
                     branch='wiki/costs-task-1', packet=packet, result=result)['state'] == 'independent_review_required'
    binding = coord.CoordinationBinding(('costs',), 'refs/remotes/origin/main', 'context.yaml')
    payload = {'context_id': 'costs', 'approved_revision': base, 'base': base, 'head': head,
               'branch': 'wiki/costs-task-1', 'packet': packet, 'result': result}
    monkeypatch.setattr(coord, '_policy', lambda *a, **kw: pytest.fail('v1 policy opened'))
    monkeypatch.setattr(coord, 'preflight', lambda *a, **kw: pytest.fail('v1 preflight executed'))
    with pytest.raises(coord.ProtectedCoordinationError) as error:
        coord.prepare_preflight(repo, binding, payload)
    assert error.value.code == 'coordination_v1_retired'


def test_v1_requirements_refused_before_policy_or_result_read(repo, monkeypatch):
    policy, _base, head, packet, result = make_proposal(repo)
    monkeypatch.setattr(requirements, '_fresh', lambda *a, **kw: pytest.fail('v1 policy opened'))
    monkeypatch.setattr(requirements, 'validate_result', lambda *a, **kw: pytest.fail('v1 result inspected'))
    with pytest.raises(requirements.RequirementError, match='v1 is historical only'):
        requirements.requirements_from_result(repo, policy, packet=packet, result=result,
            output_path='finance/costs/result.md', proposal_head=head, temporal='current', max_age_days=30)
