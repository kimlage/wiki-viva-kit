"""Bounded, owner-scoped inventory of canonical authored requirements.

This is not a receipt registry, execution proof, global inventory or ACL.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath

from wiki_core.context_policy import PolicyError, safe_path, within
from wiki_core.context_selection import _metadata
from wiki_core.folder_policy_v2 import FORMAT
from wiki_core.information_relations import information_requirements
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repository_reader import RepositoryReader


class FolderConsumersError(ValueError):
    pass


def inventory_folder_consumers_v2(root, policy, *, folder, scope=None, candidates=None,
                                   max_files=256, max_bytes=1_000_000):
    """Inspect only explicitly selected paths or authorized owner metadata.

    Requirements are canonical declarations, not v2 receipts. Resolution is
    limited to exact tracked paths; page IDs and missing paths are not resolved
    by reading other pages. No cross-owner content or unbounded coverage is
    inferred. All candidate permissions and budgets are checked before reads.
    """
    if getattr(policy, 'format_version', None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise FolderConsumersError('bound v2 policy required')
    policy = policy.fresh()
    if ((scope is None) == (candidates is None) or type(max_files) is not int or not 1 <= max_files <= 256
            or type(max_bytes) is not int or not 1 <= max_bytes <= 1_000_000):
        raise FolderConsumersError('bounded explicit paths or one scope required')
    try:
        context = policy.folder_ids[folder]
        reader = RepositoryReader(root, policy.policy_revision)
        if reader.invalid_paths:
            raise FolderConsumersError('repository metadata unavailable')
        if candidates is not None:
            if not isinstance(candidates, list) or not candidates or len(candidates) > max_files:
                raise FolderConsumersError('bounded explicit paths required')
            paths = [safe_path(path) for path in candidates]
            if len(paths) != len(set(paths)):
                raise FolderConsumersError('duplicate candidate')
            coverage = 'explicit_candidates_only'
        else:
            scope = safe_path(scope, allow_root=True)
            if not within(scope, folder):
                raise FolderConsumersError('scope outside owner')
            paths = []
            for path in reader.paths:
                if not within(path, scope) or not path.endswith('.md'):
                    continue
                parts = PurePosixPath(path).parts
                if (parts[-1] in ('AGENTS.md', 'AGENTS.override.md', 'CLAUDE.md', 'CLAUDE.local.md', 'SKILL.md')
                        or any(p in ('.skills', 'skills', '.codex', '.claude') for p in parts)):
                    continue
                try:
                    if policy.owner_of(path) == context and policy.permits(context, 'read', path):
                        paths.append(path)
                except PolicyError:
                    # Ambiguous and nested folders do not establish coverage.
                    continue
            coverage = 'authorized_regular_markdown_in_scope_only'
        if len(paths) > max_files:
            raise FolderConsumersError('candidate file limit exceeded')
        for path in paths:
            if (path not in reader.paths or not path.endswith('.md') or policy.owner_of(path) != context
                    or not policy.permits(context, 'read', path)):
                raise FolderConsumersError('candidate owner or read authority unavailable')
        if sum(reader.blob_size(path) for path in paths) > max_bytes:
            raise FolderConsumersError('candidate byte limit exceeded')
        def resolve(ref):
            # Do not resolve IDs by cataloguing page bodies or follow links.
            try:
                path = safe_path(ref)
            except PolicyError:
                return []
            return [path] if path in reader.paths else []
        consumers = []
        for path in paths:
            item = reader.read(path)
            if contains_access_secrets(item['text']):
                raise FolderConsumersError('secret detected in consumer')
            values = _metadata(item)
            if 'information_requirements' not in values:
                continue
            requirements = information_requirements(values, resolve, resolve_normative=resolve)
            if requirements:
                consumers.append({'path': path, 'requirements': requirements})
        out = {'schema_version': 'wiki.folder-consumer-inventory/v2', 'policy_revision': policy.policy_revision,
               'context_id': context, 'selection': coverage, 'inspected_count': len(paths),
               'consumers': consumers, 'coverage': 'selected_authorized_paths_only',
               'declarations': 'not_v2_receipts_or_read_proof', 'enforcement_claim': 'none'}
        if contains_access_secrets(out):
            raise FolderConsumersError('secret detected in inventory')
        policy.fresh()
        return out
    except (KeyError, TypeError, AttributeError) as exc:
        raise FolderConsumersError('consumer inventory unavailable') from exc
    except ValueError as exc:
        if isinstance(exc, FolderConsumersError):
            raise
        raise FolderConsumersError('consumer inventory unavailable') from exc
