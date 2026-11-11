#!/usr/bin/env python3
"""Compile the integral input stage from root entity, sources and configs."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import yaml

try:
    from scripts._common import ROOT  # package/spec-loader import
except ModuleNotFoundError:
    from _common import ROOT  # direct run

from wiki_core.config import config_from_mapping, load_config
from wiki_core.input_stage import (
    compile_input_stage,
    existing_generated_at,
    matching_input_stage_catalog,
    matching_input_stage_cache,
    render_input_stage_markdown,
    write_input_stage,
)
from wiki_core.paths import WikiPaths


def _check_input_stage(root, config, reads=None):
    """Run the same freshness comparison on the supplied reader."""
    paths = WikiPaths(root, config)
    generated_at = existing_generated_at(paths, reads)
    catalog = compile_input_stage(root, config, generated_at=generated_at, reads=reads)
    render_input_stage_markdown(catalog, config)
    errors = []
    page_exists = paths.input_stage_page.exists() if reads is None else reads.exists(paths.input_stage_page)
    if not page_exists:
        errors.append(f'missing input-stage page: {paths.input_stage_page.relative_to(root).as_posix()}')
    else:
        page = paths.input_stage_page.read_bytes() if reads is None else reads.read_bytes(paths.input_stage_page)
        if matching_input_stage_catalog(catalog, config, page) is None:
            errors.append(f'stale input-stage page: {paths.input_stage_page.relative_to(root).as_posix()}')
    cache_exists = paths.input_stage_catalog.exists() if reads is None else reads.exists(paths.input_stage_catalog)
    if cache_exists:
        cache = paths.input_stage_catalog.read_bytes() if reads is None else reads.read_bytes(paths.input_stage_catalog)
        if matching_input_stage_cache(catalog, cache) is None:
            errors.append(f'stale input-stage catalog: {paths.input_stage_catalog.relative_to(root).as_posix()}')
    return {'complete': not errors, 'errors': errors}


def input_stage_selection(root, binding, *, context_id, approved_revision, base, head,
                          branch, normative_paths, extra_paths=()):
    """Plan names and metadata; bootstrap authority remains external.

    A source body can name a further config_ref. An existing reference outside
    this explicit selection makes execution partial; it is never opened.
    """
    from wiki_core.audit_r1_inventory import inventory, select, _worktree_bytes
    from wiki_core.context_policy import PolicyError, git_file, safe_path, within
    from wiki_core.traversal import is_protected_artifact

    root = Path(root).resolve(strict=True)
    snapshot = inventory(root, binding, context_id=context_id, approved_revision=approved_revision,
                         base=base, head=head, branch=branch, normative_paths=normative_paths)
    approved_config = git_file(root, approved_revision, 'wiki.config.yaml')
    config_meta = snapshot['physical']['files'].get('wiki.config.yaml')
    if config_meta is None or config_meta['size'] > 2_000_000:
        raise PolicyError('input-stage working configuration unavailable')
    if _worktree_bytes(root, {'path': 'wiki.config.yaml', **config_meta}) != approved_config:
        raise PolicyError('input-stage working configuration differs from approved')
    try:
        config = config_from_mapping(yaml.safe_load(approved_config.decode('utf-8')))
    except (UnicodeError, yaml.YAMLError, ValueError, TypeError, KeyError):
        raise PolicyError('input-stage approved configuration unavailable') from None
    paths = WikiPaths(root, config)
    def relative(path):
        try:
            return safe_path(Path(path).relative_to(root).as_posix())
        except (TypeError, ValueError) as exc:
            raise PolicyError('input-stage path unavailable') from exc

    if not isinstance(extra_paths, (list, tuple)) or any(not isinstance(x, str) for x in extra_paths):
        raise PolicyError('input-stage selection unavailable')
    extras = [safe_path(path) for path in extra_paths]
    if len(set(extras)) != len(extras):
        raise PolicyError('input-stage selection unavailable')
    memory = relative(paths.memory_root)
    page = relative(paths.input_stage_page)
    cache = relative(paths.input_stage_catalog)
    configured = str((config.root_entity or {}).get('page') or '').strip()
    root_page = relative(root / configured) if configured else None
    files = snapshot['physical']['files']
    if (page not in files or (root_page is not None and root_page not in files)
            or any(path not in files for path in extras)):
        raise PolicyError('input-stage required input unavailable')
    def candidate(name):
        return ((within(name, memory) and name.endswith('.md') and
                 not is_protected_artifact(Path(name))) or name in {page, cache, root_page} or name in extras)
    missing = set(snapshot['missing_tracked']) | (set(snapshot['trees'][head]) - files.keys())
    if any(candidate(name) for name in missing):
        raise PolicyError('input-stage tracked input unavailable')
    names = {name for name in files if candidate(name)}
    selection = select(snapshot, [{'kind': 'worktree', 'path': path} for path in sorted(names)])
    return snapshot, selection, config, approved_config


def guarded_input_stage(root, binding, *, context_id, approved_revision, base, head, branch,
                        normative_paths, inventory_sha256, selection_sha256, admit,
                        extra_paths=()):
    """Compute only; host must independently admit bootstrap, selection and effects."""
    from wiki_core.audit_r1_inventory import SelectedReads, _worktree_bytes
    from wiki_core.context_policy import PolicyError
    if not callable(admit):
        raise PolicyError('input-stage admission unavailable')
    params = dict(context_id=context_id, approved_revision=approved_revision, base=base,
                  head=head, branch=branch, normative_paths=normative_paths, extra_paths=extra_paths)
    snapshot, selection, config, approved_config = input_stage_selection(root, binding, **params)
    if snapshot['inventory_sha256'] != inventory_sha256 or selection['selection_sha256'] != selection_sha256:
        raise PolicyError('input-stage selection changed')
    if admit(copy.deepcopy(selection)) is not True:
        raise PolicyError('input-stage admission unavailable')
    root = Path(root).resolve(strict=True)
    if sum(item['size'] for item in selection['inputs']) > 8_000_000 or any(item['size'] > 2_000_000 for item in selection['inputs']):
        raise PolicyError('input-stage selection budget exceeded')
    contents = {}
    attempted = 0
    status = {'scope': 'input_stage_only', 'selection_sha256': selection_sha256,
              'global_audit': 'not_performed', 'host_admission': 'external_not_verified',
              'bootstrap': 'external_not_verified', 'live_observation': 'not_verified',
              'cleanup': 'external_not_verified', 'gate_state': 'blocked_external_qualification',
              'coverage': {'worktree': 'selected_bodies_only', 'index': 'metadata_only',
                           'history': 'bootstrap_commit_objects_may_include_messages_not_audited',
                           'ignored': 'selected_bodies_only', 'composition': 'not_qualified'},
              'bootstrap_may_overlap_selection': True}
    try:
        again, selected, _, current_config = input_stage_selection(root, binding, **params)
        if (again['inventory_sha256'] != inventory_sha256 or
                selected['selection_sha256'] != selection_sha256 or current_config != approved_config):
            raise PolicyError('input-stage selection changed')
        for item in selection['inputs']:
            if admit(copy.deepcopy(selection)) is not True:
                raise PolicyError('input-stage admission changed')
            attempted += 1
            contents[item['path']] = _worktree_bytes(root, item)
        if admit(copy.deepcopy(selection)) is not True:
            raise PolicyError('input-stage admission changed')
        again, selected, _, current_config = input_stage_selection(root, binding, **params)
        if (again['inventory_sha256'] != inventory_sha256 or
                selected['selection_sha256'] != selection_sha256 or current_config != approved_config):
            raise PolicyError('input-stage selection changed')
        missing = set(snapshot['missing_tracked']) | (set(snapshot['trees'][head]) - snapshot['physical']['files'].keys())
        reads = SelectedReads(root, snapshot['physical'], contents, missing=missing)
        result = _check_input_stage(root, config, reads)
    except Exception:
        return {**status, 'state': 'partial',
                'coverage': {**status['coverage'], 'worktree': 'partial_or_unknown_selected_bodies',
                             'ignored': 'partial_or_unknown_selected_bodies'},
                'source_bodies_validated': len(contents),
                'source_body_attempts_may_have_read_bytes': attempted}
    return {**status, 'state': 'completed' if result['complete'] else 'failed', 'result': result,
            'source_bodies_validated': len(contents), 'source_body_attempts_may_have_read_bytes': attempted,
            'ignored_selected': len(set(contents) & set(snapshot['ignored'])),
            'readset': [{'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                        for path, data in sorted(contents.items())]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the input-stage page and catalog")
    parser.add_argument("--if-changed", action="store_true",
                        help="with --write, preserve an exactly reproducible artifact and its date")
    parser.add_argument("--check", action="store_true", help="fail if generated files differ")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument('--context-guard', help='explicit owner context; host admission remains external')
    parser.add_argument('--context-policy-revision', help='approved full Git revision')
    parser.add_argument('--context-base', help='approved base full Git revision')
    parser.add_argument('--context-head', help='candidate head full Git revision')
    parser.add_argument('--context-branch', help='candidate wiki branch')
    parser.add_argument('--context-normative', action='append', default=[])
    parser.add_argument('--context-extra-path', action='append', default=[])
    parser.add_argument('--context-inventory-sha256')
    parser.add_argument('--context-selection-sha256')
    parser.add_argument('--context-plan', action='store_true')
    parser.add_argument(
        "--ready",
        action="store_true",
        help="print staged or ready_for_ingest input rows as JSON",
    )
    args = parser.parse_args()
    if args.if_changed and not args.write:
        parser.error("--if-changed requires --write")

    options = (args.context_guard, args.context_policy_revision, args.context_base, args.context_head,
               args.context_branch, args.context_normative, args.context_extra_path,
               args.context_inventory_sha256, args.context_selection_sha256, args.context_plan)
    if any(options):
        if (not args.check or args.write or args.ready or not all((args.context_guard,
                args.context_policy_revision, args.context_base, args.context_head,
                args.context_branch, args.context_normative))):
            parser.error('context guard requires --check, revisions, branch and normative paths')
        if args.context_plan and (args.context_inventory_sha256 or args.context_selection_sha256):
            parser.error('context plan does not accept admitted digests')
        if not args.context_plan and not all((args.context_inventory_sha256, args.context_selection_sha256)):
            parser.error('context execution requires externally admitted inventory and selection digests')
        from wiki_core.coordination_context import CoordinationBinding
        try:
            binding = CoordinationBinding.from_environment()
            params = dict(context_id=args.context_guard, approved_revision=args.context_policy_revision,
                          base=args.context_base, head=args.context_head, branch=args.context_branch,
                          normative_paths=args.context_normative, extra_paths=args.context_extra_path)
            if args.context_plan:
                snapshot, selection, _, _ = input_stage_selection(ROOT, binding, **params)
                output = {'state': 'selection_only', 'scope': 'input_stage_only',
                          'inventory_sha256': snapshot['inventory_sha256'], 'selection': selection,
                          'bootstrap': 'external_not_verified', 'host_admission': 'external_not_verified',
                          'live_observation': 'not_verified', 'cleanup': 'external_not_verified',
                          'coverage': {'worktree': 'metadata_only', 'index': 'metadata_only',
                                       'history': 'bootstrap_commit_objects_may_include_messages_not_audited',
                                       'ignored': 'metadata_only', 'composition': 'not_qualified'},
                          'gate_state': 'blocked_external_qualification', 'global_audit': 'not_performed'}
                print(json.dumps(output, ensure_ascii=False, indent=2))
                # This plan shares --check's entry point. Do not let an exit
                # code alone present a selection as a passed gate.
                return 1
            # The host must have admitted this exact selection before invoking.
            # Matching digests bind the selection; they do not authenticate it.
            output = guarded_input_stage(ROOT, binding, **params,
                inventory_sha256=args.context_inventory_sha256, selection_sha256=args.context_selection_sha256,
                admit=lambda selection: selection['selection_sha256'] == args.context_selection_sha256)
        except (ValueError, OSError, RuntimeError, TypeError, KeyError):
            output = {'state': 'refused', 'scope': 'input_stage_only',
                      'global_audit': 'not_performed', 'bootstrap': 'external_not_verified',
                      'host_admission': 'external_not_verified', 'live_observation': 'not_verified',
                      'cleanup': 'external_not_verified', 'gate_state': 'blocked_external_qualification'}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        # This process cannot independently verify its host or post-exit cleanup.
        return 1

    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)

    if args.write:
        page_before = paths.input_stage_page.read_bytes() if paths.input_stage_page.exists() else None
        cache_before = paths.input_stage_catalog.read_bytes() if paths.input_stage_catalog.exists() else None
        catalog = write_input_stage(ROOT, config, if_changed=args.if_changed)
        print(paths.input_stage_page.relative_to(ROOT).as_posix())
        print(paths.input_stage_catalog.relative_to(ROOT).as_posix())
        md_changed = page_before != paths.input_stage_page.read_bytes()
        cache_changed = cache_before != paths.input_stage_catalog.read_bytes()
        markdown_catalog = matching_input_stage_catalog(catalog, config, paths.input_stage_page.read_bytes())
        print(json.dumps(dict(md_changed=md_changed, catalog_changed=cache_changed,
                              md_publication_date=markdown_catalog["generated_at"],
                              catalog_generation_date=catalog["generated_at"],
                              executed_at=dt.datetime.now().astimezone().isoformat()), sort_keys=True))
        return 0

    if args.check:
        result = _check_input_stage(ROOT, config)
        if result['errors']:
            for error in result['errors']:
                print(f'ERROR: {error}', file=sys.stderr)
            return 1
        print('input stage deterministic content equal to a recompile at HEAD.')
        return 0

    generated_at = existing_generated_at(paths)
    if args.format == "json" and not args.check and not args.ready and not paths.input_stage_page.exists():
        # Without published Markdown, an unverified cache cannot date the
        # fallback. The complete-model check below may retain a valid cache.
        generated_at = None
    catalog = compile_input_stage(ROOT, config, generated_at=generated_at)
    markdown = render_input_stage_markdown(catalog, config)

    if args.ready:
        print(json.dumps(catalog.get("ready_inputs", []), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.format == "json":
        # JSON has its own generation date. Reuse it only when the complete
        # stored model reproduces current inputs; Markdown dates only Markdown.
        if paths.input_stage_catalog.exists():
            retained = matching_input_stage_cache(catalog, paths.input_stage_catalog.read_bytes())
            if retained is not None:
                catalog = retained
        print(json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
