"""Validate a portable workspace declaration without inspecting a workspace.

No filesystem or Git access is performed. A valid declaration grants no access
and does not authenticate a remote. Live inspection requires a separately
qualified boundary against concurrent renames and remains unavailable.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from wiki_core.repo_read import RepoReadError, remote_identity


class WorkspaceManifestError(ValueError):
    pass


def _path(value: Any) -> str:
    if not isinstance(value, str) or not value or not re.fullmatch(r'[A-Za-z0-9._/-]+', value):
        raise WorkspaceManifestError('invalid portable path')
    parts = value.split('/')
    if any(part in ('', '.', '..') for part in parts) or PurePosixPath(value).is_absolute():
        raise WorkspaceManifestError('invalid portable path')
    return value


def validate_manifest(data: Any) -> dict[str, Any]:
    """Validate the closed v1 declaration; return no unverified success claims."""
    if not isinstance(data, dict) or set(data) != {'schema', 'directories', 'links', 'repositories'}:
        raise WorkspaceManifestError('invalid manifest fields')
    if data['schema'] != 'wiki-workspace/v1':
        raise WorkspaceManifestError('unsupported manifest schema')
    dirs, links, repos = (data[k] for k in ('directories', 'links', 'repositories'))
    if not all(isinstance(v, list) for v in (dirs, links, repos)):
        raise WorkspaceManifestError('invalid manifest collections')
    directories = [_path(x) for x in dirs]
    occupied = {p: 'directory' for p in directories}
    if len(occupied) != len(directories):
        raise WorkspaceManifestError('duplicate path')
    for item in links:
        if not isinstance(item, dict) or set(item) != {'path', 'target'}:
            raise WorkspaceManifestError('invalid link')
        path = _path(item['path'])
        target = item['target']
        if not isinstance(target, str) or ':' not in target:
            raise WorkspaceManifestError('invalid link target')
        root, relative = target.split(':', 1)
        if root not in ('wiki', 'skills'):
            raise WorkspaceManifestError('invalid link target')
        _path(relative)
        if path in occupied:
            raise WorkspaceManifestError('duplicate path')
        occupied[path] = 'link'
    for item in repos:
        if not isinstance(item, dict) or set(item) != {'path', 'identity', 'remote', 'default_branch'}:
            raise WorkspaceManifestError('invalid repository')
        path = _path(item['path'])
        if path in occupied:
            raise WorkspaceManifestError('duplicate path')
        occupied[path] = 'repository'
        try:
            identity, _ = remote_identity(item['remote'])
        except (RepoReadError, TypeError) as exc:
            raise WorkspaceManifestError('invalid repository remote') from exc
        if item['identity'] != identity:
            raise WorkspaceManifestError('repository identity mismatch')
        branch = item['default_branch']
        if not isinstance(branch, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', branch) or '..' in branch or '//' in branch or branch.endswith(('/', '.', '.lock')) or '/.' in branch:
            raise WorkspaceManifestError('invalid default branch')
    for path, kind in occupied.items():
        for parent in PurePosixPath(path).parents:
            ancestor = str(parent)
            if ancestor in occupied and occupied[ancestor] != 'directory':
                raise WorkspaceManifestError('path nested under link or repository')
    return {'schema': 'wiki-workspace-validation/v1', 'manifest': 'valid',
            'workspace': 'not_checked', 'remote_authentication': 'not_checked',
            'boundary': 'concurrent_rename_not_qualified'}
