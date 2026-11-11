"""Synthetic graph-dispatch experiment; not an integral audit or host proof."""
from pathlib import Path

import pytest

from tests.test_audit_r1_inventory import repo, run
from tests.test_wiki_audit import _load_wiki_audit
from wiki_core import audit_r1_inventory as r1
from wiki_core.config import WikiConfig
from wiki_core.context_policy import PolicyError
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.graph.page_graph import select_page_graph_inputs


def _page(name):
    return f'---\npage_id: {name}\npage_type: note\ntitle: {name}\n---\n\n# {name}\n'


def test_graph_registry_runner_can_consume_selected_bodies(repo, monkeypatch):
    root, _, _, _ = repo
    memory = root / 'memories'
    memory.mkdir()
    (memory / 'index.md').write_text(_page('root'))
    (memory / 'note.md').write_text(_page('note'))
    snapshot = run(repo)
    plan = select_page_graph_inputs(snapshot, WikiConfig())
    # This stub represents a synthetic host, not independent admission.
    assert (lambda _plan: True)(plan)
    contents = {item['path']: r1._worktree_bytes(root, item)
                for item in plan['selection']['inputs']}
    reads = r1.SelectedReads(root, snapshot['physical'], contents,
                             missing=snapshot['missing_tracked'])
    audit = _load_wiki_audit()
    monkeypatch.setattr(audit, 'ROOT', root)
    monkeypatch.setattr(Path, 'read_text', lambda *_a, **_kw: pytest.fail('body reopened'))
    ctx = audit.AuditContext(WikiConfig())
    ctx.graph_reads = reads
    dict(audit.CHECKS)['page_graph'](ctx)
    assert not ctx.errors
    assert plan['global_audit'] == 'not_performed'


def test_graph_plan_denial_precedes_runner_and_body_reads(repo, monkeypatch):
    root, _, _, _ = repo
    (root / 'restricted/denied.md').write_text(_page('denied'))
    snapshot = run(repo)
    config = WikiConfig()
    config.paths['memory_root'] = '.'
    monkeypatch.setattr(r1, '_worktree_bytes', lambda *_: pytest.fail('body read before denial'))
    with pytest.raises(PolicyError, match='selection unavailable'):
        select_page_graph_inputs(snapshot, config)


def test_real_graph_check_requires_host_admission_and_reports_partial_scope(repo, monkeypatch):
    root, base, _, head = repo
    (root / 'memories').mkdir()
    (root / 'memories/index.md').write_text(_page('root'))
    audit = _load_wiki_audit()
    monkeypatch.setattr(audit, 'ROOT', root)
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main')
    params = dict(trusted_binding=binding, context_id='.', approved_revision=base, base=base,
                  head=head, branch='wiki/synthetic', normative_paths=['wiki.config.yaml'])
    planned = audit.audit_context_bound_graph(**params, plan_only=True)
    assert planned['state'] == 'selection_only'
    execution = dict(inventory_sha256=planned['inventory_sha256'],
                     plan_sha256=planned['plan']['plan_sha256'])
    original = r1._worktree_bytes
    def before_admission(root, item):
        if item['path'].startswith('memories/'):
            pytest.fail('graph body read before host admission')
        return original(root, item)
    monkeypatch.setattr(r1, '_worktree_bytes', before_admission)
    with pytest.raises(PolicyError, match='host admission unavailable'):
        audit.audit_context_bound_graph(**params, **execution, host_admit=lambda _: False)
    decisions = iter([True, False])
    partial = audit.audit_context_bound_graph(**params, **execution,
                                               host_admit=lambda _: next(decisions))
    assert partial['state'] == 'partial'
    assert partial['source_body_attempts_may_have_read_bytes'] == 0
    assert partial['global_audit'] == 'not_performed'
    monkeypatch.setattr(r1, '_worktree_bytes', original)
    result = audit.audit_context_bound_graph(**params, **execution, host_admit=lambda _: True)
    assert result['state'] == 'completed'
    assert result['source_bodies_validated'] == 1
    assert result['scope'] == 'page_graph_only'
    assert result['global_audit'] == 'not_performed'
    assert result['gate_state'] == 'blocked_incomplete_coverage'
