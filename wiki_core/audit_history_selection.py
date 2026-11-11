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
    # Git/runtime metadata for this precheck is itself host-admitted bootstrap.
    # Refuse an already-wrong symbolic branch before the inventory reads the
    # approved policy or qualifies context instruction/index bodies.
    if (not isinstance(binding, r1.CoordinationBinding)
            or not all(isinstance(value, str) and r1.SHA.fullmatch(value)
                       for value in (approved_revision, base, head))
            or approved_revision != base or not isinstance(branch, str)
            or not r1.BRANCH.fullmatch(branch) or '..' in branch or branch.endswith('.')):
        raise PolicyError('historical search branch unavailable')
    try:
        initial_ref = r1._git(Path(root), 'symbolic-ref', '--quiet', 'HEAD').decode('ascii').strip()
        if (initial_ref != 'refs/heads/' + branch or revision(root, binding.trusted_ref) != base
                or revision(root, initial_ref) != head or revision(root, 'HEAD') != head):
            raise PolicyError('historical search branch unavailable')
    except (OSError, ValueError, UnicodeError) as exc:
        raise PolicyError('historical search branch unavailable') from exc
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
        try:
            selected_ref = 'refs/heads/' + branch
            return (revision(root, binding.trusted_ref) == base
                    and revision(root, selected_ref) == head
                    and r1._git(root, 'symbolic-ref', '--quiet', 'HEAD').decode('ascii').strip() == selected_ref
                    and revision(root, 'HEAD') == head)
        except (OSError, ValueError, UnicodeError):
            return False

    if not admitted() or not current():
        raise PolicyError('historical search admission changed')
    report = {'state': 'partial', 'check': check, 'search': 'not_completed',
              'possible_body_reads': True, 'selected_count': len(paths),
              'size_checks_attempted': 0, 'size_checks_completed': 0,
              'grep_batches_attempted': 0, 'grep_batches_completed': 0,
              'plan_sha256': plan_sha256, 'gate_coverage': 'not_verified',
              'global_audit': 'not_performed', 'worktree_check': 'not_performed',
              'index_bodies': 'not_inspected', 'historical_policy': 'external_not_verified',
              'host_admission': 'not_verified', 'live_observation': 'not_verified',
              'configured_root': 'external_not_verified',
              'bootstrap_reads': dict(first['bootstrap_reads']),
              'coverage': {'base_markdown': 'search_not_completed',
                           'base_other_bodies': 'bootstrap_policy_or_context_may_be_read',
                           'intermediate_bodies': 'not_intentionally_read',
                           'commit_messages': 'bootstrap_read_not_scanned',
                           'index_bodies': 'not_intentionally_read',
                           'worktree_bodies': 'bootstrap_ignore_rules_may_be_read',
                           'ignored_bodies': 'bootstrap_ignore_rules_may_be_read'}}
    try:
        limits = plan['selection']['limits']
        total = 0
        for item in plan['selection']['inputs']:
            if not admitted() or not current():
                return report
            report['size_checks_attempted'] += 1
            size = int(r1._git(root, 'cat-file', '-s', item['oid']).decode('ascii').strip())
            report['size_checks_completed'] += 1
            total += size
            if size < 0 or size > limits['max_item_bytes'] or total > limits['max_total_bytes']:
                return report

        # Keep the same literal-path batch boundaries as the legacy helper;
        # track each call so an interrupted search is not reported as complete.
        batches, batch, encoded_size = [], [], 0
        for path in paths:
            size = len(path.encode('utf-8')) + len(':(literal)')
            if size > 6000:
                return report
            if len(batch) >= 32 or encoded_size + size > 6000:
                batches.append(batch)
                batch, encoded_size = [], 0
            batch.append(path)
            encoded_size += size
        if batch:
            batches.append(batch)
        matches = set()
        for batch in batches:
            if not admitted() or not current():
                return report
            report['grep_batches_attempted'] += 1
            matches.update(audit._grep_selected_history(base, _PATTERNS[check], batch))
            report['grep_batches_completed'] += 1
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
