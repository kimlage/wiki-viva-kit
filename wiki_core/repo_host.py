"""Exact host-pinned independent Git selection for a trusted in-process host.

This constrains this dispatcher only. It is not an OS sandbox or proof of
remote identity. No payload, configured origin, or receipt creates a grant.
"""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading

from wiki_core.repo_read import _prepare_repo_read, _read_prepared_repo, remote_identity
from wiki_core.repository_reader import canonical_path


REPOSITORY_CAPABILITY = 'independent_git.read'
REPOSITORY_PUBLICATION = 'independent_git.derived_proposal'


def _storage_identity(root, *, before_read=None):
    """Reject Git storage redirects; bounded metadata walk, no blob reads."""
    dotgit, objects = root / '.git', root / '.git' / 'objects'
    git_stat = dotgit.lstat()
    if not stat.S_ISDIR(git_stat.st_mode):
        raise ValueError('repository storage unavailable')
    objects_stat = objects.lstat()
    if not stat.S_ISDIR(objects_stat.st_mode):
        raise ValueError('repository storage unavailable')
    if os.path.lexists(dotgit / 'commondir'):
        raise ValueError('repository storage requires an explicit adapter')
    config = dotgit / 'config'
    config_stat = config.lstat()
    if not stat.S_ISREG(config_stat.st_mode) or config_stat.st_nlink != 1:
        raise ValueError('repository configuration requires an explicit adapter')
    if os.path.lexists(dotgit / 'config.worktree'):
        raise ValueError('repository configuration requires an explicit adapter')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    if before_read is not None: before_read()
    with os.fdopen(os.open(config, flags), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (config_stat.st_dev, config_stat.st_ino):
            raise ValueError('repository configuration changed')
        raw = stream.read(100_001)
    if before_read is not None: before_read()
    if (len(raw) > 100_000 or b'\\' in raw or b'\x00' in raw
            or any(value in raw.lower() for value in (b'include', b'worktree', b'alternaterefscommand'))):
        raise ValueError('repository configuration requires an explicit adapter')
    count = 0
    pending = [objects]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                count += 1
                if count > 100_000:
                    raise ValueError('repository storage exceeds metadata limit')
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(Path(entry.path))
                elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError('repository storage requires an explicit adapter')
    if os.path.lexists(objects / 'info' / 'alternates'):
        raise ValueError('repository storage requires an explicit adapter')
    return (git_stat.st_dev, git_stat.st_ino, objects_stat.st_dev, objects_stat.st_ino,
            config_stat.st_dev, config_stat.st_ino, hashlib.sha256(raw).hexdigest())


@dataclass(frozen=True)
class RepositoryGrant:
    selection_id: str
    root: Path = field(repr=False)
    identity: str = field(repr=False)
    revision: str
    path: str
    executor: str
    integrator: str
    max_bytes: int = 100_000
    event_target: str | None = field(default=None, repr=False)
    _physical_root: tuple | None = field(init=False, default=None, repr=False, compare=False)
    _physical_storage: tuple | None = field(init=False, default=None, repr=False, compare=False)
    _pin_lock: object = field(init=False, default_factory=threading.RLock, repr=False, compare=False, hash=False)

    def __post_init__(self):
        if not isinstance(self.selection_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', self.selection_id):
            raise ValueError('invalid host repository grant')
        root = Path(self.root)
        if not root.is_absolute() or '..' in root.parts:
            raise ValueError('invalid host repository root')
        object.__setattr__(self, 'root', root)
        if (not isinstance(self.revision, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', self.revision)
                or canonical_path(self.path) != self.path or type(self.max_bytes) is not int
                or not 1 <= self.max_bytes <= 2_000_000
                or not all(isinstance(x, str) and x for x in (self.executor, self.integrator))):
            raise ValueError('invalid host repository grant')
        if remote_identity('https://' + self.identity)[0] != self.identity:
            raise ValueError('invalid host repository identity')
        if self.event_target is not None and canonical_path(self.event_target) != self.event_target:
            raise ValueError('invalid host publication target')


def _selection_ids(selection):
    if isinstance(selection, str):
        return [selection]
    if (not isinstance(selection, list) or not selection or len(selection) > 8
            or any(not isinstance(item, str) for item in selection)
            or len(set(selection)) != len(selection)):
        raise ValueError('repository selection unavailable')
    return sorted(selection)


def authorize_repository_grant(binding, policy, context_id, actor, selection_id):
    if not isinstance(selection_id, str):
        raise ValueError('repository selection unavailable')
    matches = [item for item in binding.repository_grants if item.selection_id == selection_id]
    policy.fresh()
    if (len(matches) != 1 or matches[0].executor != context_id or matches[0].integrator != actor
            or context_id not in binding.contexts or actor not in binding.contexts
            or not all(policy.permits_effect(reader, 'capabilities', REPOSITORY_CAPABILITY)
                       for reader in {context_id, actor})):
        raise ValueError('repository selection unavailable')
    return matches[0]


def authorize_repository_event(binding, policy, context_id, actor, selection_id, event_target):
    """Publication is a separate exact host grant, not a consequence of reading."""
    if selection_id is None:
        return
    for item in _selection_ids(selection_id):
        grant = authorize_repository_grant(binding, policy, context_id, actor, item)
        if (grant.event_target is None or grant.event_target != event_target
                or not all(policy.permits_effect(reader, 'publication', REPOSITORY_PUBLICATION)
                           for reader in {context_id, actor})):
            raise ValueError('repository publication unavailable')


def check_repository_storage(binding, policy, context_id, actor, selection_id):
    grant = authorize_repository_grant(binding, policy, context_id, actor, selection_id)
    try:
        with grant._pin_lock:
            info = grant.root.stat()
            if grant.root.resolve(strict=True) != grant.root or not stat.S_ISDIR(info.st_mode):
                raise ValueError('repository selection unavailable')
            physical_root = (info.st_dev, info.st_ino)
            physical_storage = _storage_identity(grant.root, before_read=policy.fresh)
            if grant._physical_root is None and grant._physical_storage is None:
                object.__setattr__(grant, '_physical_root', physical_root)
                object.__setattr__(grant, '_physical_storage', physical_storage)
            if physical_root != grant._physical_root or physical_storage != grant._physical_storage:
                raise ValueError('repository selection unavailable')
    except OSError as exc:
        raise ValueError('repository selection unavailable') from exc
    return grant


def selected_repository(binding, policy, context_id, actor, selection_id):
    """Revalidate binding, policy and physical root before every local Git I/O."""
    grant = authorize_repository_grant(binding, policy, context_id, actor, selection_id)
    def check():
        if check_repository_storage(binding, policy, context_id, actor, selection_id) != grant:
            raise ValueError('repository selection unavailable')
    prepared = _prepare_repo_read(grant.root, grant.identity, grant.revision, grant.path,
                                  max_bytes=grant.max_bytes, before_access=check)
    result = _read_prepared_repo(prepared)
    if result['revision'] != grant.revision or result['path'] != grant.path:
        raise ValueError('repository selection unavailable')
    # Do not expose root or the locally configured origin. A receipt binds bytes
    # and provenance; only the live host grant and policy authorize access.
    pinned = {'selection_id': grant.selection_id, 'root': str(grant.root), 'physical_root': grant._physical_root,
              'physical_storage': grant._physical_storage, 'identity': grant.identity,
              'revision': grant.revision, 'path': grant.path, 'executor': grant.executor,
              'integrator': grant.integrator, 'max_bytes': grant.max_bytes}
    grant_digest = hashlib.sha256(json.dumps(pinned, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'selection_id': selection_id, 'repository_identity': grant.identity, 'host_binding_digest': grant_digest,
            'revision': result['revision'], 'path': result['path'],
            'blob': result['blob'], 'document_sha256': result['document_sha256'],
            'content_sha256': result['content_sha256'], 'text': result['text']}
