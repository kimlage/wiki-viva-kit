import pytest

from tests.test_context_flow import (repo, git, policy, folder_requirements_setup,
                                     folder_requirements_proposal, folder_requirements_policy)  # noqa: F401
from wiki_core import context_policy
from wiki_core.context_integration import preflight, IntegrationError
from wiki_core.context_packet import build_packet, validate_result
from wiki_core.context_requirements import requirements_from_result, RequirementError
from wiki_core.repository_reader import RepositoryReader


def test_legacy_packet_is_refused_under_folder_authority_before_body_reads(repo, monkeypatch):
    old = policy(repo)
    oldsha = git(repo, 'rev-parse', 'HEAD')
    evidence = [{'ref': 'finance/tax/source.md', 'producer': 'tax',
                 'reason': 'synthetic', 'use': 'interpret', 'classification': 'synthetic',
                 'section': 'amount'}]
    legacy = build_packet(repo, old, 'costs', oldsha, evidence, 10000,
                          task_id='old', goal='synthetic', output='proposal', integrator='reviewer')
    legacy_result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed',
                     'task_id': 'old', 'context_id': 'costs', 'packet_digest': legacy['packet_digest'],
                     'changes': [{'path': 'finance/costs/result.md', 'action': 'modified'}],
                     'read_coverage': {'observed_refs': legacy['declared_read_set'], 'missing': []},
                     'blockers': []}
    assert validate_result(legacy_result, legacy)
    binding = folder_requirements_setup(repo)
    current, base, head, packet, result = folder_requirements_proposal(repo, binding)
    preflight_args = dict(context_id='finance/costs', base=base, head=head,
                          branch='wiki/costs-task-1', trusted_binding=binding)
    assert preflight(repo, current, packet=packet, result=result, **preflight_args)['state'] == 'independent_review_required'

    def forbidden(*args, **kwargs):
        pytest.fail('historical or packet body opened')
    with monkeypatch.context() as scoped:
        scoped.setattr(context_policy, '_policy_at', forbidden)
        scoped.setattr(RepositoryReader, 'read', forbidden)
        with pytest.raises(IntegrationError, match='packet authority format differs'):
            preflight(repo, current, packet=legacy, result=legacy_result, **preflight_args)

    git(repo, 'update-ref', 'refs/remotes/origin/main', head)
    current = folder_requirements_policy(repo)
    req_args = dict(output_path='finance/costs/result.md', proposal_head=head,
                    temporal='current', max_age_days=30)
    # The old context ID differs from the folder ID; no mapping is assumed.
    with monkeypatch.context() as scoped:
        scoped.setattr(context_policy, '_policy_at', forbidden)
        scoped.setattr(RepositoryReader, 'read', forbidden)
        with pytest.raises(RequirementError, match='packet authority format differs'):
            requirements_from_result(repo, current, packet=legacy, result=legacy_result, **req_args)
    positive = requirements_from_result(repo, current, packet=packet, result=result,
                                        trusted_binding=binding, **req_args)
    assert positive['read_claim'] == 'reported_not_verified'
    assert positive['write'] == 'not_performed'
