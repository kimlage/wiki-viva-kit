"""Internal R1 selections for existing worktree audit subchecks.

The caller must admit bootstrap, actor, output audience and isolation before
calling. This is not the complete audit, a grant or an authenticated host.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from wiki_core.audit_r1_inventory import _worktree_bytes, inventory, select
from wiki_core.context_policy import PolicyError


def plan_command_reference(snapshot: dict, config) -> dict:
    """Select the configured reference plus names required by this check."""
    from wiki_core.context_policy import safe_path
    try:
        physical = snapshot['physical']['files']
        indexed = {entry['path'] for entry in snapshot['index']}
        names = indexed | set(snapshot['untracked'])
        head_tree = snapshot['trees'][snapshot['head']]
        if (any(row['stage'] != 0 for row in snapshot['index'])
                or any(path not in physical or path not in names for path in indexed | set(head_tree))):
            raise PolicyError('command reference selection unavailable')
        reference = safe_path(config.paths['command_reference_page'])
        bodies = {reference, 'wiki.config.yaml'}
        if not bodies <= set(physical):
            raise PolicyError('command reference selection unavailable')
        selection = select(snapshot, [{'kind': 'worktree', 'path': name} for name in sorted(bodies)])
        aliases = set(snapshot['denied_oid_aliases'])
        if (any(path in bodies and row['oid'] in aliases for path, row in head_tree.items())
                or any(row['path'] in bodies and (row['oid'] in aliases or row['stage'] != 0)
                       for row in snapshot['index'])):
            raise PolicyError('command reference selection unavailable')
        limits = selection['limits']
        sizes = [row['size'] for row in selection['inputs']]
        if (any(size < 0 or size > limits['max_item_bytes'] for size in sizes)
                or sum(sizes) > limits['max_total_bytes']):
            raise PolicyError('command reference selection unavailable')
        plan = {'selection': selection, 'metadata_names': sorted(names), 'reference': reference,
                'scope': 'sanitized_git_worktree_command_reference',
                'ignored_reference_selected': reference in snapshot['ignored'],
                'history_and_index_bodies': 'not_scanned', 'worktree_content_aliases': 'external_not_verified',
                'bootstrap_and_output_audience': 'external_not_verified',
                'host_admission': 'external_not_verified', 'global_audit': 'not_performed'}
        plan['plan_sha256'] = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=True,
            separators=(',', ':')).encode()).hexdigest()
        return plan
    except (KeyError, TypeError, AttributeError) as exc:
        raise PolicyError('command reference selection unavailable') from exc


def run_worktree_command_reference(root, binding, *, context_id, approved_revision, base, head,
                                   branch, normative_paths, inventory_sha256, plan_sha256, admit):
    """Run only the registered command-reference check after host admission."""
    import yaml
    from scripts import wiki_audit as audit
    from wiki_core.audit_r1_inventory import SelectedReads
    from wiki_core.config import config_from_mapping
    from wiki_core.context_policy import git_file
    if not callable(admit): raise PolicyError('command reference host admission unavailable')
    args = dict(context_id=context_id, approved_revision=approved_revision, base=base,
                head=head, branch=branch, normative_paths=normative_paths)
    first = inventory(root, binding, **args)
    # The host independently admits this approved-config bootstrap read.
    approved = git_file(Path(root), approved_revision, 'wiki.config.yaml')
    config = config_from_mapping(yaml.safe_load(approved.decode('utf-8')))
    plan = plan_command_reference(first, config)
    if first['inventory_sha256'] != inventory_sha256 or plan['plan_sha256'] != plan_sha256:
        raise PolicyError('command reference selection changed')
    def admitted(): return admit(copy.deepcopy(plan)) is True
    if not admitted(): raise PolicyError('command reference host admission unavailable')
    status = {'scope': 'sanitized_git_worktree_command_reference', 'global_audit': 'not_performed',
              'gate_state': 'blocked_incomplete_coverage', 'bootstrap': 'external_not_verified',
              'host_admission': 'external_not_verified', 'live_observation': 'not_verified',
              'cleanup': 'external_not_verified', 'plan_sha256': plan_sha256,
              'coverage': {'worktree': 'reference_and_configuration_only', 'index': 'metadata_only',
                           'history': 'not_scanned', 'ignored_reference_selected': plan['ignored_reference_selected'],
                           'worktree_content_aliases': 'external_not_verified'}}
    attempted = validated = 0
    contents = {}
    check_started = False
    try:
        if inventory(root, binding, **args)['inventory_sha256'] != inventory_sha256:
            raise PolicyError('command reference selection changed')
        for item in plan['selection']['inputs']:
            if not admitted(): raise PolicyError('command reference admission changed')
            attempted += 1
            raw = _worktree_bytes(Path(root), item)
            audit._selected_audit_text(raw)
            contents[item['path']] = raw
            validated += 1
        if not admitted() or inventory(root, binding, **args)['inventory_sha256'] != inventory_sha256:
            raise PolicyError('command reference selection changed')
        if contents.get('wiki.config.yaml') != approved:
            raise PolicyError('command reference working configuration unavailable')
        context = audit.AuditContext(config)
        context.command_reads = SelectedReads(Path(root), first['physical'], contents,
                                             missing=first['missing_tracked'])
        context.command_names = plan['metadata_names']
        check_started = True
        dict(audit.CHECKS)['command_reference'](context)
        if not admitted(): raise PolicyError('command reference admission changed')
    except Exception:
        return {**status, 'state': 'partial',
                'coverage': {**status['coverage'], 'worktree': 'partial_or_unknown'},
                'check_progress': 'partial_or_unknown' if check_started else 'not_started',
                'source_bodies_validated': validated,
                'source_body_attempts_may_have_read_bytes': attempted}
    return {**status, 'state': 'failed' if context.errors else 'completed',
            'diagnostics': context.errors, 'source_bodies_validated': validated,
            'source_body_attempts_may_have_read_bytes': attempted}


def plan_old_paths(snapshot: dict) -> dict:
    """Select every metadata name and Markdown body needed by old_paths."""
    try:
        physical = snapshot['physical']['files']
        indexed = {entry['path'] for entry in snapshot['index']}
        names = indexed | set(snapshot['untracked'])
        head_tree = snapshot['trees'][snapshot['head']]
        # Even a staged deletion must not silently remove an input from a
        # supposedly complete check. The check examines all candidate names.
        if (any(row['stage'] != 0 for row in snapshot['index'])
                or any(path not in physical or path not in names for path in indexed | set(head_tree))):
            raise PolicyError('old paths selection unavailable')
        if any(path not in physical for path in names) or 'wiki.config.yaml' not in names:
            raise PolicyError('old paths selection unavailable')
        bodies = {path for path in names if path.endswith('.md')} | {'wiki.config.yaml'}
        selection = select(snapshot, [{'kind': 'worktree', 'path': name} for name in sorted(bodies)])
        aliases = set(snapshot['denied_oid_aliases'])
        if (any(path in bodies and row['oid'] in aliases for path, row in head_tree.items())
                or any(row['path'] in bodies and (row['oid'] in aliases or row['stage'] != 0)
                       for row in snapshot['index'])):
            raise PolicyError('old paths selection unavailable')
        sizes = [row['size'] for row in selection['inputs']]
        limits = selection['limits']
        if (any(size < 0 or size > limits['max_item_bytes'] for size in sizes)
                or sum(sizes) > limits['max_total_bytes']):
            raise PolicyError('old paths selection unavailable')
        plan = {'selection': selection, 'metadata_names': sorted(names),
                'scope': 'sanitized_git_worktree_old_paths', 'ignored': 'not_selected_by_legacy_check',
                'history_and_index_bodies': 'not_scanned', 'worktree_content_aliases': 'external_not_verified',
                'bootstrap_and_output_audience': 'external_not_verified',
                'host_admission': 'external_not_verified', 'global_audit': 'not_performed'}
        plan['plan_sha256'] = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=True,
            separators=(',', ':')).encode()).hexdigest()
        return plan
    except (KeyError, TypeError, AttributeError) as exc:
        raise PolicyError('old paths selection unavailable') from exc


def run_worktree_old_paths(root, binding, *, context_id, approved_revision, base, head,
                           branch, normative_paths, inventory_sha256, plan_sha256, admit):
    """Execute only the existing old_paths check after host plan admission."""
    import yaml
    from scripts import wiki_audit as audit
    from wiki_core.audit_r1_inventory import SelectedReads
    from wiki_core.config import config_from_mapping
    from wiki_core.context_policy import git_file

    if not callable(admit):
        raise PolicyError('old paths host admission unavailable')
    args = dict(context_id=context_id, approved_revision=approved_revision, base=base,
                head=head, branch=branch, normative_paths=normative_paths)
    first = inventory(root, binding, **args)
    plan = plan_old_paths(first)
    if first['inventory_sha256'] != inventory_sha256 or plan['plan_sha256'] != plan_sha256:
        raise PolicyError('old paths selection changed')
    def admitted():
        return admit(copy.deepcopy(plan)) is True
    if not admitted():
        raise PolicyError('old paths host admission unavailable')
    status = {'scope': 'sanitized_git_worktree_old_paths', 'global_audit': 'not_performed',
              'gate_state': 'blocked_incomplete_coverage', 'bootstrap': 'external_not_verified',
              'host_admission': 'external_not_verified', 'live_observation': 'not_verified',
              'cleanup': 'external_not_verified', 'plan_sha256': plan_sha256,
              'coverage': {'worktree': 'selected_markdown_and_names', 'index': 'metadata_only',
                           'history': 'not_scanned', 'ignored': 'not_selected_by_legacy_check',
                           'worktree_content_aliases': 'external_not_verified'}}
    attempted = validated = 0
    contents = {}
    check_started = False
    try:
        if inventory(root, binding, **args)['inventory_sha256'] != inventory_sha256:
            raise PolicyError('old paths selection changed')
        for item in plan['selection']['inputs']:
            if not admitted(): raise PolicyError('old paths admission changed')
            attempted += 1
            raw = _worktree_bytes(Path(root), item)
            # Count a body only after the same text validation used by the
            # selected check. A failed read/validation may still touch bytes.
            audit._selected_audit_text(raw)
            contents[item['path']] = raw
            validated += 1
        if not admitted() or inventory(root, binding, **args)['inventory_sha256'] != inventory_sha256:
            raise PolicyError('old paths selection changed')
        approved = git_file(Path(root), approved_revision, 'wiki.config.yaml')
        if contents.get('wiki.config.yaml') != approved:
            raise PolicyError('old paths working configuration unavailable')
        context = audit.AuditContext(config_from_mapping(yaml.safe_load(approved.decode('utf-8'))))
        context.old_paths_reads = SelectedReads(Path(root), first['physical'], contents,
                                               missing=first['missing_tracked'])
        context.old_paths_names = plan['metadata_names']
        check_started = True
        dict(audit.CHECKS)['old_paths'](context)
        if not admitted(): raise PolicyError('old paths admission changed')
    except Exception:
        return {**status, 'state': 'partial',
                'coverage': {**status['coverage'], 'worktree': 'partial_or_unknown'},
                'check_progress': 'partial_or_unknown' if check_started else 'not_started',
                'source_bodies_validated': validated,
                'source_body_attempts_may_have_read_bytes': attempted}
    return {**status, 'state': 'failed' if context.errors else 'completed',
            'diagnostics': context.errors, 'source_bodies_validated': validated,
            'source_body_attempts_may_have_read_bytes': attempted}


def plan_worktree_secrets(snapshot: dict) -> dict:
    """Select the sanitized Git worktree candidate universe before body reads.

    These constants come from the existing audit, not from the caller. Git
    HEAD/index names are used only as metadata and a missing eligible source
    fails closed, including a staged deletion. Git and config bootstrap must
    already be admitted by the host. Ambient Git configuration may make the
    legacy check's inventory different; equivalence must be qualified outside.
    """
    from scripts.wiki_audit import SECRET_SCAN_SKIP_PREFIXES, TEXT_SCAN_SUFFIXES

    try:
        physical = snapshot['physical']['files']
        ignored = set(snapshot['ignored'])
        indexed = {entry['path'] for entry in snapshot['index']}
        candidates = indexed | set(snapshot['untracked'])
        head_tree = snapshot['trees'][snapshot['head']]

        def eligible(path):
            return (not path.startswith(SECRET_SCAN_SKIP_PREFIXES)
                    and Path(path).suffix.lower() in TEXT_SCAN_SUFFIXES)

        # A missing HEAD/index input is not a successful complete scan, even
        # if the legacy check would omit it after a staged deletion.
        if (any(eligible(path) and path not in physical for path in indexed | set(head_tree))
                or any(eligible(path) and path not in candidates for path in head_tree)):
            raise PolicyError('secrets selection unavailable')
        names = sorted(path for path in candidates if eligible(path))
        if any(path in ignored or path not in physical for path in names):
            raise PolicyError('secrets selection unavailable')
        selection = select(snapshot, [{'kind': 'worktree', 'path': name} for name in names],
                           _allow_empty=True)
        selected = set(names)
        aliases = set(snapshot['denied_oid_aliases'])
        if (any(path in selected and entry['oid'] in aliases for path, entry in head_tree.items())
                or any(entry['path'] in selected and
                       (entry['oid'] in aliases or entry['stage'] != 0)
                       for entry in snapshot['index'])):
            raise PolicyError('secrets selection unavailable')
        sizes = [item['size'] for item in selection['inputs']]
        limits = selection['limits']
        if (any(size < 0 or size > limits['max_item_bytes'] for size in sizes)
                or sum(sizes) > limits['max_total_bytes']):
            raise PolicyError('secrets selection unavailable')
        plan = {'selection': selection, 'scope': 'sanitized_git_worktree_secrets_candidates',
                'ignored': 'not_selected_by_legacy_check',
                'history_and_index_bodies': 'not_scanned',
                'worktree_content_aliases': 'external_not_verified',
                'bootstrap_and_output_audience': 'external_not_verified',
                'host_admission': 'external_not_verified', 'global_audit': 'not_performed'}
        plan['plan_sha256'] = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=True,
            separators=(',', ':')).encode()).hexdigest()
        return plan
    except (KeyError, TypeError, AttributeError) as exc:
        raise PolicyError('secrets selection unavailable') from exc


def scan_worktree_secrets(root, binding, *, context_id, approved_revision, base, head,
                          branch, normative_paths, inventory_sha256, plan_sha256, admit):
    """Scan only after a host independently admits the exact full plan.

    A binary candidate returns partial, rather than claiming it was scanned.
    An error after a read reports attempts as potentially having read bytes.
    """
    import yaml
    from scripts import wiki_audit as audit
    from wiki_core.audit_r1_inventory import SelectedReads
    from wiki_core.config import config_from_mapping
    from wiki_core.context_policy import git_file

    if not callable(admit):
        raise PolicyError('secrets host admission unavailable')
    args = dict(context_id=context_id, approved_revision=approved_revision, base=base,
                head=head, branch=branch, normative_paths=normative_paths)
    first = inventory(root, binding, **args)
    plan = plan_worktree_secrets(first)
    if first['inventory_sha256'] != inventory_sha256 or plan['plan_sha256'] != plan_sha256:
        raise PolicyError('secrets selection changed')

    def admitted():
        return admit(copy.deepcopy(plan)) is True

    if not admitted():
        raise PolicyError('secrets host admission unavailable')
    status = {'scope': 'sanitized_git_worktree_secrets_candidates', 'global_audit': 'not_performed',
              'gate_state': 'blocked_incomplete_coverage', 'bootstrap': 'external_not_verified',
              'host_admission': 'external_not_verified', 'live_observation': 'not_verified',
              'cleanup': 'external_not_verified', 'plan_sha256': plan_sha256,
              'coverage': {'worktree': 'selected_candidates_only',
                           'ignored': 'not_selected_by_legacy_check',
                           'index': 'metadata_only', 'history': 'not_scanned',
                           'worktree_content_aliases': 'external_not_verified'}}
    attempted = validated = 0
    contents = {}
    scan_started = False
    try:
        current = inventory(root, binding, **args)
        if current['inventory_sha256'] != inventory_sha256:
            raise PolicyError('secrets selection changed')
        for item in plan['selection']['inputs']:
            if not admitted():
                raise PolicyError('secrets admission changed')
            attempted += 1
            raw = _worktree_bytes(Path(root), item)
            # Validate before recording the body as usable, including when a
            # caller invokes the registered selected check independently.
            audit._selected_audit_text(raw)
            contents[item['path']] = raw
            validated += 1
        if not admitted():
            raise PolicyError('secrets admission changed')
        current = inventory(root, binding, **args)
        if current['inventory_sha256'] != inventory_sha256:
            raise PolicyError('secrets selection changed')
        # The approved config read is host-admitted bootstrap. The selected
        # working config must match; candidate policy cannot authorize itself.
        approved_config = git_file(Path(root), approved_revision, 'wiki.config.yaml')
        if contents.get('wiki.config.yaml') != approved_config:
            raise PolicyError('secrets working configuration unavailable')
        config = config_from_mapping(yaml.safe_load(approved_config.decode('utf-8')))
        context = audit.AuditContext(config)
        context.secret_reads = SelectedReads(Path(root), first['physical'], contents,
                                             missing=first['missing_tracked'])
        context.secret_paths = [item['path'] for item in plan['selection']['inputs']]
        scan_started = True
        dict(audit.CHECKS)['secrets'](context)
        if not admitted():
            raise PolicyError('secrets admission changed')
    except Exception:
        return {**status, 'state': 'partial',
                'coverage': {**status['coverage'], 'worktree': 'partial_or_unknown'},
                'scan_progress': 'partial_or_unknown' if scan_started else 'not_started',
                'source_bodies_validated': validated,
                'source_body_attempts_may_have_read_bytes': attempted}
    return {**status, 'state': 'failed' if context.errors else 'completed',
            'diagnostics': context.errors,
            'source_bodies_validated': validated,
            'source_body_attempts_may_have_read_bytes': attempted}
