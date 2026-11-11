"""Plan a bounded legacy history search; not a complete audit or host boundary.

The host must independently qualify bootstrap, actor, historical authority,
output and isolation.  This module does not change legacy audit callers.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wiki_core import audit_r1_inventory as r1
from wiki_core.context_policy import PolicyError, revision, safe_path

_PATTERNS = {
    'action_state_transitions': r'page_type[[:space:]]*:',
    'source_lifecycle_transitions': r'^page_type:[[:space:]]*[\'\"]?source[\'\"]?[[:space:]]*$',
}


def plan_base_markdown(inventory: dict, *, check: str, memory_root: str) -> dict:
    """Select every base Markdown candidate under a caller-supplied root.

    The caller must establish that the root is the real approved configuration.
    Denied paths and aliases refuse the whole selection via the R1 selector;
    they are never silently excluded. No target body is read by this function.
    """
    if not isinstance(check, str) or check not in _PATTERNS or not isinstance(memory_root, str):
        raise PolicyError('historical search selection unavailable')
    if safe_path(memory_root) != memory_root or memory_root.endswith('/'):
        raise PolicyError('historical search selection unavailable')
    try:
        base = inventory['base']
        tree = inventory['trees'][base]
        paths = sorted(path for path in tree if path.startswith(memory_root + '/') and path.endswith('.md'))
        if not paths:
            raise PolicyError('historical search selection unavailable')
        requested = [{'kind': 'git_blob', 'revision': base, 'path': path} for path in paths]
        selection = r1.select(inventory, requested)
    except (KeyError, TypeError, AttributeError) as exc:
        raise PolicyError('historical search selection unavailable') from exc
    plan = {'check': check, 'memory_root': memory_root, 'base': base,
            'head': inventory['head'], 'context_id': inventory['context_id'],
            'selection': selection, 'coverage': 'base_markdown_under_caller_root_only',
            'configured_root': 'external_not_verified', 'gate_coverage': 'not_verified',
            'historical_policy': 'external_not_verified', 'target_bodies': 'not_read'}
    plan['plan_sha256'] = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=True,
                                      separators=(',', ':')).encode()).hexdigest()
    return plan


def search_base_markdown(root, binding, *, context_id, approved_revision, base, head,
                         branch, normative_paths, inventory_sha256, plan_sha256,
                         check, memory_root, admit):
    """Run the existing literal-path grep after selection and host admission.

    This is only the candidate search, not the legacy check or global audit.
    The host must independently qualify the real root, historical authority,
    bootstrap, callback, output and isolation, including concurrent writers.
    """
    if not callable(admit):
        raise PolicyError('historical search admission unavailable')
    first = r1.inventory(root, binding, context_id=context_id, approved_revision=approved_revision,
                         base=base, head=head, branch=branch, normative_paths=normative_paths)
    if first['inventory_sha256'] != inventory_sha256:
        raise PolicyError('historical search inventory changed')
    plan = plan_base_markdown(first, check=check, memory_root=memory_root)
    if plan['plan_sha256'] != plan_sha256:
        raise PolicyError('historical search selection changed')

    def admitted():
        try:
            return admit(json.loads(json.dumps(plan, sort_keys=True))) is True
        except Exception as exc:
            raise PolicyError('historical search admission unavailable') from exc

    if not admitted():
        raise PolicyError('historical search admission unavailable')
    root = Path(root).resolve(strict=True)
    from scripts import wiki_audit as audit
    if Path(audit.ROOT).resolve(strict=True) != root:
        raise PolicyError('historical search repository unavailable')
    paths = [item['path'] for item in plan['selection']['inputs']]
    def current():
        return (revision(root, binding.trusted_ref) == base
                and revision(root, 'refs/heads/' + branch) == head
                and revision(root, 'HEAD') == head)

    if not admitted() or not current():
        raise PolicyError('historical search admission changed')
    report = {'state': 'partial', 'check': check, 'search': 'not_completed',
              'possible_body_reads': True, 'selected_count': len(paths),
              'plan_sha256': plan_sha256, 'gate_coverage': 'not_verified',
              'global_audit': 'not_performed', 'worktree_check': 'not_performed',
              'index_bodies': 'not_inspected', 'historical_policy': 'external_not_verified',
              'host_admission': 'not_verified', 'live_observation': 'not_verified',
              'configured_root': 'external_not_verified',
              'coverage': {'base_markdown': 'search_not_completed',
                           'base_other_bodies': 'not_intentionally_read',
                           'intermediate_bodies': 'not_intentionally_read',
                           'commit_messages': 'bootstrap_read_not_scanned',
                           'index_bodies': 'not_intentionally_read',
                           'worktree_bodies': 'not_intentionally_read',
                           'ignored_bodies': 'not_intentionally_read'}}
    try:
        matches = audit._grep_selected_history(base, _PATTERNS[check], paths)
        if not admitted() or not current():
            return report
        after = r1.inventory(root, binding, context_id=context_id, approved_revision=approved_revision,
                             base=base, head=head, branch=branch, normative_paths=normative_paths)
        if after['inventory_sha256'] != inventory_sha256:
            return report
    except Exception:
        return report
    report['search'] = 'completed'
    report['coverage']['base_markdown'] = 'searched_under_caller_root'
    report['matching_paths'] = sorted(matches)
    return report
