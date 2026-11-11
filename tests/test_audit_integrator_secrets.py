"""Synthetic integration of host-bound role and worktree secrets selection."""
import pytest

from tests.test_context_flow import repo
from tests.test_integrator_context_read_binding import bound_integrator, snapshot
from wiki_core import audit_worktree_selection as secrets
from wiki_core.context_policy import PolicyError
from wiki_core.coordination_context import CoordinationBinding


@pytest.mark.parametrize('bound_integrator', ['audit_no_specific'], indirect=True)
def test_integrator_scans_owners_but_executor_does_not_inherit_read(bound_integrator):
    root, base, binding, contexts = bound_integrator
    snap = snapshot(bound_integrator)
    plan = secrets.plan_worktree_secrets(snap)
    names = {item['path'] for item in plan['selection']['inputs']}
    assert {'finance/tax/source.md', 'finance/costs/result.md'} <= names
    result = secrets.scan_worktree_secrets(root, binding, context_id='.', approved_revision=base,
        base=base, head=base, branch='wiki/synthetic-integrator', normative_paths=['wiki.config.yaml'],
        inventory_sha256=snap['inventory_sha256'], plan_sha256=plan['plan_sha256'], admit=lambda _: True)
    assert result['state'] == 'completed' and result['global_audit'] == 'not_performed'
    assert result['host_admission'] == 'external_not_verified'
    ordinary = CoordinationBinding(contexts, 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(PolicyError, match='selection unavailable'):
        secrets.plan_worktree_secrets(snapshot(bound_integrator, ordinary))


def test_specific_deny_blocks_whole_secret_scope_before_bodies(bound_integrator, monkeypatch):
    snap = snapshot(bound_integrator)
    monkeypatch.setattr(secrets, '_worktree_bytes', lambda *_: pytest.fail('body read'))
    with pytest.raises(PolicyError, match='selection unavailable'):
        secrets.plan_worktree_secrets(snap)
